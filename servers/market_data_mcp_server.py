"""
MCP SERVER 1 - Market data, technical indicators, Alpha Score, regime, news.
Transport: stdio (started automatically by the MCP client, trading_crew.py).

Tools
-----
  fetch_ohlcv_batch(symbols)          ONE Alpaca call for every symbol + benchmarks; caches bars
  compute_alpha_scores(symbols, ...)  20+ indicators and the composite Alpha Score, all symbols at once
  get_market_regime()                 SPY / QQQ trend + high-beta vs low-vol risk appetite
  get_news_digest(symbols)            Alpaca news headlines (one call) + sentiment + earnings dates
  get_indicator_detail(symbol)        every raw indicator value for one symbol (drill-down)

All heavy maths runs here in plain Python, so the LLM agents receive short,
ready-made summaries instead of raw price data. This keeps every run inside
the free Groq token limits.
"""

import json
import re
import os
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from trading import alpaca_rest as ar  # noqa: E402
from trading.indicators import snapshot  # noqa: E402
from trading.scoring import FAMILIES, alpha_score, regime_score  # noqa: E402
from trading.sentiment import score_headline  # noqa: E402

mcp = FastMCP("MarketData", log_level="WARNING")

BENCHMARKS = ["SPY", "QQQ", "SPHB", "SPLV"]
_cache: dict = {}   # symbol -> DataFrame
EARNINGS = {k: v for k, v in json.loads((ROOT / "config" / "earnings.json").read_text(encoding="utf-8")).items()
            if not k.startswith("_")}


def _clean(symbols) -> list[str]:
    if isinstance(symbols, str):
        try:
            symbols = json.loads(symbols)
        except ValueError:
            symbols = symbols.replace(",", " ").split()
    out = []
    for s in symbols:
        s = str(s).strip().upper()
        if s and s not in out:
            out.append(s)
    return out


def _ensure(symbols: list[str]) -> list[str]:
    """Fetch any symbol (plus benchmarks) not yet cached, in one call."""
    need = [s for s in symbols + BENCHMARKS if s not in _cache]
    if need:
        _cache.update(ar.get_bars(need, 400))
    return [s for s in symbols if s not in _cache]


def _earnings_note(sym: str) -> str | None:
    e = EARNINGS.get(sym)
    if not e:
        return None
    d = date.fromisoformat(e["date"])
    days = (d - ar.market_today()).days
    if days < -1:
        return None
    return f"earnings {e['date']} {e['time']} ({days}d)"


@mcp.tool()
def fetch_ohlcv_batch(symbols: list[str], lookback_days: int = 400) -> str:
    """
    Fetch daily OHLCV bars for ALL symbols in ONE Alpaca request (benchmarks
    SPY, QQQ, SPHB, SPLV are added automatically) and cache them.
    Call this ONCE with the full watch-list before any other tool.
    Arguments: symbols (list of tickers), lookback_days (int, default 400).
    """
    syms = _clean(symbols)
    frames = ar.get_bars(syms + BENCHMARKS, lookback_days)
    _cache.update(frames)
    lines = [f"{s}: {len(frames[s])} bars to {str(frames[s].index[-1])[:10]}, last close "
             f"{float(frames[s]['close'].iloc[-1]):.2f}" for s in syms if s in frames]
    missing = [s for s in syms if s not in frames]
    return (f"Fetched {len(lines)} symbols + benchmarks {[b for b in BENCHMARKS if b in frames]} "
            f"in 1 Alpaca call.\n" + "\n".join(lines) + (f"\nMISSING: {', '.join(missing)}" if missing else ""))


