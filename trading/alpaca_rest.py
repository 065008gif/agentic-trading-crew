"""
Thin wrapper over Alpaca's REST API (paper trading + free IEX market data).

Both MCP servers import this module. Nothing here talks to Alpaca's own MCP
server. Keys come only from environment variables.

Set MOCK_MARKET=1 to run everything offline with synthetic prices and a fake
account stored in .mock_state.json (used for tests and demos).
"""

from __future__ import annotations

import json
import math
import os
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

DATA_URL = "https://data.alpaca.markets"
TRADING_URL = os.environ.get("ALPACA_TRADING_URL", "https://paper-api.alpaca.markets")
FEED = os.environ.get("ALPACA_FEED", "iex")  # free feed; "sip" needs a paid plan
MOCK = os.environ.get("MOCK_MARKET", "0") == "1"
ROOT = Path(__file__).resolve().parent.parent
MOCK_STATE = ROOT / ".mock_state.json"


class AlpacaError(RuntimeError):
    pass


def market_today():
    """Today's date in New York (US market) time. EDT = UTC-4 until 1 Nov 2026,
    EST = UTC-5 after; a fixed rule avoids needing a time-zone database on Windows."""
    now = datetime.now(timezone.utc)
    offset = 4 if now < datetime(2026, 11, 1, 6, tzinfo=timezone.utc) else 5
    return (now - timedelta(hours=offset)).date()


def _keys() -> tuple[str, str]:
    k = os.environ.get("ALPACA_API_KEY") or os.environ.get("APCA_API_KEY_ID", "")
    s = os.environ.get("ALPACA_SECRET_KEY") or os.environ.get("APCA_API_SECRET_KEY", "")
    return k.strip(), s.strip()


