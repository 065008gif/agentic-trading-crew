"""
MCP CLIENT - CrewAI multi-agent trading system.

  python trading_crew.py --account A                 analyse account A's watch-list, ask before trading
  python trading_crew.py --account A --mode auto     analyse and place orders without asking
  python trading_crew.py --account B --mode analyze  analyse only, never trade
  python trading_crew.py --symbols MU AMD NVDA --profile momentum
  python trading_crew.py --account A --mode auto --loop 60   repeat every 60 min while the market is open

Architecture (one kickoff = one "run"):

  MCP server 1  servers/market_data_mcp_server.py    data, 20+ indicators, Alpha Score, regime, news
  MCP server 2  servers/alpaca_trading_mcp_server.py account, positions, orders (paper)

  Agent 1  Market Regime Strategist   -> fetch_ohlcv_batch (ONE call for all stocks), get_market_regime
  Agent 2  Quantitative Signal Analyst-> compute_alpha_scores (all stocks in one call)
  Agent 3  News & Catalyst Analyst    -> get_news_digest (one call) + earnings calendar
  Agent 4  Portfolio Manager          -> get_positions; returns bounded score adjustments (Pydantic)
  Agent 5  Risk Manager & Executor    -> plain Python rules (sizing, stops, cash) then orders via MCP

Every agent's output is saved as run_reports/<account>/<AgentName><DDMMYYYY>-<HH:MM>.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
# Windows consoles and redirected output (| tee, > file) may not be UTF-8;
# never crash on a symbol an LLM wrote, print a '?' instead.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONWARNINGS", "ignore")
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from pydantic import BaseModel, Field  # noqa: E402

from trading import llm as llm_factory  # noqa: E402
from trading import mcp_bridge as bridge  # noqa: E402
from trading.planner import RiskSettings, build_plan, plan_markdown  # noqa: E402
from trading.reports import RunRecorder, log_equity, log_trade  # noqa: E402
from trading.scoring import FAMILIES, PROFILES  # noqa: E402

CONFIG = json.loads((ROOT / "config" / "portfolios.json").read_text(encoding="utf-8"))


# ============================================================ structured output of agent 4
class Adjustment(BaseModel):
    symbol: str
    adjust: int = Field(description="Score change from -15 (much worse) to +15 (much better); 0 if no view")
    veto_buy: bool = Field(default=False, description="True only if news/earnings make a NEW buy too risky")
    note: str = Field(description="One short reason")


class PMOverlay(BaseModel):
    exposure: float = Field(description="Share of the account to keep invested, 0.50 to 0.98")
    adjustments: list[Adjustment]
    summary: str = Field(description="2-4 sentences: market view and the plan")


# ============================================================ configuration
def resolve_watchlist(account: str | None, symbols: list[str] | None, profile: str | None):
    if symbols:
        return [s.upper() for s in symbols], (profile or "momentum"), (account or "CUSTOM")
    acct = (account or os.environ.get("ACCOUNT_LABEL") or "A").upper()
    p = CONFIG["portfolios"].get(acct)
    if not p:
        raise SystemExit(f"Unknown account '{acct}'. Use A, B, C or pass --symbols.")
    return p["high_beta"] + p["others"], (profile or p["profile"]), acct


def alpaca_env(keys: dict | None = None) -> dict:
    """Keys passed from the web UI override .env for this run only."""
    keys = keys or {}
    return {"ALPACA_API_KEY": keys.get("ALPACA_API_KEY") or os.environ.get("ALPACA_API_KEY", ""),
            "ALPACA_SECRET_KEY": keys.get("ALPACA_SECRET_KEY") or os.environ.get("ALPACA_SECRET_KEY", "")}


# ============================================================ the crew
def build_crew(llm, model_name, symbols, profile, families, holdings_text, rec, pause, log, alp_env):
    from crewai import Agent, Crew, Process, Task
    from crewai_tools import MCPServerAdapter
    from mcp import StdioServerParameters

    env = bridge.server_env(alp_env)
    market = MCPServerAdapter(StdioServerParameters(command=sys.executable, args=[bridge.MARKET_SERVER], env=env),
                              "fetch_ohlcv_batch", "get_market_regime", "compute_alpha_scores", "get_news_digest")
    trading = MCPServerAdapter(StdioServerParameters(command=sys.executable, args=[bridge.TRADING_SERVER], env=env),
                               "get_positions")
    tools = {t.name: t for t in list(market.tools) + list(trading.tools)}

    def cb(agent_name, title):
        def _w(output):
            try:
                pyd = getattr(output, "pydantic", None)
                body = pyd.model_dump_json(indent=2) if pyd is not None else str(output.raw)
                rec.write(agent_name, title, body)
                log["steps"].append({"agent": agent_name, "title": title, "output": body[:4000],
                                     "time": datetime.now().strftime("%H:%M:%S")})
            except Exception as e:
                print(f"WARNING: report write failed for {agent_name}: {e}")
            if pause:
                time.sleep(pause)   # stay under the free tokens-per-minute limit
        return _w

    sym_json = json.dumps(symbols)
    fam_json = json.dumps(families)
    common = {"llm": llm, "verbose": True, "max_iter": 4, "allow_delegation": False}

    regime_agent = Agent(
        role="Market Regime Strategist",
        goal="Load price data for the whole watch-list in one call and judge whether the market is risk-on or risk-off.",
        backstory="A macro trader who sizes total exposure to the market's trend and risk appetite. Reports tool numbers exactly.",
        tools=[tools["fetch_ohlcv_batch"], tools["get_market_regime"]], **common)
    quant_agent = Agent(
        role="Quantitative Signal Analyst",
        goal="Rank every stock with the Alpha Score and explain what drives the top and bottom names.",
        backstory="A quant who built the team's composite indicator from trend, momentum, relative strength, "
                  "volume, volatility and mean-reversion families. Never invents numbers.",
        tools=[tools["compute_alpha_scores"]], **common)
    news_agent = Agent(
        role="News and Catalyst Analyst",
        goal="Spot headlines and earnings dates that the price indicators cannot see yet.",
        backstory="A former sell-side analyst who reads headlines fast and flags event risk such as earnings reports.",
        tools=[tools["get_news_digest"]], **common)
    pm_agent = Agent(
        role="Portfolio Manager",
        goal="Turn the regime, Alpha Scores and news into bounded score adjustments that maximise 2-week returns.",
        backstory="An aggressive but disciplined growth PM competing to top a class trading league over 11 trading "
                  "days. Takes risk where the evidence is strong, cuts it where the evidence is broken.",
        tools=[tools["get_positions"]], **common)

    t1 = Task(name="Regime",
              description=(f"Step 1: call fetch_ohlcv_batch ONCE with symbols={sym_json} and lookback_days=400. "
                           'Step 2: call get_market_regime ONCE with benchmarks=["SPY", "QQQ"]. '
                           "Pass exactly these arguments. "
                           "Report: regime label, regime_score, invest_fraction, SPY RSI and trend, high-beta vs "
                           "low-vol reading, and any missing symbols. Max 120 words."),
              expected_output="Short regime report with the tool's numbers.",
              agent=regime_agent, callback=cb("Market Regime Strategist", "Regime"))
    t2 = Task(name="Alpha Scores",
              description=(f"Call compute_alpha_scores ONCE with symbols={sym_json}, profile='{profile}', "
                           f"families={fam_json}. Copy the returned table exactly, then in max 120 words explain "
                           "which families drive the top 3 and the bottom 3 names."),
              expected_output="The ranked Alpha Score table plus a short explanation.",
              agent=quant_agent, context=[t1], callback=cb("Quantitative Signal Analyst", "Alpha Scores"))
    t3 = Task(name="News",
              description=(f"Call get_news_digest ONCE with symbols={sym_json}, days=3 and per_symbol=2. "
                           "For each symbol give one line: "
                           "sentiment (bullish/neutral/bearish), the key headline in a few words, and EARNINGS RISK "
                           "if a report is due in the next 2 sessions. Max 200 words."),
              expected_output="One line per symbol.",
              agent=news_agent, async_execution=os.environ.get("PARALLEL_ANALYSTS", "0") == "1",
              callback=cb("News and Catalyst Analyst", "News"))
    t4 = Task(name="Portfolio decisions",
              description=(
                  f"Strategy profile: {PROFILES[profile]['label']}.\n{holdings_text}\n"
                  'You may call get_positions once with sort_by="value" to confirm holdings.\n'
                  "Using the regime, Alpha Score table and news above:\n"
                  "1. exposure: start from the regime invest_fraction; you may move it by at most 0.10 "
                  "(range 0.50-0.98). The team is judged on total % profit, so idle cash is a cost.\n"
                  "2. adjustments: for EVERY symbol give adjust between -15 and +15. The Alpha Score already "
                  "contains trend, breakouts and volume, so do not add points for those again. Use +6..+15 only "
                  "for clearly good news ABOUT THAT COMPANY (upgrade, target raise, contract, guidance raise) and "
                  "-6..-15 only for clearly bad news about it; otherwise stay within -5..+5. A headline about a "
                  "different company is not news for this one. Set veto_buy=true only when a headline about the "
                  "company itself is clearly bad. The Risk Manager checks every move bigger than 5 and every veto "
                  "against the news sentiment numbers and cancels the ones they do not support.\n"
                  "3. summary: 2-4 sentences.\n"
                  "Do NOT size positions or place orders; the Risk Manager does that from your output."),
              expected_output="exposure, one adjustment per symbol, and a summary.",
              agent=pm_agent, context=[t1, t2, t3], output_pydantic=PMOverlay,
              callback=cb("Portfolio Manager", "Score adjustments"))

    crew = Crew(agents=[regime_agent, quant_agent, news_agent, pm_agent], tasks=[t1, t2, t3, t4],
                process=Process.sequential, verbose=True, max_rpm=25)
    return crew, market, trading


def parse_overlay(text: str) -> dict:
    """Portfolio Manager JSON found anywhere in a text reply, validated; {} if none."""
    import re
    for match in re.finditer(r"\{.*\}", text or "", re.S):
        try:
            return PMOverlay.model_validate_json(match.group(0)).model_dump()
        except Exception:
            continue
    return {}


def run_crew_with_fallback(symbols, profile, families, holdings_text, rec, log, alp_env):
    """Try each configured free LLM in order; return (overlay dict, model name)."""
    providers = llm_factory.chain()
    if not providers:
        log["errors"].append("No LLM key configured: running on the rule-based Alpha Score only.")
        return {}, "rule-based (no LLM key)"
    for name, llm in providers:
        model_name = llm_factory.describe(name)
        rec.model = model_name
        print(f"\n>>> Running crew on {model_name}")
        market = trading = None
        try:
            crew, market, trading = build_crew(llm, model_name, symbols, profile, families, holdings_text,
                                               rec, llm_factory.pause_seconds(name), log, alp_env)
            result = crew.kickoff()
            overlay = result.pydantic.model_dump() if getattr(result, "pydantic", None) else {}
            if not overlay:                      # structured output missing: read JSON from the text
                overlay = parse_overlay(getattr(result, "raw", "") or "")
            if not overlay:
                raise RuntimeError("Portfolio Manager returned no structured output")
            return overlay, model_name
        except Exception as e:
            msg = f"{model_name} failed: {type(e).__name__}: {str(e)[:300]}"
            print("WARNING:", msg)
            log["errors"].append(msg)
        finally:
            for a in (market, trading):
                try:
                    a and a.stop()
                except Exception:
                    pass
    log["errors"].append("All LLM providers failed: plan is purely rule-based this run.")
    return {}, "rule-based (LLMs unavailable)"


# ============================================================ one full run
def run_once(account: str | None = None, symbols: list[str] | None = None, profile: str | None = None,
             families: list[str] | None = None, mode: str = "approve", keys: dict | None = None,
             use_llm: bool = True, log: dict | None = None, confirm=None) -> dict:
    """
    mode: analyze (never trade) | approve (ask before orders) | auto (trade immediately).
    `confirm(plan) -> bool` is used in approve mode; default asks on the terminal.
    """
    log = log if log is not None else {}
    log.setdefault("steps", []); log.setdefault("errors", [])
    env = alpaca_env(keys)
    syms, profile, label = resolve_watchlist(account, symbols, profile)
    families = [f for f in (families or FAMILIES) if f in FAMILIES] or FAMILIES
    prof = PROFILES.get(profile) or PROFILES["momentum"]

    # current holdings first, so held stocks are always analysed too
    acct_info, pos = bridge.call_many(bridge.TRADING_SERVER,
                                      [("get_account_info", {}), ("positions_data", {})], env)
    if isinstance(acct_info, dict) and "error" in acct_info:
        raise RuntimeError(f"Cannot reach Alpaca: {acct_info['error']}")
    positions = pos.get("positions", {}) if isinstance(pos, dict) else {}
    for s in positions:
        if s not in syms:
            syms.append(s)
    held = [f"  - {s}: {p['qty']:g} sh, value ${p['market_value']:,.0f}, P/L {p['pl_pct']:+.1f}%"
            for s, p in positions.items()]
    holdings_text = "Currently HELD:\n" + ("\n".join(held) if held else "  (nothing yet)")

    rec = RunRecorder(label, "pending", syms, profile)
    print(f"\n{'=' * 70}\n Account {label} | profile {profile} | {len(syms)} stocks | mode {mode}\n"
          f" Equity ${acct_info.get('equity', 0):,.0f} | cash ${acct_info.get('cash', 0):,.0f}\n{'=' * 70}")

    overlay, model_name = ({}, "rule-based (LLM off)")
    if use_llm:
        overlay, model_name = run_crew_with_fallback(syms, profile, families, holdings_text, rec, log, env)
    rec.model = model_name

    # deterministic numbers for the Risk Manager (same MCP server, one more data call)
    scores, regime, news = bridge.call_many(bridge.MARKET_SERVER, [
        ("alpha_scores_data", {"symbols": syms, "profile": profile, "families": families}),
        ("get_market_regime", {"benchmarks": ["SPY", "QQQ"]}),
        ("news_data", {"symbols": syms, "days": 3})], env)
    # no news data means no evidence: big PM moves are then capped at +/-5
    evidence = {r["symbol"]: r for r in news.get("rows", [])} if isinstance(news, dict) else {}
    if not isinstance(scores, dict) or "rows" not in scores:
        raise RuntimeError(f"Indicator server failed: {scores}")
    if not use_llm or not overlay:
        rec.write("Quantitative Signal Analyst", "Alpha Scores (rule-based run)", "```\n" + scores["table"] + "\n```")

    plan = build_plan(scores["rows"], regime, positions, acct_info, overlay, profile,
                      prof["hold_through_earnings"], RiskSettings(), evidence=evidence)
    plan.update({"account": label, "model": model_name, "mode": mode, "families": families,
                 "alpha_table": scores["table"], "missing": scores.get("missing", []),
                 "errors": log["errors"], "created": datetime.now().isoformat(timespec="seconds")})
    md = plan_markdown(plan)
    rec.write("Risk Manager", "Target portfolio and orders", md)
    plan["plan_file"] = str(rec.save_plan(plan))
    log_equity(label, acct_info, plan, model_name)
    log["plan"] = plan
    print("\n" + md)

    if mode == "auto" or (mode == "approve" and plan["orders"] and (confirm or _ask)(plan)):
        plan["executions"] = execute_plan(plan, keys, rec)
    else:
        plan["executions"] = []
        if plan["orders"]:
            print("\nNo orders placed (analysis only or not approved).")
    return plan


def _ask(plan) -> bool:
    try:
        return input(f"\nPlace these {len(plan['orders'])} orders on your PAPER account? [y/N]: ").strip().lower() == "y"
    except EOFError:
        return False


def execute_plan(plan: dict, keys: dict | None = None, rec: RunRecorder | None = None) -> list:
    """Send the plan's orders through the trading MCP server: sells first, then buys."""
    env = alpaca_env(keys)
    label = plan.get("account", "CUSTOM")
    sells = [o for o in plan["orders"] if o["side"] == "sell"]
    buys = [o for o in plan["orders"] if o["side"] == "buy"]
    calls = []
    for o in sells:
        calls.append(("close_position", {"symbol": o["symbol"]}) if o.get("type") == "close"
                     else ("sell_stock", {"symbol": o["symbol"], "qty": o["qty"]}))
    results = bridge.call_many(bridge.TRADING_SERVER, calls, env) if calls else []
    if sells and buys:
        time.sleep(3)   # let sells fill so cash is free for the buys
    if buys:
        results += bridge.call_many(bridge.TRADING_SERVER,
                                    [("buy_dollars", {"symbol": o["symbol"], "dollars": o["dollars"]}) for o in buys], env)
    out, lines = [], []
    for o, r in zip(sells + buys, results):
        log_trade(label, o, r)
        status = r.get("status", r.get("error", "?")) if isinstance(r, dict) else str(r)[:80]
        out.append({"order": o, "result": r})
        lines.append(f"- {o['side'].upper()} {o['symbol']} ${o['dollars']:,.0f}: {status}")
    clock = bridge.call(bridge.TRADING_SERVER, "get_market_clock", {}, env)
    if isinstance(clock, dict) and clock.get("is_open") is False:
        lines.append(f"\nMarket is closed: orders are queued and fill at the next open ({clock.get('next_open')}).")
    text = "\n".join(lines) or "no orders"
    print("\nEXECUTION\n" + text)
    if rec:
        rec.write("Executor", "Orders sent via trading MCP server", text)
    return out


