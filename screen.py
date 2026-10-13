"""
Stock screener: scores the whole universe in config/universe.json with the
same Alpha Score the agents use, through the market-data MCP server
(one Alpaca call for all symbols). Places no orders and uses no LLM.

    python screen.py                      top 25 for each strategy profile
    python screen.py --top 40
    python screen.py --profiles momentum

Columns: Alpha Score, lean, six family sub-scores, RSI14, 10-day return,
20-day return vs SPY, beta, and flags: HB = confirmed high-beta member,
hb? = listed as member in May (re-check), BRKOUT/BRKDN = 20-day
breakout/breakdown, and the next earnings date if inside the window.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
# Windows consoles and redirected output (| tee, > file) may not be UTF-8;
# never crash on a symbol an LLM wrote, print a '?' instead.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONWARNINGS", "ignore")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from trading import mcp_bridge as bridge  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Score the screening universe (no orders, no LLM)")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--profiles", nargs="*", default=["momentum", "catalyst", "rebound"])
    a = ap.parse_args()

    uni = json.loads((ROOT / "config" / "universe.json").read_text(encoding="utf-8"))
    confirmed, may = set(uni["high_beta_confirmed"]), set(uni["high_beta_listed_may"])
    symbols = list(dict.fromkeys(uni["high_beta_confirmed"] + uni["high_beta_listed_may"] + uni["others"]))
    env = {"ALPACA_API_KEY": os.environ.get("ALPACA_API_KEY", ""),
           "ALPACA_SECRET_KEY": os.environ.get("ALPACA_SECRET_KEY", "")}

    calls = [("get_market_regime", {"benchmarks": ["SPY", "QQQ"]})]
    calls += [("alpha_scores_data", {"symbols": symbols, "profile": p}) for p in a.profiles]
    results = bridge.call_many(bridge.MARKET_SERVER, calls, env)
    regime = results[0]
    if isinstance(regime, dict) and "error" in regime:
        print("Market data failed:", regime["error"])
        return 1
    print(f"Universe: {len(symbols)} stocks | regime {regime.get('regime')} ({regime.get('regime_score')}) "
          f"| data as of {regime.get('as_of')}\n")

    for profile, res in zip(a.profiles, results[1:]):
        if not isinstance(res, dict) or "rows" not in res:
            print(f"{profile}: failed: {res}")
            continue
        print(f"=== profile: {profile} | top {a.top} ===")
        print(f"{'#':>2} {'sym':<6}{'score':>6} {'lean':<8} trend mom  rs vol brk stat   rsi  roc10   rs20  beta  flags")
        for i, r in enumerate(res["rows"][: a.top], 1):
            f = r["families"]
            flags = []
            if r["symbol"] in confirmed:
                flags.append("HB")
            elif r["symbol"] in may:
                flags.append("hb?")
            if r.get("breakout"):
                flags.append("BRKOUT")
            if r.get("breakdown"):
                flags.append("BRKDN")
            if r.get("earnings"):
                flags.append(r["earnings"])

            def num(x, fmt):
                return format(x, fmt) if isinstance(x, (int, float)) else "  n/a"
            print(f"{i:>2} {r['symbol']:<6}{r['alpha_score']:>6.1f} {r['lean']:<8}"
                  f"{f['trend']:>5.0f}{f['momentum']:>4.0f}{f['rs']:>4.0f}{f['volume']:>4.0f}{f['volatility']:>4.0f}"
                  f"{f['stats']:>5.0f} {num(r.get('rsi14'), '5.1f')} {num(r.get('roc10'), '6.1f')} "
                  f"{num(r.get('rs20'), '6.1f')} {num(r.get('beta60'), '5.2f')}  {' '.join(flags)}")
        if res.get("missing"):
            print("missing data:", ", ".join(res["missing"]))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
