# Setup on a Windows laptop (teammates: accounts B and C)

You only need to do this once. It takes about 15 minutes.
You will copy-paste commands into **PowerShell**. Nothing here costs money.

**Before you start, have these ready in a notepad:**
- your Alpaca **paper** API key and secret key (app.alpaca.markets, with "Paper" selected at the top-left, then **API Keys** on the Home page)
- your free Groq API key (console.groq.com, then **API Keys**, then **Create API Key**)
- which account you are: **B** or **C** (Akshit will tell you)

## 1. Open PowerShell

Press the **Windows key**, type `PowerShell`, and click **Windows PowerShell**.
A blue or black window opens. To paste in it, **right-click** inside the window. Press Enter after each command.

## 2. Install uv and Git (one time)

uv installs Python and all libraries for you. Git downloads the project.

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```powershell
winget install --id Git.Git -e --source winget
```

If winget asks to accept terms, type `Y` and Enter.
**Close PowerShell and open it again** so the new programs are found. Then check:

```powershell
uv --version
git --version
```

Both should print a version number.

## 3. Download the project

```powershell
cd $HOME
git clone https://github.com/065008gif/agentic-trading-crew.git
cd agentic-trading-crew
```

## 4. Install everything (2-5 minutes)

```powershell
uv sync
```

## 5. Put your keys in a private `.env` file

```powershell
copy .env.example .env
notepad .env
```

Notepad opens. Fill in, right after each `=`, with no spaces or quotes:

- `ALPACA_API_KEY=` your Alpaca paper key
- `ALPACA_SECRET_KEY=` your Alpaca paper secret
- `ACCOUNT_LABEL=` **B** or **C**
- `GROQ_API_KEY=` your Groq key
- `APP_PASSWORD=` any password you'll remember

Save with **Ctrl + S** and close Notepad.

## 6. Check the setup (places no orders)

```powershell
uv run python check_setup.py
```

You want `[ OK ]` on the Alpaca, market data and LLM lines. If you see `[FAIL]`, send Akshit a screenshot.

## 7. Trade

Replace **B** with **C** if you are account C.

First an analysis-only run (no trades):

```powershell
uv run python trading_crew.py --account B --mode analyze
```

Then the real run. At the end it asks `Place these orders...? [y/N]`. Type `y` and Enter:

```powershell
uv run python trading_crew.py --account B
```

### Or use the web page instead

```powershell
uv run python app.py
```

Open http://localhost:8000 in Chrome or Edge. Type your app password under **Alpaca keys and app password**, reload, choose your account (B or C) at the top, press **Run the agents**, check the plan, then press **Place orders**.

## Daily routine (US market: 7:00 PM to 1:30 AM India time)

Run your account 2-3 times each trading day (Monday to Friday, until 27 October):

| India time | Do this |
|---|---|
| ~7:30 PM | run and approve |
| ~10:30 PM | run again |
| ~1:00 AM (if awake) | run again |

Or leave the laptop on and plugged in, and let it trade every hour by itself:

```powershell
uv run python trading_crew.py --account B --mode auto --loop 60
```

Stop it with **Ctrl + C**.

## Every evening: send your records to Akshit

```powershell
uv run python export_reports.py
```

It creates a file like `reports_B_20102026-2330.zip` in the project folder. Send that file to Akshit (WhatsApp or email). The interim report is due 20 October and the final report 28 October.

## Getting updates

When Akshit says the code was updated:

```powershell
cd $HOME\agentic-trading-crew
git pull
uv sync
```

## If something goes wrong

| You see | Do this |
|---|---|
| `uv` or `git` is not recognized | Close PowerShell, open it again, and retry |
| `Alpaca refused the keys (401)` | You copied Live keys or added a space. Generate new **Paper** keys and paste again |
| `rate limit` from Groq | Wait 1 minute and run again. The program also switches to a backup model by itself |
| Run says `rule-based` | The AI was unavailable that run. The plan still works. Run again later |
| Anything else | Screenshot the last 20 lines and send it to Akshit |
