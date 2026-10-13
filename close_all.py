"""
Book everything: cancel open orders and sell every position in one account.

    python close_all.py --account A          asks y/N first
    python close_all.py --account A --yes    no question (used by run_session.py)

run_session.py calls this by itself on the last trading day (27 Oct 2026,
config/portfolios.json > group_rules), 30 minutes before the close, so every
gain is realised as cash before the competition ends.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import trading_crew as tc  # noqa: E402  (loads .env)
from trading import mcp_bridge as bridge  # noqa: E402
from trading.reports import RunRecorder, log_trade  # noqa: E402


def close_all(account: str, confirm: bool = True) -> list:
    env = tc.alpaca_env()
    acct, pos = bridge.call_many(bridge.TRADING_SERVER, [("get_account_info", {}), ("positions_data", {})], env)
    positions = pos.get("positions", {}) if isinstance(pos, dict) else {}
    if not positions:
        print("No open positions: nothing to sell.")
        return []
    total = sum(p["market_value"] for p in positions.values())
    upl = sum(p.get("unrealized_pl", 0) for p in positions.values())
    print(f"Account {account}: {len(positions)} positions worth ${total:,.0f}, unrealised P/L ${upl:+,.0f}")
    for s, p in sorted(positions.items()):
        print(f"  {s:<6} ${p['market_value']:>10,.0f}  {p['pl_pct']:+.1f}%")
    if confirm:
        try:
            if input("Sell ALL of these now and keep the cash? [y/N]: ").strip().lower() not in ("y", "yes"):
                print("Nothing sold.")
                return []
        except EOFError:
            return []
    calls = [("cancel_orders", {"symbol": ""})] + [("close_position", {"symbol": s}) for s in positions]
    results = bridge.call_many(bridge.TRADING_SERVER, calls, env)[1:]
    rec = RunRecorder(account, "rules (book all profits)", list(positions), "close-all")
    lines = []
    for (s, p), r in zip(positions.items(), results):
        order = {"symbol": s, "side": "sell", "type": "close", "dollars": round(p["market_value"], 2),
                 "reason": f"final day: book all profits ({p['pl_pct']:+.1f}%)"}
        log_trade(account, order, r)
        status = r.get("status", r.get("error", "?")) if isinstance(r, dict) else str(r)[:80]
        lines.append(f"- SELL ALL {s} ${p['market_value']:,.0f} ({p['pl_pct']:+.1f}%): {status}")
    text = (f"Booked all positions. Value ${total:,.0f}, unrealised P/L before selling ${upl:+,.0f}.\n\n"
            + "\n".join(lines))
    rec.write("Executor", "Final day: all positions sold to book the profit", text)
    print("\n" + text)
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="Sell every position in one account (book all profits)")
    ap.add_argument("--account", required=True, help="A, B or C")
    ap.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    a = ap.parse_args()
    close_all(a.account.upper(), confirm=not a.yes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
