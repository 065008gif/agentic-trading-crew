"""
Alpha Score: the team's own composite indicator.

Each stock gets six sub-scores (0-100), one per indicator family from the
professor's feature tree, plus relative strength and mean reversion:

    trend       EMA20/50/200 stack, EMA slope, ADX with +DI/-DI
    momentum    RSI(14) sweet spot, MACD histogram, ROC(10), TSI
    rs          return vs SPY over 5 and 20 days
    volume      CMF, OBV slope, MFI, relative volume on up days, PVO
    volatility  Donchian breakout, distance to 20-day high, Bollinger squeeze
    stats       mean reversion: RSI(2) pullback in an uptrend, 20-day z-score

A strategy profile weights the six families differently. The weighted sum
is the Alpha Score. The user can switch whole families off from the web UI;
weights are then renormalised over the families left on.
"""

from __future__ import annotations

FAMILIES = ["trend", "momentum", "rs", "volume", "volatility", "stats"]

PROFILES: dict[str, dict] = {
    "momentum": {
        "label": "A - AI/semis momentum: ride the strongest trends",
        "weights": {"trend": .25, "momentum": .30, "rs": .20, "volume": .10, "volatility": .15, "stats": 0},
        "hold_through_earnings": False,
    },
    "catalyst": {
        "label": "B - Earnings catalysts: buy the setup, hold through the report",
        "weights": {"trend": .15, "momentum": .25, "rs": .15, "volume": .20, "volatility": .15, "stats": .10},
        "hold_through_earnings": True,
    },
    "rebound": {
        "label": "C - Rebound: buy sharp pullbacks inside uptrends, across sectors",
        "weights": {"trend": .15, "momentum": .10, "rs": .10, "volume": .15, "volatility": .05, "stats": .45},
        "hold_through_earnings": False,
    },
    "balanced": {
        "label": "Balanced: equal weight on every family",
        "weights": {f: 1 / 6 for f in FAMILIES},
        "hold_through_earnings": False,
    },
}


def _clamp(x: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, x))


def _lin(x, x0, x1) -> float:
    """Map x linearly so x0 -> 0 and x1 -> 100, clamped."""
    if x is None:
        return 50.0
    return _clamp(100 * (x - x0) / (x1 - x0))


def _avg(vals) -> float:
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else 50.0


def family_scores(s: dict) -> dict:
    """Six 0-100 sub-scores from one indicator snapshot."""
    c = s.get("close") or 0
    e20, e50, e200 = s.get("ema20"), s.get("ema50"), s.get("ema200")

    # trend
    t = 0
    if e20 and c > e20: t += 20
    if e20 and e50 and e20 > e50: t += 20
    if e200 and c > e200: t += 15
    elif e200 is None and e50 and c > e50: t += 10
    t += 15 * _lin(s.get("ema20_slope5"), -1, 2) / 100
    if s.get("adx") and s.get("plus_di") and s.get("minus_di"):
        if s["plus_di"] > s["minus_di"]:
            t += 20 if s["adx"] >= 20 else 10
            if s["adx"] >= 30: t += 10
    trend = _clamp(t)

    # momentum
    r = s.get("rsi14")
    if r is None: rsi_pts = 50
    elif 55 <= r <= 72: rsi_pts = 100
    elif 50 <= r < 55 or 72 < r <= 80: rsi_pts = 70
    elif r > 80: rsi_pts = 35
    elif 40 <= r < 50: rsi_pts = 40
    else: rsi_pts = 15
    h, hp = s.get("macd_hist"), s.get("macd_hist_prev")
    macd_pts = 50 if h is None else (40 + (35 if h > 0 else 0) + (25 if hp is not None and h > hp else 0))
    momentum = _avg([rsi_pts, macd_pts, _lin(s.get("roc10"), -8, 12), _lin(s.get("tsi"), -25, 35)])

    # relative strength vs SPY
    rs = _avg([_lin(s.get("rs_vs_spy_20d"), -8, 12), _lin(s.get("rs_vs_spy_5d"), -4, 6)])

    # volume
    m = s.get("mfi")
    mfi_pts = 50 if m is None else (85 if 50 <= m <= 80 else 45 if m > 80 else _lin(m, 20, 50))
    up_day_vol = 50
    if s.get("rel_volume") is not None and s.get("ret_1d") is not None:
        rv, r1 = s["rel_volume"], s["ret_1d"]
        up_day_vol = _clamp(50 + (rv - 1) * 60) if r1 > 0 else _clamp(50 - (rv - 1) * 60)
    volume = _avg([_lin(s.get("cmf"), -0.15, 0.2), _lin(s.get("obv_slope10"), -5, 5),
                   mfi_pts, up_day_vol, _lin(s.get("pvo"), -15, 20)])

    # volatility / breakout
    if s.get("donchian_breakdown"):
        vol = 5
    elif s.get("donchian_breakout"):
        vol = 90
    else:
        vol = _lin(s.get("dist_high20_pct"), -15, 0) * 0.8
        if (s.get("bb_width_rank") or 1) < 0.25 and (s.get("bb_pctb") or 0) > 0.5:
            vol = max(vol, 70)   # squeeze resolving upward
    volatility = _clamp(vol)

    # statistics / mean reversion
    up = (e200 and c > e200) or (e200 is None and e50 and c > e50)
    r2, z = s.get("rsi2"), s.get("zscore20")
    if up and r2 is not None and r2 < 10: st = 95
    elif up and r2 is not None and r2 < 25: st = 78
    elif up and z is not None and z < -1.5: st = 70
    elif z is not None and z > 2.5: st = 15
    elif not up and r2 is not None and r2 < 10: st = 45   # falling knife
    else: st = 50 - _clamp((z or 0) * 12, -20, 30)
    stats = _clamp(st)

    return {"trend": round(trend, 1), "momentum": round(momentum, 1), "rs": round(rs, 1),
            "volume": round(volume, 1), "volatility": round(volatility, 1), "stats": round(stats, 1)}


