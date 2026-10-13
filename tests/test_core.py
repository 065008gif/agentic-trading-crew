"""Offline tests: python -m pytest -q   (no keys, no network)."""

import os
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["MOCK_MARKET"] = "1"

from trading.indicators import rsi, snapshot  # noqa: E402
from trading.planner import RiskSettings, build_plan  # noqa: E402
from trading.scoring import alpha_score, regime_score  # noqa: E402

REGIME = {"regime": "RISK-ON", "regime_score": 70, "invest_fraction": 0.97}
ACCT = {"equity": 100000.0, "cash": 100000.0}


def row(sym, score, close=100.0, stop=90.0, **kw):
    r = {"symbol": sym, "alpha_score": score, "close": close, "stop": stop, "rsi14": 60, "zscore": 0.5,
         "breakout": False, "breakdown": False, "earnings": None}
    r.update(kw)
    return r


def held(value, qty=None):
    return {"qty": qty or value / 100, "market_value": value, "avg_entry": 100, "pl_pct": 0}


def test_rsi_bounds_and_trend():
    up = pd.Series(np.linspace(10, 50, 60))
    assert rsi(up).iloc[-1] > 95
    down = pd.Series(np.linspace(50, 10, 60))
    assert rsi(down).iloc[-1] < 5


def test_snapshot_and_score_on_trend():
    idx = pd.bdate_range("2025-01-01", periods=300)
    c = pd.Series(np.linspace(50, 150, 300) * (1 + 0.01 * np.sin(np.arange(300))), index=idx)
    df = pd.DataFrame({"open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1e6}, index=idx)
    s = snapshot(df, df)
    sc = alpha_score(s, "momentum")
    assert 0 <= sc["alpha_score"] <= 100
    assert sc["families"]["trend"] >= 60


def test_held_stock_in_40_45_band_does_not_crash():
    rows = [row("AAA", 42), row("BBB", 70)]
    plan = build_plan(rows, REGIME, {"AAA": held(10000)}, {"equity": 100000, "cash": 90000})
    t = {x["symbol"]: x for x in plan["targets"]}
    assert isinstance(t["AAA"]["target_weight"], float)


def test_stop_hit_exits():
    rows = [row("AAA", 80, close=85, stop=90)]
    plan = build_plan(rows, REGIME, {"AAA": held(10000)}, ACCT)
    assert plan["orders"][0]["side"] == "sell" and plan["orders"][0]["type"] == "close"


def test_low_score_exits_and_cap_respected():
    rows = [row("AAA", 30), row("BBB", 90), row("CCC", 60)]
    plan = build_plan(rows, REGIME, {"AAA": held(20000)}, {"equity": 100000, "cash": 80000})
    t = {x["symbol"]: x for x in plan["targets"]}
    assert t["AAA"]["action"] == "EXIT"
    assert t["BBB"]["target_weight"] <= RiskSettings().max_position_pct + 1e-9


def test_never_spends_more_than_cash():
    rows = [row(s, 80) for s in "ABCDEFGHIJ"]
    plan = build_plan(rows, REGIME, {}, {"equity": 100000, "cash": 20000})
    assert sum(o["dollars"] for o in plan["orders"] if o["side"] == "buy") <= 20000 + 1


def test_pm_exposure_change_is_limited():
    rows = [row(s, 80) for s in "ABCDEFGHIJ"]
    reg = {"regime": "RISK-OFF", "regime_score": 20, "invest_fraction": 0.55}
    plan = build_plan(rows, reg, {}, ACCT, overlay={"exposure": 0.98, "adjustments": []})
    assert abs(plan["exposure_target"] - 0.65) < 1e-9


def test_pm_adjustment_is_bounded():
    rows = [row("AAA", 60)]
    plan = build_plan(rows, REGIME, {}, ACCT, overlay={"adjustments": [{"symbol": "AAA", "adjust": 90, "note": ""}]})
    assert plan["targets"][0]["final"] == 75


def test_earnings_cap_for_non_catalyst_profile():
    today = date(2026, 10, 20)
    rows = [row("TSLA", 85, earnings="earnings 2026-10-20 AMC (0d)")] + [row(s, 60) for s in "ABCDEFG"]
    plan = build_plan(rows, REGIME, {}, ACCT, today=today)
    t = {x["symbol"]: x for x in plan["targets"]}
    assert t["TSLA"]["target_weight"] <= 0.05 + 1e-9
    plan_b = build_plan(rows, REGIME, {}, ACCT, profile="catalyst", hold_through_earnings=True, today=today)
    tb = {x["symbol"]: x for x in plan_b["targets"]}
    assert tb["TSLA"]["target_weight"] > 0.05


def test_fillers_get_fixed_small_weight_and_never_outnumber_strong_names():
    rows = [row("AAA", 80), row("BBB", 75)] + [row(s, 46) for s in "CDEFGH"]
    plan = build_plan(rows, REGIME, {}, ACCT)
    t = {x["symbol"]: x for x in plan["targets"]}
    fillers = [x for x in plan["targets"] if "added to reach minimum holdings" in x["reasons"]]
    assert len(fillers) == 2                      # no more fillers than qualified names
    assert all(abs(f["target_weight"] - 0.05) < 1e-9 for f in fillers)
    assert t["AAA"]["target_weight"] == t["BBB"]["target_weight"] == RiskSettings().max_position_pct
    assert sum(x["target_weight"] for x in plan["targets"]) <= 0.98 + 1e-9


def test_first_live_run_13_oct_sizing():
    # real Alpha Scores from the first analysis run on 13 Oct 2026 (risk-on, 97% exposure)
    scores = {"PLTR": 88.2, "META": 81.6, "GOOGL": 67.6, "GEV": 64.9, "AMD": 47.6, "ANET": 42.2,
              "NVDA": 41.0, "TSM": 39.3, "AVGO": 33.6, "LRCX": 33.2, "MU": 24.4, "SNDK": 19.1, "VRT": 13.7}
    rows = [row(s, v) for s, v in scores.items()]
    reg = {"regime": "RISK-ON", "regime_score": 95, "invest_fraction": 0.97}
    legacy = RiskSettings(max_position_pct=0.20, weight_power=1.5)   # settings used that day
    plan = build_plan(rows, reg, {}, ACCT, settings=legacy)
    w = {x["symbol"]: x["target_weight"] for x in plan["targets"]}
    for strong in ("PLTR", "META", "GOOGL", "GEV"):
        assert abs(w[strong] - 0.20) < 1e-9, (strong, w[strong])
    for filler in ("AMD", "ANET", "NVDA"):
        assert abs(w[filler] - 0.05) < 1e-9, (filler, w[filler])
    assert w["TSM"] == w["VRT"] == 0
    assert 0.94 <= sum(w.values()) <= 0.98


def test_agent_tools_have_inputs_for_groq_strict_mode():
    """Groq rejects a tool whose strict schema has no properties (seen live on 13 Oct)."""
    import json
    import subprocess
    import sys as _sys
    root = Path(__file__).resolve().parent.parent
    code = (
        "import sys, json; sys.path.insert(0, '.')\n"
        "from crewai_tools import MCPServerAdapter\n"
        "from mcp import StdioServerParameters\n"
        "from trading import mcp_bridge as b\n"
        "from crewai.utilities.pydantic_schema_utils import sanitize_tool_params_for_openai_strict as s\n"
        "out = {}\n"
        "for srv, names in [(b.MARKET_SERVER, ['fetch_ohlcv_batch','get_market_regime','compute_alpha_scores','get_news_digest']),\n"
        "                   (b.TRADING_SERVER, ['get_positions'])]:\n"
        "    ad = MCPServerAdapter(StdioServerParameters(command=sys.executable, args=[srv], env=b.server_env()), *names)\n"
        "    for t in ad.tools:\n"
        "        out[t.name] = s(t.args_schema.model_json_schema())\n"
        "    ad.stop()\n"
        "print('JSON' + json.dumps(out))\n"
    )
    env = dict(os.environ, MOCK_MARKET="1", PYTHONWARNINGS="ignore")
    res = subprocess.run([_sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True, timeout=120)
    line = [x for x in res.stdout.splitlines() if x.startswith("JSON")]
    assert line, res.stderr[-2000:]
    schemas = json.loads(line[-1][4:])
    assert set(schemas) == {"fetch_ohlcv_batch", "get_market_regime", "compute_alpha_scores",
                            "get_news_digest", "get_positions"}
    for name, sch in schemas.items():
        assert sch.get("properties"), f"{name} has no input properties"
        assert "include_rows" not in sch["properties"], name


def test_regime_labels():
    strong = {"close": 110, "ema20": 105, "ema50": 100, "ema200": 90, "macd_hist": 1}
    weak = {"close": 80, "ema20": 85, "ema50": 90, "ema200": 95, "macd_hist": -1}
    assert regime_score(strong, strong, 3)["regime"] == "RISK-ON"
    assert regime_score(weak, weak, -3)["regime"] == "RISK-OFF"


def test_pm_moves_need_news_evidence():
    """Replays 13 Oct run 3: the PM vetoed SHOP over an Apple headline and
    DELL over a bullish CEO comment, and gave MSFT +12 for Oracle news."""
    rows = [row("SHOP", 86.5), row("DELL", 66.7), row("MSFT", 86.8), row("DDOG", 82.5), row("XOM", 79.7)]
    overlay = {"adjustments": [
        {"symbol": "SHOP", "adjust": -8, "veto_buy": True, "note": "Munster warns Apple"},
        {"symbol": "DELL", "adjust": -10, "veto_buy": True, "note": "CEO cites supply"},
        {"symbol": "MSFT", "adjust": 12, "note": "Oracle news"},
        {"symbol": "DDOG", "adjust": 10, "note": "Barclays target raise"},
        {"symbol": "XOM", "adjust": -12, "veto_buy": True, "note": "really bad news"}]}
    ev = {"SHOP": {"sentiment": -0.2}, "DELL": {"sentiment": 0.0}, "MSFT": {"sentiment": 0.03},
          "DDOG": {"sentiment": 0.33}, "XOM": {"sentiment": -0.4}}
    plan = build_plan(rows, REGIME, {}, ACCT, overlay, evidence=ev)
    t = {x["symbol"]: x for x in plan["targets"]}
    assert t["SHOP"]["action"] == "BUY" and t["SHOP"]["adjust"] == -8   # mild bad news: dip kept, veto dropped
    assert t["DELL"]["action"] == "BUY" and t["DELL"]["adjust"] == -5
    assert t["MSFT"]["adjust"] == 5                 # unsupported +12 capped
    assert t["DDOG"]["adjust"] == 10                # backed by a target raise, kept
    assert t["XOM"]["action"] == "AVOID" and t["XOM"]["adjust"] == -12   # backed by bad news, kept
    # without evidence (old behaviour) the veto still applies
    plan2 = build_plan(rows, REGIME, {}, ACCT, overlay)
    assert {x["symbol"]: x for x in plan2["targets"]}["SHOP"]["action"] == "AVOID"


def test_news_filter_drops_roundups_and_shrinks_single_headlines():
    import importlib
    srv = importlib.import_module("servers.market_data_mcp_server")
    roundup = {"symbols": ["AAPL", "MSFT", "META", "NVDA", "AVGO"], "headline": "Samsung falls as Broadcom CEO warns"}
    shared = {"symbols": ["AAPL", "SHOP"], "headline": "Munster warns Apple could lose the AI game"}
    own = {"symbols": ["DDOG"], "headline": "Barclays raises price target on Datadog"}
    assert not srv._relevant(roundup, "MSFT") and srv._relevant(shared, "SHOP")
    orig = srv.ar.get_news
    srv.ar.get_news = lambda syms, days=3: [roundup, shared, own]
    try:
        rows = {r["symbol"]: r for r in srv._news_rows(["MSFT", "SHOP", "DDOG"])[0]}
    finally:
        srv.ar.get_news = orig
    assert rows["MSFT"]["articles"] == 0
    assert -0.25 < rows["SHOP"]["sentiment"] < 0     # half weight, shrunk: too weak for a veto
    assert rows["DDOG"]["sentiment"] > 0.3


def test_dropped_small_position_money_is_reinvested():
    """Run 4 (13 Oct): DELL's share was under 3%, got dropped, and its money sat in cash (95.7% vs 98%)."""
    scores = {"MSFT": 96.9, "PLTR": 93.1, "DDOG": 92.8, "SHOP": 90.5, "ZBRA": 87.9, "META": 86.6, "MRNA": 81.8,
              "XOM": 79.4, "VST": 77.7, "HPE": 75.6, "AAPL": 75.6, "WMT": 75.3, "DELL": 62.3}
    rows = [row(s, v) for s, v in scores.items()]
    reg = {"regime": "RISK-ON", "regime_score": 95, "invest_fraction": 0.98}
    plan = build_plan(rows, reg, {}, ACCT)
    t = {x["symbol"]: x for x in plan["targets"]}
    assert t["DELL"]["action"] == "AVOID" and any("minimum position" in r or "not in the top" in r
                                                  for r in t["DELL"]["reasons"])
    assert sum(1 for x in plan["targets"] if x["target_weight"] > 0) <= RiskSettings().max_holdings
    assert abs(sum(x["target_weight"] for x in plan["targets"]) - 0.98) < 1e-6


def test_profit_lock_books_most_of_the_best_gain():
    """Bought at 100, ran to 120 (+20%), now back to 109: lock is 112 (keep 60%), so sell and book +9%."""
    pos = {"AAA": {"qty": 100, "market_value": 10900, "avg_entry": 100, "pl_pct": 9.0}}
    plan = build_plan([row("AAA", 85, close=109, stop=95)], REGIME, pos, ACCT, peaks={"AAA": 120})
    t = plan["targets"][0]
    assert t["action"] == "EXIT" and any("profit lock" in r for r in t["reasons"])
    # still above the lock: hold, and the plan says where the lock is
    plan2 = build_plan([row("AAA", 85, close=115, stop=95)], REGIME, pos, ACCT, peaks={"AAA": 120})
    t2 = plan2["targets"][0]
    assert t2["action"] != "EXIT" and any("profit lock active" in r for r in t2["reasons"])
    # small gains (peak under +6%) are left to the normal stop
    plan3 = build_plan([row("AAA", 85, close=101, stop=95)], REGIME, pos, ACCT, peaks={"AAA": 105})
    assert plan3["targets"][0]["action"] != "EXIT"


def test_no_rebuy_same_day_after_stop_or_lock():
    plan = build_plan([row("AAA", 90)] + [row(s, 80) for s in "BCDEFGHI"], REGIME, {}, ACCT, no_rebuy={"AAA"})
    t = {x["symbol"]: x for x in plan["targets"]}
    assert t["AAA"]["action"] == "AVOID" and t["AAA"]["target_weight"] == 0


def test_aggressive_sizing_concentrates_on_the_best():
    scores = {"MSFT": 96.9, "SHOP": 94.2, "PLTR": 93.7, "DDOG": 91.5, "META": 88.7, "MRNA": 88.1, "ZBRA": 86.5,
              "XOM": 81.4, "VST": 79.8, "HPE": 78.2, "WMT": 76.2, "AAPL": 73.9, "DELL": 63.3}
    plan = build_plan([row(s, v) for s, v in scores.items()], REGIME, {}, ACCT)
    w = {x["symbol"]: x["target_weight"] for x in plan["targets"]}
    held = [s for s, v in w.items() if v > 0]
    assert len(held) <= RiskSettings().max_holdings and w["MSFT"] > 2 * min(v for v in w.values() if v > 0)
    assert w["MSFT"] <= RiskSettings().max_position_pct + 1e-9
