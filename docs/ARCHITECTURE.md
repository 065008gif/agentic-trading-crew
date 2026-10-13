# Architecture and design decisions

Written for the interim and final reports. Each section states what was built and why.

## 1. Goal and constraints

The objective was the highest combined percentage gain on $300,000 of paper capital (three Alpaca accounts of $100,000) over 11 trading days, 13-27 October 2026. Constraints from the brief and the team:

- CrewAI as the agent framework; MCP client plus a local MCP server; Alpaca's own MCP server was not allowed.
- OHLCV for all stocks fetched in one call, not one call per stock.
- 10-15 stocks per student, with 30% of the group's stocks drawn from the S&P 500 High Beta Index.
- Only free resources: Alpaca paper accounts and the free IEX data feed, Groq's free tier (about 1,000 requests and 200,000 tokens per day, and 8,000 tokens per minute on `openai/gpt-oss-120b`), OpenRouter free models, and Ollama Cloud's free tier.

## 2. Key decision: indicators in tools, judgement in the LLM

The professor's reference crew made one LLM task per stock per indicator. With 13 stocks that is about 30 LLM tasks per run, which exceeds Groq's 8,000 tokens-per-minute limit within the first minute and uses a large share of the daily quota.

The system therefore moved every calculation into MCP server 1. One tool call computes all indicators and the composite score for the full watch-list and returns a compact text table (about 80 tokens per stock). The LLM agents only read summaries, so a full run needs roughly 8-12 LLM calls. This allows 8-10 runs per account per day on the free tier, and it removes the risk of the LLM misreading or inventing indicator values.

## 3. The Alpha Score (the team's own indicator)

Following the feature tree in the brief (trend, momentum, volume, volatility, statistics), 20+ indicators were grouped into six families, each scored 0-100:

| Family | Indicators |
|---|---|
| Trend | EMA 20/50/200 stack, EMA-20 slope, ADX with +DI/-DI |
| Momentum | RSI(14) sweet spot 55-72, MACD histogram level and direction, ROC(10), TSI |
| Relative strength | 5- and 20-day return minus SPY |
| Volume | CMF, OBV slope, MFI, relative volume on up days, PVO |
| Volatility / breakout | Donchian 20-day breakout or breakdown, distance to 20-day high, Bollinger squeeze |
| Statistics / mean reversion | RSI(2) pullback inside an uptrend, 20-day z-score |

A strategy profile weights the families (for example momentum: trend 25%, momentum 30%, relative strength 20%, volume 10%, breakout 15%). An overextension penalty (-8) applies when RSI(14) > 82 or the z-score > 2.8, because chasing vertical moves rarely pays inside a two-week window. Each account used a different profile so that the three accounts formed a controlled A/B/C comparison of strategies.

Indicator formulas follow pandas_ta's definitions but were written in plain pandas, so they run identically on Linux and Windows without compiled dependencies.

## 4. Market regime

Total exposure was set from a regime score built from SPY and QQQ trend (price versus EMA 20/50/200, MACD) and risk appetite (the 20-day change of the SPHB/SPLV ratio, high beta versus low volatility). Score bands mapped to invested fractions of 97% (risk-on), 90%, 75% and 55% (risk-off). Because idle cash counts against a percentage-return target, the system stays mostly invested unless the regime is clearly negative.

## 5. Agents

| # | Agent | Tools (MCP) | Output |
|---|---|---|---|
| 1 | Market Regime Strategist | fetch_ohlcv_batch, get_market_regime | regime, invest fraction |
| 2 | Quantitative Signal Analyst | compute_alpha_scores | ranked table and drivers |
| 3 | News and Catalyst Analyst | get_news_digest | sentiment and earnings risk per stock |
| 4 | Portfolio Manager | get_positions | Pydantic: exposure, score adjustments, vetoes, summary |
| 5 | Risk Manager | none (Python) | target weights and orders |

The process is sequential; agents 2 and 3 can run in parallel (`PARALLEL_ANALYSTS=1`) when the LLM's rate limit allows.

## 6. Bounded LLM authority

The Portfolio Manager can move any stock's score by at most 15 points, veto a new buy, and shift exposure by at most 10 percentage points. These limits are enforced in code, not only in the prompt. Position sizing, stops and cash checks are deterministic:

- weights proportional to (score - 45)^1.5 among stocks scoring 52 or more, capped at 15% per stock, at least 8 holdings;
- exit when the close falls below a chandelier stop (highest close of 10 days minus 2.5 ATR), the score drops below 40, or a 20-day breakdown coincides with a weak score;
- profiles that do not hold through earnings cap a stock at 5% the session before its report; overextended winners are trimmed to 7%;
- trades smaller than 1.5% of equity are skipped to avoid churn; sells execute before buys; buys never exceed cash.

## 7. Resilience

- LLM fallback chain: Groq `gpt-oss-120b`, then Groq `gpt-oss-20b` (separate quota), then OpenRouter and Ollama Cloud free models. If all fail, the plan is built from the Alpha Score alone and the report records it.
- Alpaca calls retry on rate limits and short network errors.
- A mock market mode (`MOCK_MARKET=1`) and 11 unit tests allow testing without keys or network.

## 8. Web interface

FastAPI serves a single page to choose the account's stocks, profile and indicator families; enter Alpaca keys (kept in the browser tab only); run the crew with live agent progress; review the target portfolio; and approve orders. It is protected by an app password and can be opened on a phone through an ngrok tunnel.
