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
    plan = build_plan(rows, reg, {}, ACCT)
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