def alpha_score(snap: dict, profile: str = "momentum", families: list[str] | None = None) -> dict:
    """Weighted Alpha Score (0-100) plus its parts and a plain-English lean."""
    prof = PROFILES.get(profile, PROFILES["momentum"])
    fams = family_scores(snap)
    on = [f for f in (families or FAMILIES) if f in FAMILIES]
    w = {f: prof["weights"][f] for f in on if prof["weights"][f] > 0}
    if not w:                       # every weighted family switched off
        w = {f: 1.0 for f in on} or {f: 1.0 for f in FAMILIES}
    tot = sum(w.values())
    score = sum(fams[f] * w[f] for f in w) / tot

    # overextension penalty: chasing a vertical move rarely pays inside 2 weeks
    if (snap.get("rsi14") or 0) > 82 or (snap.get("zscore20") or 0) > 2.8:
        score -= 8

    score = round(_clamp(score), 1)
    lean = "BULLISH" if score >= 60 else "BEARISH" if score < 42 else "NEUTRAL"
    return {"alpha_score": score, "lean": lean, "families": fams,
            "weights_used": {k: round(v / tot, 3) for k, v in w.items()}}


def regime_score(spy: dict, qqq: dict | None = None, risk_ratio_roc: float | None = None) -> dict:
    """
    Market regime 0-100 from SPY/QQQ trend plus risk appetite
    (high beta SPHB vs low volatility SPLV, 20-day change of their ratio).
    Returns the score, a label and how much of the account to keep invested.
    """
    def trend_pts(s):
        if not s: return 50
        c, p = s.get("close") or 0, 0
        if s.get("ema20") and c > s["ema20"]: p += 30
        if s.get("ema50") and c > s["ema50"]: p += 30
        if s.get("ema200") and c > s["ema200"]: p += 25
        if (s.get("macd_hist") or 0) > 0: p += 15
        return p

    parts = [trend_pts(spy)]
    if qqq: parts.append(trend_pts(qqq))
    if risk_ratio_roc is not None: parts.append(_lin(risk_ratio_roc, -4, 4))
    score = round(sum(parts) / len(parts), 1)
    if score >= 65: label, invest = "RISK-ON", 0.97
    elif score >= 45: label, invest = "NEUTRAL", 0.90
    elif score >= 30: label, invest = "CAUTION", 0.75
    else: label, invest = "RISK-OFF", 0.55
    return {"regime_score": score, "regime": label, "invest_fraction": invest}
