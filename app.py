"""
Web interface for the trading crew.

  python app.py                      then open http://localhost:8000
  ngrok http 8000                    (second terminal) to open it on your phone

Pick the account's stocks and indicator families, enter Alpaca keys (or leave
blank to use .env), run the agents, review the plan and approve the orders.
Set APP_PASSWORD in .env: anyone with the ngrok link would otherwise be able
to trade on your paper account.
"""

from __future__ import annotations

import io
import os
import secrets
import sys
import threading
import traceback
import uuid
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import trading_crew as tc  # noqa: E402  (loads .env)
from fastapi import FastAPI, Header, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, PlainTextResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from trading import mcp_bridge as bridge  # noqa: E402
from trading.reports import REPORTS  # noqa: E402
from trading.scoring import FAMILIES, PROFILES  # noqa: E402

app = FastAPI(title="Agentic Trading Crew")
RUNS: dict[str, dict] = {}
PASSWORD = os.environ.get("APP_PASSWORD", "")


def _auth(pw: str | None):
    if PASSWORD and not secrets.compare_digest(pw or "", PASSWORD):
        raise HTTPException(401, "Wrong or missing app password")


class Keys(BaseModel):
    ALPACA_API_KEY: str = ""
    ALPACA_SECRET_KEY: str = ""


class RunRequest(BaseModel):
    account: str = "A"
    symbols: list[str] = []
    profile: str = "momentum"
    families: list[str] = FAMILIES
    mode: str = "approve"          # analyze | approve | auto
    use_llm: bool = True
    keys: Keys = Keys()


class _Tee(io.TextIOBase):
    """Copy the crew's console output into the run's live log."""
    def __init__(self, run):
        self.run = run

    def write(self, s):
        sys.__stdout__.write(s)
        self.run["console"] = (self.run.get("console", "") + s)[-20000:]
        return len(s)


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/api/config")
def config(x_app_password: str | None = Header(None)):
    _auth(x_app_password)
    return {"portfolios": tc.CONFIG["portfolios"], "profiles": {k: v["label"] for k, v in PROFILES.items()},
            "families": FAMILIES, "password_required": bool(PASSWORD),
            "env_keys_present": bool(os.environ.get("ALPACA_API_KEY")),
            "llm_chain": [tc.llm_factory.describe(n) for n, _ in tc.llm_factory.chain()]}


@app.post("/api/account")
def account(keys: Keys, x_app_password: str | None = Header(None)):
    _auth(x_app_password)
    env = tc.alpaca_env(keys.model_dump())
    acct, pos, clock = bridge.call_many(bridge.TRADING_SERVER, [
        ("get_account_info", {}), ("positions_data", {}), ("get_market_clock", {})], env)
    if isinstance(acct, dict) and "error" in acct:
        raise HTTPException(400, acct["error"])
    return {"account": acct, "positions": (pos or {}).get("positions", {}), "clock": clock}


@app.post("/api/run")
def start_run(req: RunRequest, x_app_password: str | None = Header(None)):
    _auth(x_app_password)
    if any(r["status"] == "running" for r in RUNS.values()):
        raise HTTPException(409, "A run is already in progress")
    run_id = uuid.uuid4().hex[:8]
    run = {"id": run_id, "status": "running", "started": datetime.now().strftime("%H:%M:%S"),
           "steps": [], "errors": [], "console": "", "request": req.model_dump(exclude={"keys"})}
    RUNS[run_id] = run
    keys = req.keys.model_dump()

    def work():
        try:
            with redirect_stdout(_Tee(run)):
                plan = tc.run_once(req.account, req.symbols or None, req.profile, req.families,
                                   "auto" if req.mode == "auto" else "analyze", keys, req.use_llm, run)
            run["plan"] = plan
            run["status"] = "done"
        except Exception as e:
            run["errors"].append(f"{type(e).__name__}: {e}")
            run["trace"] = traceback.format_exc()[-3000:]
            run["status"] = "failed"
        run["finished"] = datetime.now().strftime("%H:%M:%S")

    threading.Thread(target=work, daemon=True).start()
    return {"run_id": run_id}


@app.get("/api/run/{run_id}")
def run_status(run_id: str, x_app_password: str | None = Header(None)):
    _auth(x_app_password)
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(404, "Unknown run")
    return {k: v for k, v in run.items() if k != "console"} | {"console_tail": run.get("console", "")[-4000:]}


@app.post("/api/run/{run_id}/execute")
def execute(run_id: str, keys: Keys, x_app_password: str | None = Header(None)):
    _auth(x_app_password)
    run = RUNS.get(run_id)
    if not run or "plan" not in run:
        raise HTTPException(404, "No plan for this run")
    if run["plan"].get("executions"):
        raise HTTPException(409, "This plan was already executed")
    res = tc.execute_plan(run["plan"], keys.model_dump())
    run["plan"]["executions"] = res
    return {"executions": res}


@app.get("/api/reports")
def reports(x_app_password: str | None = Header(None)):
    _auth(x_app_password)
    files = sorted((p for p in REPORTS.rglob("*.md")), key=lambda p: p.stat().st_mtime, reverse=True)[:60]
    return [{"path": str(p.relative_to(REPORTS)), "modified": datetime.fromtimestamp(p.stat().st_mtime)
             .strftime("%d %b %H:%M")} for p in files]


@app.get("/api/report")
def report(path: str, x_app_password: str | None = Header(None)):
    _auth(x_app_password)
    p = (REPORTS / path).resolve()
    if REPORTS.resolve() not in p.parents or p.suffix != ".md" or not p.exists():
        raise HTTPException(404, "Not found")
    return PlainTextResponse(p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("APP_PORT", "8000"))
    print(f"\n  Web interface: http://localhost:{port}"
          f"\n  Phone: run  ngrok http {port}  in a second terminal and open the https link it prints"
          + ("" if PASSWORD else "\n  WARNING: APP_PASSWORD is not set in .env - set one before using ngrok") + "\n")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
