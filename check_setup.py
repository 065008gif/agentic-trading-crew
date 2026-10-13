"""
Checks everything before the first trade:  python check_setup.py
  1. .env exists and has keys     2. Alpaca paper account reachable
  3. market data works (one batched call)   4. each LLM provider answers
Nothing is bought or sold.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONWARNINGS", "ignore")

OK, BAD = "[ OK ]", "[FAIL]"


def main():
    env = ROOT / ".env"
    if not env.exists():
        print(f"{BAD} No .env file. Copy .env.example to .env and fill in your keys.")
        return 1
    from dotenv import load_dotenv
    load_dotenv(env)
    from trading import alpaca_rest as ar
    failed = 0

    k, s = os.environ.get("ALPACA_API_KEY", ""), os.environ.get("ALPACA_SECRET_KEY", "")
    if not k or not s:
        print(f"{BAD} ALPACA_API_KEY / ALPACA_SECRET_KEY are empty in .env"); return 1
    if not k.startswith("PK"):
        print("[WARN] Your Alpaca key does not start with 'PK'. Paper keys usually do: check you copied PAPER keys.")

    try:
        a = ar.get_account()
        print(f"{OK} Alpaca paper account {a.get('account_number')}: equity ${a['equity']:,.2f}, cash ${a['cash']:,.2f}")
    except Exception as e:
        print(f"{BAD} Alpaca account: {e}"); failed += 1

    try:
        bars = ar.get_bars(["SPY", "MU", "AAPL"], 30)
        print(f"{OK} Market data: {len(bars)} symbols in one call, SPY last close {bars['SPY']['close'].iloc[-1]:.2f}")
    except Exception as e:
        print(f"{BAD} Market data: {e}"); failed += 1

    try:
        news = ar.get_news(["AAPL"], days=3, limit=3)
        print(f"{OK} News feed: {len(news)} recent AAPL headlines")
    except Exception as e:
        print(f"[WARN] News feed unavailable ({str(e)[:90]}). The News agent will work without it.")

    from trading import llm as L
    chain = L.chain()
    if not chain:
        print(f"{BAD} No LLM key set. Add GROQ_API_KEY to .env (free at console.groq.com)."); failed += 1
    for name, llm in chain:
        try:
            reply = llm.call([{"role": "user", "content": "Reply with the single word READY."}])
            print(f"{OK} LLM {L.describe(name)} answered: {str(reply).strip()[:40]}")
        except Exception as e:
            if name == chain[0][0]:
                print(f"{BAD} Main LLM {L.describe(name)}: {str(e)[:160]}")
                failed += 1
            else:  # backups are optional: trading still works with the main model
                print(f"[WARN] Backup LLM {L.describe(name)} unavailable for this key: {str(e)[:110]}")
                print("       Optional fix: run  python list_groq_models.py  and put one of the listed"
                      " ids in GROQ_BACKUP_MODEL in .env")

    if failed:
        print(f"\n{failed} problem(s) above. Fix them, then run this again.")
    else:
        print(f"\nAll good. Next: python trading_crew.py --account {os.environ.get('ACCOUNT_LABEL', 'A')} --mode analyze")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
