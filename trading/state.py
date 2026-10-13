"""
Small per-account memory between runs, kept in run_reports/<account>/state.json:
- peaks: the highest price seen for each stock while we held it (for the profit lock)
- no_rebuy: stocks sold by a stop or the profit lock, with the day they were sold,
  so the next run (30 minutes later) does not buy them straight back.
"""

from __future__ import annotations

import json
from datetime import date

from trading.reports import REPORTS


def _path(account: str):
    return REPORTS / account / "state.json"


def load(account: str) -> dict:
    try:
        st = json.loads(_path(account).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    st.setdefault("peaks", {})
    st.setdefault("no_rebuy", {})
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


def blocked_today(st: dict, today: date) -> set:
    return {s for s, d in st["no_rebuy"].items() if d == today.isoformat()}


def record_exits(st: dict, plan: dict, today: date) -> None:
    """After orders were sent: remember stop / profit-lock sales for today."""
    st["no_rebuy"] = {s: d for s, d in st["no_rebuy"].items() if d == today.isoformat()}
    for o in plan.get("orders", []):
        if o.get("side") == "sell" and ("stop hit" in o.get("reason", "") or "profit lock" in o.get("reason", "")):
            st["no_rebuy"][o["symbol"]] = today.isoformat()
            st["peaks"].pop(o["symbol"], None)