def _headers() -> dict:
    k, s = _keys()
    if not k or not s:
        raise AlpacaError("Alpaca keys missing: set ALPACA_API_KEY and ALPACA_SECRET_KEY in your .env file.")
    return {"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s}


def _request(method: str, url: str, **kw):
    """HTTP call with retry on rate limits (429) and brief network errors."""
    for attempt in range(4):
        try:
            r = requests.request(method, url, headers=_headers(), timeout=25, **kw)
        except requests.RequestException as e:
            if attempt == 3:
                raise AlpacaError(f"Network error calling Alpaca: {e}") from e
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 429:
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code == 401 or r.status_code == 403:
            raise AlpacaError(f"Alpaca refused the keys ({r.status_code}). Check they are PAPER keys "
                              "and copied without spaces.")
        if r.status_code >= 400:
            try:
                msg = r.json().get("message", r.text)
            except ValueError:
                msg = r.text
            raise AlpacaError(f"Alpaca {r.status_code}: {msg}")
        return r.json() if r.text else {}
    raise AlpacaError("Alpaca rate limit hit repeatedly; wait a minute and retry.")


# ============================================================ market data
def get_bars(symbols: list[str], lookback_days: int = 400, timeframe: str = "1Day") -> dict[str, pd.DataFrame]:
    """ONE (paginated) request for many symbols -> {symbol: OHLCV DataFrame}."""
    symbols = [s.upper() for s in symbols]
    if MOCK:
        return {s: _mock_bars(s, lookback_days) for s in symbols}
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    params = {"symbols": ",".join(symbols), "timeframe": timeframe,
              "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "limit": 10000,
              "feed": FEED, "adjustment": "all"}
    rows: dict[str, list] = {}
    while True:
        payload = _request("GET", f"{DATA_URL}/v2/stocks/bars", params=params)
        for sym, bars in (payload.get("bars") or {}).items():
            rows.setdefault(sym, []).extend(bars)
        token = payload.get("next_page_token")
        if not token:
            break
        params["page_token"] = token
    out = {}
    for sym, bars in rows.items():
        df = pd.DataFrame(bars)
        df["t"] = pd.to_datetime(df["t"])
        df = (df.set_index("t").sort_index()
                .rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
              [["open", "high", "low", "close", "volume"]].astype(float))
        out[sym] = df[~df.index.duplicated(keep="last")]
    return out


def get_latest_prices(symbols: list[str]) -> dict[str, float]:
    """Latest trade price for many symbols in one call (snapshots endpoint)."""
    symbols = [s.upper() for s in symbols]
    if MOCK:
        return {s: float(_mock_bars(s, 30)["close"].iloc[-1]) for s in symbols}
    payload = _request("GET", f"{DATA_URL}/v2/stocks/snapshots",
                       params={"symbols": ",".join(symbols), "feed": FEED})
    out = {}
    for s, snap in (payload or {}).items():
        trade = (snap or {}).get("latestTrade") or {}
        bar = (snap or {}).get("dailyBar") or (snap or {}).get("prevDailyBar") or {}
        p = trade.get("p") or bar.get("c")
        if p:
            out[s] = float(p)
    return out


def get_news(symbols: list[str], days: int = 3, limit: int = 50, pages: int = 6) -> list[dict]:
    """Recent headlines (Alpaca news, Benzinga source) for many symbols in one call."""
    if MOCK:
        return [{"symbols": [s], "headline": f"{s} mock headline: analysts debate outlook",
                 "summary": "", "created_at": datetime.now(timezone.utc).isoformat(), "source": "mock"}
                for s in symbols]
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Alpaca returns at most 50 articles per page, newest first. Mega caps
    # (MSFT, META, AAPL) fill one page on their own, so read up to `pages`
    # pages or the smaller names get no news at all.
    out, token = [], None
    for _ in range(max(1, pages)):
        params = {"symbols": ",".join(s.upper() for s in symbols), "start": start,
                  "limit": min(limit, 50), "sort": "desc", "include_content": "false"}
        if token:
            params["page_token"] = token
        payload = _request("GET", f"{DATA_URL}/v1beta1/news", params=params)
        out += payload.get("news", [])
        token = payload.get("next_page_token")
        if not token:
            break
    return out


# ============================================================ trading
def get_account() -> dict:
    if MOCK:
        st = _mock_state()
        mv = sum(p["qty"] * _mock_price(s) for s, p in st["positions"].items())
        eq = st["cash"] + mv
        return {"equity": eq, "cash": st["cash"], "buying_power": st["cash"],
                "portfolio_value": eq, "last_equity": 100000.0, "status": "ACTIVE",
                "multiplier": "1", "account_number": "MOCK"}
    a = _request("GET", f"{TRADING_URL}/v2/account")
    keep = ["account_number", "status", "equity", "last_equity", "cash", "buying_power",
            "portfolio_value", "multiplier", "daytrade_count", "pattern_day_trader"]
    return {k: (float(a[k]) if k in ("equity", "last_equity", "cash", "buying_power", "portfolio_value")
                else a.get(k)) for k in keep if k in a}


def get_positions() -> dict[str, dict]:
    if MOCK:
        st = _mock_state()
        out = {}
        for s, p in st["positions"].items():
            px = _mock_price(s)
            out[s] = {"qty": p["qty"], "avg_entry": p["avg"], "market_value": p["qty"] * px,
                      "current_price": px, "unrealized_pl": p["qty"] * (px - p["avg"]),
                      "pl_pct": 100 * (px / p["avg"] - 1)}
        return out
    out = {}
    for p in _request("GET", f"{TRADING_URL}/v2/positions"):
        q = float(p["qty"])
        if q <= 0:
            continue  # long-only system; ignore any shorts
        out[p["symbol"]] = {"qty": q, "avg_entry": float(p["avg_entry_price"]),
                            "market_value": float(p["market_value"]),
                            "current_price": float(p["current_price"]),
                            "unrealized_pl": float(p["unrealized_pl"]),
                            "pl_pct": 100 * float(p["unrealized_plpc"])}
    return out


def get_clock() -> dict:
    if MOCK:
        return {"is_open": True, "next_open": "", "next_close": "", "timestamp": datetime.now().isoformat()}
    return _request("GET", f"{TRADING_URL}/v2/clock")


def list_open_orders() -> list[dict]:
    if MOCK:
        return []
    return [{"id": o["id"], "symbol": o["symbol"], "side": o["side"], "qty": o.get("qty"),
             "notional": o.get("notional"), "status": o["status"], "submitted_at": o["submitted_at"]}
            for o in _request("GET", f"{TRADING_URL}/v2/orders", params={"status": "open", "limit": 200})]


def cancel_orders_for(symbol: str | None = None) -> int:
    if MOCK:
        return 0
    if symbol is None:
        _request("DELETE", f"{TRADING_URL}/v2/orders")
        return -1
    n = 0
    for o in list_open_orders():
        if o["symbol"] == symbol.upper():
            _request("DELETE", f"{TRADING_URL}/v2/orders/{o['id']}")
            n += 1
    return n


def is_fractionable(symbol: str) -> bool:
    if MOCK:
        return True
    try:
        return bool(_request("GET", f"{TRADING_URL}/v2/assets/{symbol.upper()}").get("fractionable"))
    except AlpacaError:
        return False


def submit_market_order(symbol: str, side: str, qty: float | None = None,
                        notional: float | None = None) -> dict:
    """Market DAY order. Buys may use a dollar amount (notional); falls back to
    whole shares if the stock is not fractionable."""
    symbol, side = symbol.upper(), side.lower()
    if MOCK:
        return _mock_fill(symbol, side, qty, notional)
    body = {"symbol": symbol, "side": side, "type": "market", "time_in_force": "day"}
    if notional is not None:
        if is_fractionable(symbol):
            body["notional"] = str(round(notional, 2))
        else:
            px = get_latest_prices([symbol]).get(symbol)
            if not px:
                raise AlpacaError(f"No price for {symbol}")
            whole = math.floor(notional / px)
            if whole < 1:
                raise AlpacaError(f"{symbol} is not fractionable and ${notional:.0f} buys < 1 share")
            body["qty"] = str(whole)
    else:
        body["qty"] = str(qty)
    try:
        o = _request("POST", f"{TRADING_URL}/v2/orders", json=body)
    except AlpacaError as e:
        if "notional" not in body or not any(w in str(e).lower() for w in ("fraction", "notional")):
            raise
        px = get_latest_prices([symbol]).get(symbol)   # retry with whole shares
        whole = math.floor(float(body.pop("notional")) / px) if px else 0
        if whole < 1:
            raise
        body["qty"] = str(whole)
        o = _request("POST", f"{TRADING_URL}/v2/orders", json=body)
    return {"order_id": o["id"], "symbol": o["symbol"], "side": o["side"], "qty": o.get("qty"),
            "notional": o.get("notional"), "status": o["status"], "submitted_at": o["submitted_at"]}


def close_position(symbol: str) -> dict:
    symbol = symbol.upper()
    if MOCK:
        st = _mock_state()
        q = st["positions"].get(symbol, {}).get("qty", 0)
        return _mock_fill(symbol, "sell", q, None) if q else {"symbol": symbol, "status": "no position"}
    o = _request("DELETE", f"{TRADING_URL}/v2/positions/{symbol}")
    return {"order_id": o.get("id"), "symbol": symbol, "side": "sell", "qty": o.get("qty"),
            "status": o.get("status")}


def get_portfolio_history(period: str = "1M", timeframe: str = "1D") -> dict:
    if MOCK:
        return {"timestamp": [], "equity": [], "profit_loss_pct": []}
    return _request("GET", f"{TRADING_URL}/v2/account/portfolio/history",
                    params={"period": period, "timeframe": timeframe, "extended_hours": "false"})


# ============================================================ mock market
def _mock_bars(symbol: str, days: int) -> pd.DataFrame:
    rnd = random.Random(sum(map(ord, symbol)) * 7919)
    n = max(60, int(days * 252 / 365))
    drift = rnd.uniform(-0.001, 0.003)
    vol = rnd.uniform(0.012, 0.04)
    px, rows = rnd.uniform(30, 400), []
    idx = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=n)
    for _ in idx:
        r = rnd.gauss(drift, vol)
        o = px
        c = max(1.0, px * (1 + r))
        h = max(o, c) * (1 + abs(rnd.gauss(0, vol / 2)))
        lo = min(o, c) * (1 - abs(rnd.gauss(0, vol / 2)))
        rows.append((o, h, lo, c, rnd.randint(200_000, 3_000_000)))
        px = c
    return pd.DataFrame(rows, index=idx, columns=["open", "high", "low", "close", "volume"])


