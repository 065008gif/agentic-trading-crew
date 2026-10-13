# Console logs

Full terminal output of important runs, saved with `tee`, for example:

    python trading_crew.py --account A --mode analyze 2>&1 | tee console_logs/run4.txt

The agents' own outputs (one Markdown file per agent per run, named
`AgentNameDDMMYYYY-HH:MM.md`) are in `run_reports/<account>/`.
