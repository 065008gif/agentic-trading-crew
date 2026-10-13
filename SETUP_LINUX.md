# Setup on the college Linux computer (Akshit, account A)

This computer uses a plain Python **venv** (no extra installers) and **VS Code**.
Commands go in the VS Code terminal: **Terminal > New Terminal** (or `` Ctrl + ` ``).
Paste with `Ctrl + Shift + V` and press Enter. Wait for the prompt to come back before the next command.

## 1. Download the project and open it in VS Code (one time)

```bash
cd ~
git clone https://github.com/065008gif/agentic-trading-crew.git
cd agentic-trading-crew
code .
```

When VS Code asks **"Do you trust the authors of the files in this folder?"**, click **Yes, I trust the authors**.
When it suggests installing the recommended **Python** extensions, click **Install**.

## 2. Create the venv and install the libraries (one time, 3-5 minutes)

In the VS Code terminal (it opens inside the project folder):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The prompt now starts with `(.venv)`. Every new terminal in VS Code activates it automatically.
If it ever doesn't, run `source .venv/bin/activate`.

## 3. Put your keys in a private `.env` file

```bash
cp .env.example .env
code .env
```

Fill in right after each `=` (no spaces, no quotes): `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` (Alpaca **paper**),
`GROQ_API_KEY`, `ACCOUNT_LABEL=A`, `APP_PASSWORD`. Save with `Ctrl + S`.
`.env` never goes to GitHub (it is in `.gitignore`, and `sync_github.py` double-checks).

## 4. Sign in to GitHub inside VS Code (one time)

Click the **Accounts** icon (person, bottom-left) > **Sign in with GitHub** and finish in the browser.
After that, `git push` from the VS Code terminal works without typing a password.

## 5. Running things

Either type the commands below, or use the **Run and Debug** panel (`Ctrl + Shift + D`): pick an entry in the
drop-down at the top (they are numbered 1-6), press the green play button, and choose the account.

| What | Command |
|---|---|
| Check keys and connections (no orders) | `python check_setup.py` |
| Analysis only (no orders) | `python trading_crew.py --account A --mode analyze 2>&1 \| tee console_logs/runN.txt` |
| **Trade** (asks y/N before placing the orders) | `python trading_crew.py --account A` |
| Screener (scores ~80 stocks) | `python screen.py --top 30` |
| Web interface | `python app.py`, then http://localhost:8000 |
| **Whole evening, every 30 min** | `python run_session.py --account A --every 30 --sync` |
| Tests | `python -m pytest -q` |
| **Save everything to GitHub** | `python sync_github.py` |

Web interface on the phone: with `app.py` running, open a second terminal and run `ngrok http 8000`
(free ngrok account), then open the `https://....ngrok-free.app` link it prints.

## Daily routine (Monday to Friday, until 27 October)

**Once (do it now):** Settings > Power > **Automatic Suspend: Off** (screen blanking/locking is fine;
suspend would pause the session).

**Every trading evening, about 7:00 PM IST:**

```bash
cd ~/agentic-trading-crew
code .
```

In the VS Code terminal (**Terminal > New Terminal**, the line starts with `(.venv)`; if not, `source .venv/bin/activate`):

```bash
git pull
python run_session.py --account A --every 30 --sync
```

That is all. It waits for the 7:00 PM open, makes the first run at 7:10 PM, then runs the full crew every
30 minutes (auto mode, no y/N questions) until the 1:30 AM close, stops by itself, and saves everything
to GitHub. Leave VS Code open; you can lock the screen. To stop early press **Ctrl + C**: it still saves.
One line per run is written to `run_reports/A/session_log.txt`.

Before starting, put any teammates' zips (`reports_B_...zip`, `reports_C_...zip`) in **Downloads**;
the save step at the end imports them into `teammate_reports/`.

If the final save says it timed out (GitHub wanted a login), run `python sync_github.py` the next time you are at the PC.
On weekends and US holidays the session says "no trading session" and exits.

**Booking profit:** every run applies a *profit lock*: once a stock has been up 8% or more from our buy
price, it is sold if it falls back below half of its best gain (so at least half the gain is kept), and it
is not bought back the same day. On the **last day, 27 Oct**, the session sells **everything** at
1:00 AM IST (30 min before the close) so all gains are booked as cash. Make sure the session runs that
evening. Manual version: `python close_all.py --account A` (asks y/N).

Single manual run instead (asks y/N): `python trading_crew.py --account A`.

## Getting code updates

```bash
git pull
pip install -r requirements.txt
```
