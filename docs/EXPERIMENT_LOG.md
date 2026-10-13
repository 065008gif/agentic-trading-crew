# Experiment log

The brief asks for a record of why each experiment failed or succeeded. Add one row per change (model, indicator families, profile, risk setting), with the date and the result measured from `equity_log.csv` and the agent reports.

| Date | Account | Change made | Reason | Result (equity / notes) | Kept? |
|---|---|---|---|---|---|
| 12 Oct 2026 | all | Moved indicator maths from per-stock LLM tasks into one MCP tool call | Groq free tier allows 8,000 tokens per minute; per-stock tasks exceeded it | One run uses about 8-12 LLM calls instead of 30+ | Yes |
| 12 Oct 2026 | all | Floor on position-sizing formula for held stocks scoring 40-45 | Negative base produced an invalid weight in testing | Covered by unit test | Yes |
| 13 Oct 2026 | A | First live analysis runs: PM agent vetoed SHOP over an Apple headline, DELL over a bullish CEO quote, +12 to MSFT for Oracle news | LLM misreads news | Added a news-evidence check: moves beyond +/-5 and vetoes need matching news sentiment; news fetch paginated, round-ups filtered | Yes |
| 13 Oct 2026 | A | Dropped tiny positions left their money as cash (95.7% vs 98% invested) | Sizing leak | Money of too-small positions is re-split among the rest | Yes |
| 13 Oct 2026 | A | First trade: 12 stocks, about 98% invested, weights 4-12% (score^1.5, 20% cap) | Start of trading | Baseline for comparison | Replaced 14 Oct |
| 14 Oct 2026 | all | Aggressive sizing: top 8 names only, cap 25%, weights by score^2.5 | Brief: "MUST take risks"; spreading over 12 names behaved like an index | Measure from equity_log.csv vs SPY from 14 Oct | Testing |
| 14 Oct 2026 | all | Profit lock (after +6%, keep 60% of the best gain), no same-day re-buy, sell everything 30 min before the close on 27 Oct | Book profits instead of giving gains back | Covered by unit tests; watch session_log.txt | Testing |
| 14 Oct 2026 | all | run_session.py: a full AI run every 15 min (26 a day); free daily limits handled by a model chain (Groq gpt-oss-120b, gpt-oss-20b, qwen3.8-27b, then OpenRouter/Ollama Cloud if keys are set, then rules-only); a model whose daily quota is used up is skipped until the next day | Faster stops, profit locks and news reactions | Watch which model each run used in session_log.txt | Testing |
| | | | | | |
