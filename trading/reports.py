"""
Run records, as the brief requires: every agent's output is saved as
    run_reports/<ACCOUNT>/<AgentName><DDMMYYYY>-<HH:MM>.md
plus a machine-readable plan, a trade journal and an equity log for the
interim and final reports.

Windows does not allow ':' in file names, so on Windows the time is written
as HH.MM (e.g. QuantAnalyst13102026-19.45.md). Linux and macOS keep HH:MM.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "run_reports"
SEP = "." if os.name == "nt" else ":"


class RunRecorder:
    def __init__(self, account_label: str, model: str, symbols: list[str], profile: str):
        self.started = datetime.now()
        self.stamp = self.started.strftime("%d%m%Y-%H") + SEP + self.started.strftime("%M")
        self.dir = REPORTS / account_label
        self.dir.mkdir(parents=True, exist_ok=True)
        self.account, self.model, self.symbols, self.profile = account_label, model, symbols, profile
        self.files: dict[str, Path] = {}

    def path(self, agent: str) -> Path:
        name = "".join(ch for ch in agent.title() if ch.isalnum())
        p = self.dir / f"{name}{self.stamp}.md"
        if agent not in self.files and p.exists():           # same-minute rerun
            p = self.dir / f"{name}{self.stamp}{SEP}{self.started.strftime('%S')}.md"
        return self.files.setdefault(agent, p)

    def write(self, agent: str, title: str, body: str) -> Path:
        p = self.path(agent)
        new = not p.exists()
        with p.open("a", encoding="utf-8") as f:
            if new:
                f.write(f"# {agent}\n\n- Account: {self.account}\n- Run started: "
                        f"{self.started:%d %b %Y, %H:%M:%S}\n- Model: {self.model}\n- Profile: "
                        f"{self.profile}\n- Watch-list: {', '.join(self.symbols)}\n\n---\n\n")
            f.write(f"## {title}\n\n_Written {datetime.now():%d %b %Y, %H:%M:%S}_\n\n{str(body).strip()}\n\n---\n\n")
        return p

    def save_plan(self, plan: dict) -> Path:
        p = self.dir / f"plan{self.started:%d%m%Y-%H%M%S}.json"
        p.write_text(json.dumps(plan, indent=2, default=str), encoding="utf-8")
        (self.dir / "latest_plan.json").write_text(json.dumps(plan, indent=2, default=str), encoding="utf-8")
        return p


def append_csv(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if new:
            w.writeheader()
        w.writerow(row)


def log_equity(account_label: str, account: dict, plan: dict, model: str) -> None:
    append_csv(REPORTS / account_label / "equity_log.csv", {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "equity": account.get("equity"), "cash": account.get("cash"),
        "last_equity": account.get("last_equity"), "regime": plan.get("regime"),
        "exposure_target": plan.get("exposure_target"), "orders": len(plan.get("orders", [])),
        "model": model})


def log_trade(account_label: str, order: dict, result: dict | str) -> None:
    r = result if isinstance(result, dict) else {"raw": str(result)[:200]}
    append_csv(REPORTS / account_label / "trade_journal.csv", {
        "timestamp": datetime.now().isoformat(timespec="seconds"), "symbol": order["symbol"],
        "side": order["side"], "dollars": order.get("dollars"), "qty": order.get("qty"),
        "reason": order.get("reason", "")[:200], "status": r.get("status", r.get("error", "")),
        "order_id": r.get("order_id", "")})
