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
| Tests | `python -m pytest -q` |
| **Save everything to GitHub** | `python sync_github.py` |

Web interface on the phone: with `app.py` running, open a second terminal and run `ngrok http 8000`
(free ngrok account), then open the `https://....ngrok-free.app` link it prints.

## Daily routine (US market: 7:00 PM to 1:30 AM India time, Monday to Friday, until 27 October)

| India time | Do this |
|---|---|
| ~7:30 PM | `git pull`, then trade: `python trading_crew.py --account A`, approve with `y` |
| ~10:30 PM | run again (it only trades what changed) |
| ~1:00 AM (if awake) | run again |
| End of the session | put the teammates' zips (from WhatsApp/email) in Downloads, then `python sync_github.py` |

`sync_github.py` unpacks the teammates' `reports_B_...zip` / `reports_C_...zip` into `teammate_reports/B` and `teammate_reports/C`,
moves loose `run*.txt` / `screen*.txt` files into `console_logs/`, commits everything, pulls and pushes.

## Getting code updates

```bash
git pull
pip install -r requirements.txt
```
