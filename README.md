# Agentic Trading Crew

A multi-agent system that trades US stocks on **Alpaca paper accounts**, built with **CrewAI** and two **local MCP servers**, for the "Trade Algorithmically using Trading Agents" project (FORE School of Management, October 2026).

Three team members each trade a $100,000 paper account (10-15 stocks each, 39 stocks in total, 12 of them from the S&P 500 High Beta Index). The same agent system runs on all three computers, with a different strategy profile per account.

- **Setup on Linux:** [SETUP_LINUX.md](SETUP_LINUX.md)
- **Setup on Windows (teammates):** [SETUP_WINDOWS.md](SETUP_WINDOWS.md)
- **Design notes for the report:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Experiment log:** [docs/EXPERIMENT_LOG.md](docs/EXPERIMENT_LOG.md)

## How one run works

```
                          trading_crew.py  (MCP client + CrewAI crew)
                                        |
   +------------------------------------+-------------------------------------+
   |                                                                          |
MCP server 1: market_data_mcp_server.py                     MCP server 2: alpaca_trading_mcp_server.py
  fetch_ohlcv_batch   (ONE Alpaca call, all stocks)            get_account_info, get_positions,
  compute_alpha_scores (20+ indicators -> Alpha Score)         get_market_clock, buy_dollars,
  get_market_regime   (SPY/QQQ trend, high-beta appetite)      sell_stock, close_position, cancel_orders
  get_news_digest     (Alpaca news + earnings calendar)
   |                                                                          |
   v                                                                          v
 1 Market Regime Strategist --> 2 Quantitative Signal Analyst --> 3 News & Catalyst Analyst
                                        |
                                        v
                         4 Portfolio Manager (LLM, Pydantic output:
                           exposure +/-10 pts, score adjustments +/-15)
                                        |
                                        v
                         5 Risk Manager (Python rules, no LLM):
                           sizing, stops, earnings caps, cash check
                                        |
                       human approval (terminal or web) or auto mode
                                        |
                                        v
                         orders through MCP server 2 -> Alpaca paper
```

Every agent's output is saved as `run_reports/<account>/<AgentName><DDMMYYYY>-<HH:MM>.md`, as the brief asks (Akshit's account in `run_reports/A`, the teammates' accounts in `teammate_reports/B` and `teammate_reports/C`). Each run also saves a JSON plan, a trade journal (`trade_journal.csv`) and an equity log (`equity_log.csv`).

## Commands

| Goal | Command |
|---|---|
| Check keys and connections | `uv run python check_setup.py` |
| Analyse only | `uv run python trading_crew.py --account A --mode analyze` |
| Analyse, then approve orders | `uv run python trading_crew.py --account A` |
| Trade without asking | `uv run python trading_crew.py --account A --mode auto` |
| **Whole evening: a run every 15 min until the close, then save** | `python run_session.py --account A --sync` |
| Rules only, no LLM | add `--no-llm` |
| Custom stocks / profile / indicator families | `--symbols MU AMD NVDA --profile rebound --families trend momentum` |
| Web interface | `uv run python app.py`, then http://localhost:8000 (`ngrok http 8000` for the phone) |
| Offline tests | `uv run python -m pytest -q` |
| Sell everything now (book all profits) | `python close_all.py --account A` |
| Zip run records for the report (teammates) | `uv run python export_reports.py` |
| Save records and code to GitHub (Akshit) | `python sync_github.py` |

In VS Code the same commands are one click away: **Run and Debug** (`Ctrl+Shift+D`) lists them as numbered entries (`.vscode/launch.json`). The college Linux PC uses a plain venv (`SETUP_LINUX.md`); the Windows laptops use uv (`SETUP_WINDOWS.md`).

## Requirement checklist (from the project brief)

| Brief requirement | Where it is met |
|---|---|
| Live paper trading on Alpaca, US equities | `trading/alpaca_rest.py` (paper endpoint only) |
| 10-15 stocks per student, 30% high beta | `config/portfolios.json` (13 each, 4 high-beta each, 12 of 39 = 31%) |
| Financial indicators, own indicator | `trading/indicators.py` (20+), `trading/scoring.py` (Alpha Score) |
| CrewAI agents | `trading_crew.py` (4 LLM agents + rule-based Risk Manager) |
| Local MCP server, not Alpaca's MCP | `servers/` (two FastMCP servers over stdio) |
| OHLCV for many stocks in one call | `fetch_ohlcv_batch` / `alpaca_rest.get_bars` |
| Agent outputs saved as agentNameDDMMYYYY-HH:MM.md | `trading/reports.py` |
| Free LLMs (Ollama cloud / Groq / OpenRouter) | `trading/llm.py` with automatic fallback |
| Optional human approval before orders | default `approve` mode, web **Place orders** button |
| News analysis | `get_news_digest` (Alpaca news) + News & Catalyst Analyst |
| Web interface with stock list, indicator choice, API keys, results, ngrok | `app.py`, `web/index.html` |

## Strategy profiles

| Account | Profile | Idea |
|---|---|---|
| A | momentum | Ride the strongest trends (AI and semiconductors lead 2026) |
| B | catalyst | Buy the setup into earnings and hold through the report |
| C | rebound | Buy sharp pullbacks inside uptrends, across sectors |

## Safety

- Paper trading endpoint only; no margin (exposure is capped at 98% of equity).
- The LLM can only nudge scores (+/-15) and exposure (+/-10 points); position sizes, stops and cash checks are plain Python.
- If every LLM is unavailable, the run still produces a rule-based plan.
- Profit booking: a chandelier trailing stop on every holding, a profit lock (after a 6%+ gain, keep at least 60% of the best gain; no same-day re-buy), concentration in the 8 strongest names (up to 25% each, weights tilted by score^2.5), a trim of over-extended winners (RSI > 82 and z > 2.5), and on the last trading day (27 Oct) `run_session.py` sells every position 30 minutes before the close.
- Keys live in `.env` (never committed) or only in the browser tab when typed into the web page.
- Set `APP_PASSWORD` before exposing the web page with ngrok.

Not financial advice; educational project on simulated money.