def _scores(symbols, profile, families):
    """Indicators + Alpha Score for every symbol: (rows, text table, families used, missing)."""
    syms = _clean(symbols)
    missing = _ensure(syms)
    fams = [f for f in (families or FAMILIES) if f in FAMILIES] or FAMILIES
    spy = _cache.get("SPY")
    rows = []
    for s in syms:
        if s not in _cache:
            continue
        df = _cache[s]
        if len(df) < 60:
            missing.append(s)
            continue
        snap = snapshot(df, spy)
        sc = alpha_score(snap, profile, fams)
        rows.append({"symbol": s, **sc, "close": snap["close"], "rsi14": snap["rsi14"],
                     "rsi2": snap["rsi2"], "macd_hist": snap["macd_hist"], "adx": snap["adx"],
                     "roc10": snap["roc10"], "rs20": snap.get("rs_vs_spy_20d"),
                     "zscore": snap["zscore20"], "atr_pct": snap["atr_pct"],
                     "beta60": snap.get("beta60"), "stop": snap["chandelier_stop"],
                     "breakout": snap["donchian_breakout"], "breakdown": snap["donchian_breakdown"],
                     "earnings": _earnings_note(s), "as_of": snap["as_of"]})
    rows.sort(key=lambda r: r["alpha_score"], reverse=True)
    lines = ["rank symbol score lean | trend mom rs vol brk stat | rsi14 rsi2 roc10 rs20 z beta | note"]
    for i, r in enumerate(rows, 1):
        f = r["families"]
        note = ", ".join(x for x in [
            "BREAKOUT" if r["breakout"] else "", "BREAKDOWN" if r["breakdown"] else "",
            r["earnings"] or ""] if x)
        lines.append(f"{i} {r['symbol']} {r['alpha_score']} {r['lean']} | {f['trend']:.0f} {f['momentum']:.0f} "
                     f"{f['rs']:.0f} {f['volume']:.0f} {f['volatility']:.0f} {f['stats']:.0f} | "
                     f"{r['rsi14']} {r['rsi2']} {r['roc10']} {r['rs20']} {r['zscore']} {r['beta60']} | {note}")
    return rows, "\n".join(lines), fams, sorted(set(missing))


@mcp.tool()
def compute_alpha_scores(symbols: list[str], profile: str = "momentum",
                         families: list[str] | None = None) -> str:
    """
    Compute 20+ technical indicators and the composite Alpha Score (0-100)
    for EVERY symbol in one call, ranked best first.
    Arguments: symbols (list of tickers); profile (momentum | catalyst |
    rebound | balanced); families (subset of trend, momentum, rs, volume,
    volatility, stats).
    Returns a compact text table ranked best first. Copy numbers exactly.
    Columns: trend mom rs vol brk stat are the six family sub-scores (0-100).
    """
    rows, table, fams, miss = _scores(symbols, profile, families)
    return (f"Alpha Scores (profile={profile}, families={','.join(fams)})\n{table}"
            + (f"\nMISSING DATA: {', '.join(miss)}" if miss else ""))


@mcp.tool()
def alpha_scores_data(symbols: list[str], profile: str = "momentum",
                      families: list[str] | None = None) -> dict:
    """Same as compute_alpha_scores but returns every row as data (used by the
    rule-based Risk Manager, not by the LLM agents)."""
    rows, table, fams, miss = _scores(symbols, profile, families)
    return {"profile": profile, "families_used": fams, "table": table, "rows": rows, "missing": miss}


@mcp.tool()
def get_market_regime(benchmarks: list[str] = ["SPY", "QQQ"]) -> str:  # noqa: B006
    """
    Market regime from index trend plus risk appetite (SPHB high-beta vs
    SPLV low-volatility ratio, 20-day change).
    Argument: benchmarks - the index ETFs whose trend is scored; use
    ["SPY", "QQQ"] (allowed: SPY, QQQ).
    Returns regime_score 0-100, regime label (RISK-ON / NEUTRAL / CAUTION /
    RISK-OFF) and invest_fraction (share of the account to keep invested).
    """
    use = [b for b in _clean(benchmarks or []) if b in ("SPY", "QQQ")] or ["SPY", "QQQ"]
    _ensure([])
    spy = snapshot(_cache["SPY"]) if "SPY" in _cache and "SPY" in use else None
    qqq = snapshot(_cache["QQQ"]) if "QQQ" in _cache and "QQQ" in use else None
    if spy is None and qqq is not None:   # regime_score expects a primary index
        spy, qqq = qqq, None
    ratio_roc = None
    if "SPHB" in _cache and "SPLV" in _cache:
        r = (_cache["SPHB"]["close"] / _cache["SPLV"]["close"]).dropna()
        if len(r) > 21:
            ratio_roc = round(float(100 * (r.iloc[-1] / r.iloc[-21] - 1)), 2)
    out = regime_score(spy, qqq, ratio_roc)
    out.update({"spy_close": spy and spy["close"], "spy_rsi14": spy and spy["rsi14"],
                "spy_vs_ema50_pct": spy and spy["ema50"] and round(100 * (spy["close"] / spy["ema50"] - 1), 2),
                "qqq_roc10": qqq and qqq["roc10"], "high_beta_vs_low_vol_20d_pct": ratio_roc,
                "as_of": spy and spy["as_of"]})
    return json.dumps(out)


