# Experiment log

The brief asks for a record of why each experiment failed or succeeded. Add one row per change (model, indicator families, profile, risk setting), with the date and the result measured from `equity_log.csv` and the agent reports.

| Date | Account | Change made | Reason | Result (equity / notes) | Kept? |
|---|---|---|---|---|---|
| 12 Oct 2026 | all | Moved indicator maths from per-stock LLM tasks into one MCP tool call | Groq free tier allows 8,000 tokens per minute; per-stock tasks exceeded it | One run uses about 8-12 LLM calls instead of 30+ | Yes |
| 12 Oct 2026 | all | Floor on position-sizing formula for held stocks scoring 40-45 | Negative base produced an invalid weight in testing | Covered by unit test | Yes |
| | | | | | |