# ============================================================ CLI
def main():
    ap = argparse.ArgumentParser(description="Agentic trading crew (CrewAI + local MCP servers + Alpaca paper)")
    ap.add_argument("--account", help="A, B or C (watch-lists in config/portfolios.json)")
    ap.add_argument("--symbols", nargs="*", help="custom watch-list instead of an account's list")
    ap.add_argument("--profile", choices=list(PROFILES), help="override the strategy profile")
    ap.add_argument("--families", nargs="*", choices=FAMILIES, help="indicator families to use (default all)")
    ap.add_argument("--mode", choices=["analyze", "approve", "auto"], default="approve")
    ap.add_argument("--no-llm", action="store_true", help="skip the agents; pure rule-based plan")
    ap.add_argument("--loop", type=int, default=0, help="repeat every N minutes while the market is open")
    a = ap.parse_args()

    def once():
        try:
            run_once(a.account, a.symbols, a.profile, a.families, a.mode, use_llm=not a.no_llm)
        except Exception as e:
            print(f"\nRUN FAILED: {e}")
            traceback.print_exc()

    if not a.loop:
        once()
        return
    print(f"Loop mode: every {a.loop} min while the US market is open. Ctrl+C to stop.")
    while True:
        clock = bridge.call(bridge.TRADING_SERVER, "get_market_clock", {}, alpaca_env())
        if isinstance(clock, dict) and clock.get("is_open"):
            once()
        else:
            print(f"{datetime.now():%H:%M} market closed; next open {clock.get('next_open') if isinstance(clock, dict) else '?'}")
        time.sleep(a.loop * 60)


if __name__ == "__main__":
    main()
