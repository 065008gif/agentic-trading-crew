"""
One command for a whole trading evening:

    python run_session.py --account A --every 30 --sync          (Akshit)
    uv run python run_session.py --account B --every 30          (teammates)

- If the US market is not open yet, it waits for the open (times shown in IST).
- First run 10 minutes after the open (the first minutes are the noisiest),
  then the full agent crew runs every --every minutes in auto mode
  (no y/N question), until the market closes (1:30 AM IST until 1 Nov 2026).
- At the close it stops by itself, then either saves everything to GitHub
  (--sync, Akshit's computer) or zips the run records to send to Akshit
  (teammates). Ctrl + C stops it early and still does that final step.
- If today is a weekend or US holiday, it says so and exits.
- A failed run (network, AI busy) is logged and the session carries on.
- A one-line summary of every run goes to run_reports/<account>/session_log.txt.

Keep the computer awake (turn off automatic suspend/sleep) while it runs.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import trading_crew as tc  # noqa: E402  (loads .env and the config)
from trading import mcp_bridge as bridge  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))   # India has no daylight saving


def ist(dt: datetime) -> str:
    return dt.astimezone(IST).strftime("%a %d %b %I:%M %p IST")


def get_clock() -> dict | None:
    """Market clock through the trading MCP server; retries for a few minutes."""
    for attempt in range(5):
        c = bridge.call(bridge.TRADING_SERVER, "get_market_clock", {}, tc.alpaca_env())
        if isinstance(c, dict) and "is_open" in c and c.get("timestamp"):
            return c
        print(f"  could not read the market clock ({str(c)[:100]}); retrying in 1 min")
        time.sleep(60)
    return None


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def sleep_until(target: datetime, now: datetime, label: str) -> None:
    secs = max(0.0, (target - now).total_seconds())
    if secs > 0:
        print(f"  {label}: {ist(target)} (in {int(secs // 60)} min). Leave this window open.")
        time.sleep(secs)


def log_line(account: str, text: str) -> None:
    d = ROOT / "run_reports" / account
    d.mkdir(parents=True, exist_ok=True)
    with (d / "session_log.txt").open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now(IST):%d-%m-%Y %H:%M} IST  {text}\n")


def finish(sync: bool) -> None:
    print("\n" + "=" * 70)
    if sync:
        print("Saving everything to GitHub ...")
        import sync_github
        sync_github.main()
    else:
        print("Zipping today's records to send to Akshit ...")
        subprocess.run([sys.executable, str(ROOT / "export_reports.py")], cwd=ROOT)
    print("Session finished. You can close VS Code.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the trading crew all evening, every N minutes")
    ap.add_argument("--account", default=os.environ.get("ACCOUNT_LABEL", "A"), help="A, B or C")
    ap.add_argument("--every", type=int, default=30, help="minutes between runs (default 30, minimum 15)")
    ap.add_argument("--start-delay", type=int, default=10, help="minutes after the open before the first run")
    ap.add_argument("--sync", action="store_true", help="at the end, save everything to GitHub (Akshit)")
    ap.add_argument("--no-llm", action="store_true", help="rules only, no AI agents")
    a = ap.parse_args()
    a.account = a.account.upper()
    every = timedelta(minutes=max(15, a.every))

    print("=" * 70)
    print(f" Trading session | account {a.account} | a run every {every.seconds // 60} min | auto mode")
    print(" Stops by itself at the market close. Ctrl + C stops it early.")
    print("=" * 70)

    runs, opened = 0, False
    try:
        while True:
            c = get_clock()
            if c is None:
                print("Market clock unavailable for 5 minutes. Check the internet, then start again.")
                break
            now = parse(c["timestamp"])
            if not c["is_open"]:
                if opened:
                    print(f"\nMarket closed ({ist(now)}). {runs} run(s) today.")
                    break
                nxt = parse(c["next_open"])
                if nxt - now > timedelta(hours=14):
                    print(f"No US trading session in the next 14 hours (weekend or holiday). "
                          f"Next open: {ist(nxt)}.")
                    return 0
                sleep_until(min(nxt + timedelta(minutes=a.start_delay), now + timedelta(minutes=30)),
                            now, "Market not open yet; waiting until")
                continue

            opened = True
            close = parse(c["next_close"])
            open_today = now.replace(hour=9, minute=30, second=0, microsecond=0)   # New York time
            first_ok = open_today + timedelta(minutes=a.start_delay)
            if runs == 0 and now < first_ok:
                sleep_until(first_ok, now, "Market just opened; first run at")
                continue
            if close - now < timedelta(minutes=5):
                sleep_until(close + timedelta(minutes=1), now, "Close is near; no new run. Stopping after")
                continue

            runs += 1
            started = now
            print(f"\n{'#' * 70}\n# Run {runs}  |  {ist(now)}  |  market closes {ist(close)}\n{'#' * 70}")
            try:
                plan = tc.run_once(a.account, mode="auto", use_llm=not a.no_llm)
                ex = plan.get("executions", [])
                bad = [e for e in ex if isinstance(e.get("result"), dict) and "error" in e["result"]]
                summary = (f"run {runs}: model {plan.get('model')}, regime {plan.get('regime')}, "
                           f"{len(ex)} order(s) sent, {len(bad)} error(s), "
                           f"invested after plan {plan.get('invested_after_pct')}%")
            except Exception as e:  # never stop the evening because of one bad run
                traceback.print_exc()
                summary = f"run {runs}: FAILED ({str(e)[:120]}) - will retry at the next slot"
            print("\n>> " + summary)
            log_line(a.account, summary)

            c2 = get_clock()
            now2 = parse(c2["timestamp"]) if c2 else now
            nxt_run = started + every
            if nxt_run >= close:
                sleep_until(close + timedelta(minutes=1), now2, "That was the last run today. Stopping after the close")
            else:
                sleep_until(nxt_run, now2, f"Run {runs} done. Next run")
    except KeyboardInterrupt:
        print("\nStopped by you (Ctrl + C).")
    log_line(a.account, f"session ended after {runs} run(s)")
    finish(a.sync)
    return 0


if __name__ == "__main__":
    sys.exit(main())
