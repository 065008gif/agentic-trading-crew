# Setup on a Windows laptop (Teammate 1 = account B, Teammate 2 = account C)

One-time setup takes about 20 minutes. Nothing here costs money.
The detailed version is the PDF guide Akshit sends you; this page is the short version.

**Have these ready in Notepad before you start:**
- your Alpaca **paper** API key and secret (app.alpaca.markets > make sure **Paper** is selected top-left > Home > **API Keys** > Generate)
- your own free Groq API key (console.groq.com > **API Keys** > **Create API Key**)
- your account letter: **B** (Teammate 1) or **C** (Teammate 2)

## 1. Install VS Code, Git and uv (one time)

Press the **Windows key**, type `PowerShell`, open **Windows PowerShell**. Paste with **right-click**, press Enter after each line:

```powershell
winget install --id Microsoft.VisualStudioCode -e --source winget
winget install --id Git.Git -e --source winget
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Type `Y` if winget asks to accept terms. **Close PowerShell and open it again**, then check (each prints a version):

```powershell
code --version
git --version
uv --version
```

## 2. Download the project and open it in VS Code

```powershell
cd $HOME
git clone https://github.com/065008gif/agentic-trading-crew.git
cd agentic-trading-crew
code .
```

In VS Code: click **Yes, I trust the authors**, and **Install** the recommended Python extensions when asked.
Open the terminal inside VS Code: menu **Terminal > New Terminal**. All further commands go there.

## 3. Install the libraries (3-5 minutes)

```powershell
uv sync
```

Then `Ctrl + Shift + P` > type `Python: Select Interpreter` > choose the one with **.venv** in its path.

## 4. Your keys in a private `.env` file

```powershell
copy .env.example .env
code .env
```

Fill in right after each `=` (no spaces, no quotes), then save with `Ctrl + S`:
`ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ACCOUNT_LABEL` (**B** or **C**), `GROQ_API_KEY`, `APP_PASSWORD` (any password).
Never send this file or these keys to anyone, including an AI chat.

## 5. Check, analyse, trade

Replace **B** with **C** if you are Teammate 2.

```powershell
uv run python check_setup.py
uv run python trading_crew.py --account B --mode analyze
uv run python trading_crew.py --account B
```

The last one asks `Place these orders on your PAPER account? [y/N]`: type `y` and Enter.
Or use **Run and Debug** (`Ctrl + Shift + D`): pick **3. TRADE** in the drop-down, press the green play button, choose your letter.

## Daily routine (Monday to Friday, until 27 October)

Once: Settings > System > Power > set **Sleep** to **Never** when plugged in. Keep the laptop plugged in.

Every trading evening at about **7:00 PM IST**, open the project in VS Code, then in the VS Code terminal:

```powershell
git pull
uv run python run_session.py --account B
```

It waits for the open, runs every 15 minutes (auto mode, no questions; the AI agents refresh every 30 minutes) until the 1:30 AM close,
stops by itself, and creates `reports_B_....zip` in the project folder. Send that zip to Akshit
(the next morning is fine). Ctrl + C stops it early and still creates the zip.

On the **last day, 27 Oct**, the session sells everything at 1:00 AM IST to book the profit, so it must
run that evening.

## If something goes wrong

| You see | Do this |
|---|---|
| `code`, `git` or `uv` is not recognized | Close PowerShell / VS Code, open again, retry |
| Red text about "running scripts is disabled" when a terminal opens | Harmless; always start commands with `uv run` |
| `Alpaca refused the keys (401)` | You copied Live keys or added a space. Generate new **Paper** keys |
| `rate limit` from Groq | Wait 1 minute and run again; the program also switches to a backup model |
| Run says `rule-based` | The AI was unavailable that run; the plan still works |
| Anything else | Screenshot the last 20 lines and send it to Akshit |