def _relevant(article: dict, sym: str) -> bool:
    """An article counts for a stock only if it is really about that stock:
    tagged with at most 3 tickers (market round-ups tag 10+), or the ticker
    is written in the headline."""
    tags = article.get("symbols", [])
    return len(tags) <= 3 or re.search(r"\b" + re.escape(sym) + r"\b", article.get("headline", "")) is not None


def _news_rows(symbols, days: int = 3, per_symbol: int = 2) -> tuple[list[dict], str | None]:
    syms = _clean(symbols)
    try:
        news, err = ar.get_news(syms, days=days), None
    except Exception as e:  # news is optional; never break the run
        news, err = [], str(e)
    by = {s: [] for s in syms}
    for n in news:
        for s in n.get("symbols", []):
            if s in by and _relevant(n, s):
                by[s].append(n)
    rows = []
    for s in syms:
        items = by[s]
        # an article about this stock alone counts fully; one shared with
        # other tickers counts half (unless the ticker is in the headline)
        w = [1.0 if len(n.get("symbols", [])) == 1
             or re.search(r"\b" + re.escape(s) + r"\b", n.get("headline", "")) else 0.5 for n in items]
        sc = [score_headline(n.get("headline", "")) for n in items]
        # shrink toward 0 (+2 in the denominator): one headline can never read as +/-1.0
        sent = round(sum(a * b for a, b in zip(w, sc)) / (sum(w) + 2), 2) if items else 0.0
        rows.append({"symbol": s, "articles": len(items), "sentiment": sent,
                     "headlines": [n.get("headline", "")[:110] for n in items[:per_symbol]],
                     "earnings": _earnings_note(s)})
    return rows, err


@mcp.tool()
def get_news_digest(symbols: list[str], days: int = 3, per_symbol: int = 2) -> str:
    """
    Recent news for ALL symbols, with a sentiment score per symbol
    (-1 bearish .. +1 bullish, shrunk toward 0 when there are few articles),
    the top headlines, and any earnings date inside the trading window.
    Market round-ups that merely tag a stock are left out.
    Arguments: symbols (list), days (int, default 3), per_symbol (int, default 2).
    """
    rows, err = _news_rows(symbols, days, per_symbol)
    lines = [f"{r['symbol']}: sent {r['sentiment']:+.2f} ({r['articles']} art)"
             + (f" | {r['earnings']}" if r["earnings"] else "")
             + "".join(f"\n   - {h}" for h in r["headlines"]) for r in rows]
    head = f"News digest, last {days} days" + (f" (news unavailable: {err[:80]})" if err else "")
    return head + "\n" + "\n".join(lines)


@mcp.tool()
def news_data(symbols: list[str], days: int = 3) -> dict:
    """Same news as get_news_digest but as data rows (used by the Risk Manager
    code to check the Portfolio Manager's adjustments against real news)."""
    rows, err = _news_rows(symbols, days)
    return {"rows": rows, "error": err}


@mcp.tool()
def get_indicator_detail(symbol: str) -> str:
    """Every raw indicator value for ONE symbol (EMA, ADX, RSI, MACD, ROC, TSI,
    CMF, OBV, MFI, PVO, ATR, Bollinger, Donchian, z-score, beta). Argument: symbol."""
    s = symbol.strip().upper()
    _ensure([s])
    if s not in _cache:
        return f"no data for {s}"
    return json.dumps(snapshot(_cache[s], _cache.get("SPY")))


if __name__ == "__main__":
    mcp.run(transport="stdio")