def _mock_price(symbol: str) -> float:
    return float(_mock_bars(symbol, 30)["close"].iloc[-1])


def _mock_state() -> dict:
    if MOCK_STATE.exists():
        return json.loads(MOCK_STATE.read_text(encoding="utf-8"))
    return {"cash": 100000.0, "positions": {}}


def _mock_fill(symbol, side, qty, notional) -> dict:
    st = _mock_state()
    px = _mock_price(symbol)
    q = float(qty) if qty is not None else round(float(notional) / px, 4)
    pos = st["positions"].get(symbol, {"qty": 0.0, "avg": px})
    if side == "buy":
        newq = pos["qty"] + q
        pos["avg"] = (pos["avg"] * pos["qty"] + px * q) / newq
        pos["qty"] = newq
        st["cash"] -= px * q
    else:
        q = min(q, pos["qty"])
        pos["qty"] -= q
        st["cash"] += px * q
    if pos["qty"] > 1e-6:
        st["positions"][symbol] = pos
    else:
        st["positions"].pop(symbol, None)
    MOCK_STATE.write_text(json.dumps(st))
    return {"order_id": f"mock-{int(time.time()*1000)}", "symbol": symbol, "side": side,
            "qty": str(round(q, 4)), "status": "filled", "submitted_at": datetime.now().isoformat()}
