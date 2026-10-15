"""
Small per-account memory between runs, kept in run_reports/<account>/state.json:
- peaks: the highest price seen for each stock while we held it (for the profit lock)
- no_rebuy: stocks fully sold today, so a later run does not buy them straight back
- bought: stocks first bought today, so a later run does not sell them again
  today for a soft reason (prevents buy-sell-buy flip-flops seen on 13 Oct)
"""

from __future__ import annotations

import json
from datetime import date

from trading.reports import REPORTS


def _path(account: str):
    return REPORTS / account / "state.json"


def _bought_day(v):
    return v.get("date") if isinstance(v, dict) else v


def load(account: str) -> dict:
    try:
        st = json.loads(_path(account).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    st.setdefault("peaks", {})
    st.setdefault("no_rebuy", {})
    st.setdefault("bought", {})
    return st


def save(account: str, st: dict) -> None:
    p = _path(account)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, indent=1, sort_keys=True), encoding="utf-8")


def update_peaks(st: dict, positions: dict, rows: list[dict]) -> dict:
    """Raise each held stock's peak to the latest price; forget stocks we no longer hold."""
    price = {r["symbol"]: r.get("close") for r in rows}
    peaks = {}
    for sym, p in positions.items():
        now = price.get(sym) or p.get("current_price") or 0
        peaks[sym] = round(max(float(st["peaks"].get(sym) or 0), float(now or 0),
                               float(p.get("avg_entry") or 0)), 4)
    st["peaks"] = peaks
    return peaks


def blocked_today(st: dict, today: date) -> dict:
    """{symbol: score when sold (None after a stop / profit lock)} for stocks sold today."""
    return {s: (v.get("score") if isinstance(v, dict) else None)
            for s, v in st["no_rebuy"].items() if _bought_day(v) == today.isoformat()}


def bought_today(st: dict, today: date) -> dict:
    """{symbol: technical (alpha) score at purchase} for stocks first bought today."""
    return {s: (v.get("score") if isinstance(v, dict) else None)
            for s, v in st["bought"].items() if _bought_day(v) == today.isoformat()}


def record_exits(st: dict, plan: dict, today: date) -> None:
    """After orders were sent: remember today's full sales and first buys."""
    t = today.isoformat()
    st["no_rebuy"] = {s: v for s, v in st["no_rebuy"].items() if _bought_day(v) == t}
    alphas = {x["symbol"]: x.get("alpha") for x in plan.get("targets", [])}
    st["bought"] = {s: v for s, v in st["bought"].items() if _bought_day(v) == t}
    new_buys = {x["symbol"]: x.get("alpha") for x in plan.get("targets", []) if x.get("action") == "BUY"}
    for o in plan.get("orders", []):
        if o.get("side") == "sell" and o.get("type") == "close":
            hard = "stop hit" in o.get("reason", "") or "profit lock" in o.get("reason", "")
            st["no_rebuy"][o["symbol"]] = {"date": t, "score": None if hard else alphas.get(o["symbol"])}
            st["peaks"].pop(o["symbol"], None)
            st["bought"].pop(o["symbol"], None)
        elif o.get("side") == "buy" and o["symbol"] in new_buys:
            st["bought"][o["symbol"]] = {"date": t, "score": new_buys[o["symbol"]]}
