# Setup on the college Linux computer (Akshit, account A)

Every command goes in the **Terminal** (open it with `Ctrl + Alt + T`).
Copy each block, paste it with `Ctrl + Shift + V`, and press Enter.
Wait for a command to finish (the prompt `$` comes back) before the next one.

## 1. Install uv (one time, no admin password needed)

uv downloads the right Python version and all libraries for you.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
uv --version
```

The last line should print something like `uv 0.9.x`. If it says "command not found", close the terminal, open a new one and run `uv --version` again.

## 2. Download the project

```bash
cd ~
git clone https://github.com/YOUR-GITHUB-NAME/agentic-trading-crew.git
cd agentic-trading-crew
```

## 3. Install everything (takes 2-4 minutes the first time)

```bash
uv sync
```

## 4. Put your keys in a private `.env` file

```bash
cp .env.example .env
nano .env
```

`nano` is a simple text editor that opens inside the terminal:

1. Use the arrow keys to move to `ALPACA_API_KEY=` and paste your Alpaca **paper** key right after the `=` (no spaces, no quotes).
2. Do the same for `ALPACA_SECRET_KEY=` and `GROQ_API_KEY=`.
3. Check `ACCOUNT_LABEL=A`.
4. Set `APP_PASSWORD=` to any password you'll remember (it protects the web page).
5. Save with `Ctrl + O`, then press Enter. Exit with `Ctrl + X`.

`.env` never goes to GitHub (it is listed in `.gitignore`).

## 5. Check the setup (places no orders)

```bash
uv run python check_setup.py
```

You want `[ OK ]` on the Alpaca, market data and LLM lines. If a line says `[FAIL]`, the message says what to fix.

## 6. First run: analysis only

```bash
uv run python trading_crew.py --account A --mode analyze
```

You'll see the four agents work one after another, then the Risk Manager's table of targets and orders. Nothing is traded in `analyze` mode. The agents' notes are saved in `run_reports/A/`.

## 7. Trade

```bash
uv run python trading_crew.py --account A
```

Same as above, but at the end it asks `Place these orders on your PAPER account? [y/N]`. Type `y` and Enter to trade.

## 8. Web interface (optional, also on your phone)

```bash
uv run python app.py
```

Open http://localhost:8000 in the browser. Type your app password under **Alpaca keys and app password** and reload the page.

To open it on your phone, install ngrok once (free account at ngrok.com, then follow its "Linux" install steps). Run this in a **second** terminal while `app.py` is running:

```bash
ngrok http 8000
```

Open the `https://....ngrok-free.app` link it prints on your phone.

## Daily routine (US market: 7:00 PM to 1:30 AM India time)

| India time | What to run |
|---|---|
| ~7:30 PM (after the open settles) | `uv run python trading_crew.py --account A` and approve |
| ~10:30 PM | run again (it only trades what changed) |
| ~1:00 AM (before the close) | run again |

Or let it run by itself every hour while the market is open:

```bash
uv run python trading_crew.py --account A --mode auto --loop 60
```

Stop it with `Ctrl + C`.

## Getting updates

When the code changes on GitHub:

```bash
cd ~/agentic-trading-crew
git pull
uv sync
```
