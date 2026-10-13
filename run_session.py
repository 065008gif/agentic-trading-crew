"""
One command for a whole trading evening:

    python run_session.py --account A --sync          (Akshit)
    uv run python run_session.py --account B          (teammates)

- If the US market is not open yet, it waits for the open (times shown in IST).
- First run 10 minutes after the open (the first minutes are the noisiest),
  then a run every --every minutes (default 15) in auto mode: fresh prices,
  scores, stops and profit locks every run, and the four AI agents run every
  time too (--ai-every 15). When a free model's daily limit is used up, the
  next free model takes over (Groq 120b -> 20b -> qwen -> OpenRouter -> Ollama
  Cloud), and as a last resort the run is rules-only (still trades safely).
  (no y/N question), until the market closes (1:30 AM IST until 1 Nov 2026).
- At the close it stops by itself, then either saves everything to GitHub
  (--sync, Akshit's computer) or zips the run records to send to Akshit
  (teammates). Ctrl + C stops it early and still does that final step.
- If today is a weekend or US holiday, it says so and exits.
- On the last trading day (config/portfolios.json > group_rules >
  last_trading_day, 27 Oct 2026) it sells EVERY position 30 minutes before
  the close (1:00 AM IST), so all gains are booked as cash, and makes no
  further trades. After that date it refuses to trade.
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
    from trading.reports import REPORTS
    d = REPORTS / account
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
    ap.add_argument("--every", type=int, default=15, help="minutes between runs (default 15, minimum 10)")
    ap.add_argument("--ai-every", type=int, default=15,
                    help="the four AI agents run at most this often (default 15 = every run); with a larger "
                         "value the runs in between reuse their view with fresh prices, stops and profit locks")
    ap.add_argument("--start-delay", type=int, default=10, help="minutes after the open before the first run")
    ap.add_argument("--sync", action="store_true", help="at the end, save everything to GitHub (Akshit)")
    ap.add_argument("--no-llm", action="store_true", help="rules only, no AI agents")
    a = ap.parse_args()
    a.account = a.account.upper()
    every = timedelta(minutes=max(10, a.every))

    print("=" * 70)
    print(f" Trading session | account {a.account} | a run every {every.seconds // 60} min | auto mode")
    print(" Stops by itself at the market close. Ctrl + C stops it early.")
    print("=" * 70)

    rules = tc.CONFIG.get("group_rules", {})
    last_day = rules.get("last_trading_day")                     # e.g. "2026-10-27"
    book_min = int(rules.get("book_profits_minutes_before_close", 30))
    runs, opened, booked = 0, False, False
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
            if last_day and now.date().isoformat() > last_day:
                print(f"The trading competition ended on {last_day}. No trades placed.")
                return 0
            is_last = bool(last_day) and now.date().isoformat() == last_day
            book_at = close - timedelta(minutes=book_min)
            if is_last and now >= book_at:
                if not booked:
                    print(f"\n{'#' * 70}\n# LAST TRADING DAY: selling everything to book the profit ({ist(now)})\n{'#' * 70}")
                    try:
                        from close_all import close_all
                        res = close_all(a.account, confirm=False)
                        log_line(a.account, f"final day: sold all {len(res)} position(s) to book the profit")
                    except Exception as e:
                        traceback.print_exc()
                        log_line(a.account, f"final day: close-all FAILED ({str(e)[:120]})")
                        print("!! Selling failed. Run  python close_all.py --account " + a.account + "  now.")
                    booked = True
                sleep_until(close + timedelta(minutes=1), now, "All sold. Stopping after the close")
                continue
            open_today = now.replace(hour=9, minute=30, second=0, microsecond=0)   # New York time
            first_ok = open_today + timedelta(minutes=a.start_delay)
            if runs == 0 and now < first_ok:
                sleep_until(first_ok, now, "Market just opened; first run at")
                continue
            if close - now < timedelta(minutes=10):   # no new run in the last 10 minutes
                sleep_until(close + timedelta(minutes=1), now, "Close is near; no new run. Stopping after")
                continue

            runs += 1
            started = now
            print(f"\n{'#' * 70}\n# Run {runs}  |  {ist(now)}  |  market closes {ist(close)}\n{'#' * 70}")
            try:
                plan = tc.run_once(a.account, mode="auto", use_llm=not a.no_llm,
                                   ai_every_min=max(0, a.ai_every - 2))   # -2 so timing jitter never skips a refresh
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
            if is_last and nxt_run >= book_at:
                sleep_until(book_at, now2, "Last day: next step is selling everything at")
                continue
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
