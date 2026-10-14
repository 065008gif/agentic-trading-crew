"""
Risk Manager (rule-based, no LLM): turns Alpha Scores + the Portfolio
Manager agent's bounded adjustments into target weights and orders.

Why rules here and not the LLM: an LLM can misread a number or invent one.
Sizing, stops and cash checks must be exact, so they are plain Python that
the LLM can only nudge inside fixed limits (+/-15 score points, a buy veto,
and an exposure setting between 50% and 98%).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta


@dataclass
class RiskSettings:
    max_position_pct: float = 0.25      # cap per stock (aggressive: the brief says "MUST take risks")
    max_holdings: int = 8               # concentrate on the strongest 8 of the 13 (all 13 stay tradable)
    weight_power: float = 2.5           # how hard money tilts to the top scores (1.5 = gentler)
    hold_bonus: float = 5.0             # a held stock keeps its slot unless a newcomer beats it by 5+
    same_day_drop: float = 15.0         # a stock bought today may be sold today if its score fell this much
    min_position_pct: float = 0.03      # smaller targets are dropped (not worth the noise)
    entry_score: float = 52             # new buys need at least this final score
    exit_score: float = 40              # held stocks are sold below this (hysteresis)
    rebalance_band_pct: float = 0.02    # ignore changes smaller than 2% of equity (less churn)
    min_order_dollars: float = 300
    max_exposure: float = 0.98          # never use margin
    earnings_cap_pct: float = 0.05      # A/C profiles shrink to 5% the day before a report
    overextended_cap_pct: float = 0.07  # RSI>82 and z>2.5: lock in gains
    max_llm_adjust: float = 15
    unsupported_adjust: float = 5       # PM moves beyond +/-5 need news pointing the same way
    news_support: float = 0.10          # |sentiment| that counts as news support for a big adjustment
    veto_news: float = -0.25            # a buy veto needs news at least this negative (or a breakdown)
    min_holdings: int = 8               # if fewer qualify, add the next-best names scoring >= exit_score
    filler_weight_pct: float = 0.05     # fixed small size for those added names (never more)
    lock_trigger: float = 0.06          # once a holding has been up 6%+ from our entry ...
    lock_keep: float = 0.60             # ... keep at least 60% of the best gain (profit lock)


@dataclass
class Target:
    symbol: str
    alpha: float
    adjust: float
    final: float
    current_value: float = 0.0
    current_weight: float = 0.0
    target_weight: float = 0.0
    action: str = "HOLD"          # BUY / ADD / TRIM / EXIT / HOLD / AVOID
    dollars: float = 0.0          # + buy, - sell
    qty: float = 0.0              # shares to sell (sells only)
    reasons: list = field(default_factory=list)


def _earnings_soon(note: str | None, today: date) -> bool:
    """True if a report lands before the next trading session ends."""
    if not note or not note.startswith("earnings "):
        return False
    try:
        d = date.fromisoformat(note.split()[1])
        when = note.split()[2]
    except (IndexError, ValueError):
        return False
    nxt = today + timedelta(days=3 if today.weekday() == 4 else 1)
    return d == today or (d == nxt and when == "BMO") or (d == today and when == "AMC")


def _capped_split(raw: dict, budget: float, cap: float) -> dict:
    """Split `budget` by score weight, cap each name, and pass the excess to the
    names still under the cap (if every name is capped, the rest stays cash)."""
    tot = sum(raw.values())
    weights = {s: budget * v / tot for s, v in raw.items()}
    for _ in range(10):
        over = {s: w for s, w in weights.items() if w > cap + 1e-9}
        if not over:
            break
        spare = sum(w - cap for w in over.values())
        for s in over:
            weights[s] = cap
        free = {s: raw[s] for s in weights if weights[s] < cap - 1e-9}
        if not free:
            break
        ft = sum(free.values())
        for s, v in free.items():
            weights[s] += spare * v / ft
    return weights


def build_plan(rows: list[dict], regime: dict, positions: dict, account: dict,
               overlay: dict | None = None, profile: str = "momentum",
               hold_through_earnings: bool = False, settings: RiskSettings | None = None,
               today: date | None = None, evidence: dict | None = None,
               peaks: dict | None = None, no_rebuy: dict | None = None,
               bought_today: dict | None = None) -> dict:
    """evidence: {symbol: {"sentiment": float, "articles": int}} from the news
    server. When given, the Portfolio Manager's adjustments and vetoes are
    checked against it, so an LLM misreading cannot move money on its own.
    peaks: {symbol: highest price seen while we held it} for the profit lock.
    no_rebuy: {symbol: score when sold, or None} for stocks fully sold today. After a stop or
    the profit lock (None) no re-buy today; after a soft sale, a re-buy today only if the
    score is now 15+ points higher than when it was sold.
    bought_today: {symbol: final score when it was bought} for stocks first bought today.
    They are not sold or trimmed again today for a small wobble in the AI score; they CAN
    be sold the same day if the stop, the profit lock, a score below the exit level, or a
    real deterioration (final score 15+ points below the buy score) says so."""
    rs = settings or RiskSettings()
    overlay = overlay or {}
    if today is None:
        from trading.alpaca_rest import market_today
        today = market_today()
    equity = float(account.get("equity") or account.get("portfolio_value") or 0)
    if equity <= 0:
        raise ValueError("Account equity is zero or missing")

    adjustments = {a["symbol"].upper(): a for a in overlay.get("adjustments", []) if a.get("symbol")}
    exposure = float(regime.get("invest_fraction", 0.9))
    if overlay.get("exposure") is not None:
        # the PM agent may tilt exposure by at most 10 points, within 50%..98%
        want = float(overlay["exposure"])
        want = max(exposure - 0.10, min(exposure + 0.10, want))
        exposure = max(0.5, min(rs.max_exposure, want))
    exposure = min(exposure, rs.max_exposure)

    by_sym = {r["symbol"]: r for r in rows}
    targets: dict[str, Target] = {}
    for sym, r in by_sym.items():
        a = dict(adjustments.get(sym, {}))
        adj = max(-rs.max_llm_adjust, min(rs.max_llm_adjust, float(a.get("adjust", 0) or 0)))
        checks = []
        if evidence is not None:
            sent = float((evidence.get(sym) or {}).get("sentiment", 0) or 0)
            if adj > rs.unsupported_adjust and sent < rs.news_support:
                checks.append(f"capped {adj:+.0f}->{rs.unsupported_adjust:+.0f}, news {sent:+.2f} does not support it")
                adj = rs.unsupported_adjust
            elif adj < -rs.unsupported_adjust and sent > -rs.news_support and not r.get("breakdown"):
                checks.append(f"capped {adj:+.0f}->{-rs.unsupported_adjust:+.0f}, news {sent:+.2f} does not support it")
                adj = -rs.unsupported_adjust
            if a.get("veto_buy") and sent > rs.veto_news and not r.get("breakdown"):
                checks.append(f"veto ignored, news {sent:+.2f} not negative enough")
                a["veto_buy"] = False
            adjustments[sym] = a
        final = max(0.0, min(100.0, r["alpha_score"] + adj))
        held = positions.get(sym, {})
        t = Target(sym, r["alpha_score"], adj, round(final, 1),
                   current_value=float(held.get("market_value", 0)),
                   current_weight=float(held.get("market_value", 0)) / equity)
        if adj or checks:
            t.reasons.append(f"PM adjust {adj:+.0f}: {a.get('note', '')[:80]}")
        t.reasons += [f"Risk check: {c}" for c in checks]
        targets[sym] = t

    # held stocks we have no data for: keep untouched and say so
    for sym, p in positions.items():
        if sym not in targets:
            t = Target(sym, -1, 0, -1, current_value=p["market_value"],
                       current_weight=p["market_value"] / equity, action="HOLD")
            t.target_weight = t.current_weight
            t.reasons.append("no indicator data; left unchanged")
            targets[sym] = t

    # ---------------- eligibility and exits
    raw = {}
    for sym, t in targets.items():
        if t.alpha < 0:
            continue
        r = by_sym[sym]
        held = t.current_value > 0
        close, stop = r.get("close"), r.get("stop")
        veto = bool(adjustments.get(sym, {}).get("veto_buy"))
        if held and close and stop and close < stop:
            t.action = "EXIT"; t.reasons.append(f"stop hit: close {close} < chandelier stop {stop}")
            continue
        avg = float(positions.get(sym, {}).get("avg_entry") or 0)
        peak = max(float((peaks or {}).get(sym) or 0), float(close or 0))
        if held and close and avg and peak >= avg * (1 + rs.lock_trigger):
            floor = avg + rs.lock_keep * (peak - avg)
            if close < floor:
                t.action = "EXIT"
                t.reasons.append(f"profit lock: best gain {peak / avg - 1:+.1%}, now {close / avg - 1:+.1%}; "
                                 f"price {close} fell below the lock {floor:.2f}, booking the profit")
                continue
            t.reasons.append(f"profit lock active: sells below {floor:.2f} (keeps at least "
                             f"{floor / avg - 1:+.1%})")
        if not held and no_rebuy and sym in no_rebuy:
            sold_at = no_rebuy[sym]
            if sold_at is None:
                t.action = "AVOID"; t.reasons.append("sold today by a stop or the profit lock; no re-buy until tomorrow")
                continue
            if t.final < float(sold_at) + rs.same_day_drop:
                t.action = "AVOID"
                t.reasons.append(f"sold earlier today at score {sold_at}; re-buy only if the score rises "
                                 f"{rs.same_day_drop:.0f}+ points (now {t.final})")
                continue
            t.reasons.append(f"sold earlier today at score {sold_at}, now {t.final}: clearly stronger, re-buy allowed")
        if held and t.final < rs.exit_score:
            t.action = "EXIT"; t.reasons.append(f"score {t.final} below exit level {rs.exit_score}")
            continue
        if held and r.get("breakdown") and t.final < 50:
            t.action = "EXIT"; t.reasons.append("20-day breakdown with weak score")
            continue
        threshold = rs.exit_score if held else rs.entry_score
        if t.final < threshold or (veto and not held) or (r.get("breakdown") and not held):
            t.action = "AVOID" if not held else t.action
            if veto and not held:
                t.reasons.append("PM vetoed new buy")
            elif not held:
                t.reasons.append(f"score {t.final} below entry {rs.entry_score}")
            continue
        raw[sym] = max(t.final - 45, 2) ** rs.weight_power   # floor keeps held names in the 40-45 band small, never negative

    # concentrate: only the best max_holdings names get money (held names get a small bonus
    # so the portfolio does not flip back and forth between two similar scores every run)
    if len(raw) > rs.max_holdings:
        rank = sorted(raw, key=lambda s: -(targets[s].final + (rs.hold_bonus if targets[s].current_value > 0 else 0)))
        for s in rank[rs.max_holdings:]:
            del raw[s]
            targets[s].reasons.append(f"not in the top {rs.max_holdings}: money goes to stronger names")

    # top up to min_holdings with the next-best names that are not broken
    forced: set[str] = set()
    # fillers never outnumber the stocks that genuinely qualified
    if raw and len(raw) < rs.min_holdings:
        spare_names = sorted((t for s, t in targets.items() if s not in raw and t.alpha >= 0
                              and t.action not in ("EXIT",) and t.final >= rs.exit_score
                              and not adjustments.get(s, {}).get("veto_buy")
                              and not by_sym[s].get("breakdown")), key=lambda t: -t.final)
        for t in spare_names[: min(rs.min_holdings - len(raw), len(raw))]:
            forced.add(t.symbol)
            t.reasons = [r for r in t.reasons if "below entry" not in r] + ["added to reach minimum holdings"]

    # ---------------- weights: score-tilted, capped, renormalised
    # Qualified stocks share the budget by score, each capped at max_position_pct.
    # Fillers get a fixed small weight and never absorb leftover money: if the
    # strong names are all at their cap, the remainder stays in cash.
    weights = {}
    if raw:
        filler_w = min(rs.filler_weight_pct, rs.max_position_pct)
        budget = max(0.0, exposure - filler_w * len(forced))
        pool = dict(raw)
        while pool:
            weights = _capped_split(pool, budget, rs.max_position_pct)
            small = [s for s, w in weights.items() if w < rs.min_position_pct - 1e-9]
            if not small:
                break
            # too small to be worth holding: drop the weakest and share its money
            # among the rest instead of leaving it as idle cash
            drop = min(small, key=lambda s: pool[s])
            targets[drop].reasons.append(f"target below the {rs.min_position_pct:.0%} minimum position; "
                                         "its money goes to stronger names")
            del pool[drop]
            weights = {}
        for s in forced:
            weights[s] = filler_w

    for sym, w in weights.items():
        t, r = targets[sym], by_sym[sym]
        if not hold_through_earnings and _earnings_soon(r.get("earnings"), today) and w > rs.earnings_cap_pct:
            w = rs.earnings_cap_pct
            t.reasons.append(f"earnings next session ({r['earnings']}): capped at {rs.earnings_cap_pct:.0%}")
        if (r.get("rsi14") or 0) > 82 and (r.get("zscore") or 0) > 2.5 and w > rs.overextended_cap_pct:
            w = rs.overextended_cap_pct
            t.reasons.append("overextended (RSI>82, z>2.5): trimmed to lock gains")
        t.target_weight = w

    # ---------------- orders
    band = max(rs.rebalance_band_pct * equity, rs.min_order_dollars)
    orders = []
    for sym, t in targets.items():
        if t.alpha < 0:
            continue
        price = by_sym[sym].get("close") or 0
        if t.action == "EXIT":
            t.target_weight = 0.0
            t.dollars = -t.current_value
            orders.append({"symbol": sym, "side": "sell", "type": "close", "dollars": round(-t.dollars, 2),
                           "reason": "; ".join(t.reasons)})
            continue
        tgt_val = t.target_weight * equity
        delta = tgt_val - t.current_value
        if t.current_value == 0 and t.target_weight == 0:
            t.action = "AVOID"
            continue
        if abs(delta) < band:
            t.action = "HOLD"
            if t.current_value:
                t.reasons.append("within rebalance band")
            continue
        if delta < 0 and bought_today and sym in bought_today:
            buy_score = bought_today[sym]
            if buy_score is None or t.final > float(buy_score) - rs.same_day_drop:
                # only a small wobble since the buy: do not flip-flop (hard exits were handled above)
                t.action = "HOLD"
                t.target_weight = t.current_weight
                t.reasons.append(f"bought today at score {buy_score}; score {t.final} has not dropped "
                                 f"{rs.same_day_drop:.0f}+ points, so kept (stop and profit lock still apply)")
                continue
            t.reasons.append(f"bought today at score {buy_score} but now {t.final}: real deterioration, selling allowed")
        if delta > 0:
            t.action = "BUY" if t.current_value == 0 else "ADD"
            t.dollars = round(delta, 2)
            orders.append({"symbol": sym, "side": "buy", "type": "dollars", "dollars": t.dollars,
                           "reason": f"score {t.final}; target {t.target_weight:.1%}"})
        elif t.target_weight == 0:
            t.action = "EXIT"
            t.dollars = round(-t.current_value, 2)
            orders.append({"symbol": sym, "side": "sell", "type": "close", "dollars": t.current_value,
                           "reason": f"score {t.final} no longer earns a position"})
        else:
            t.action = "TRIM"
            t.dollars = round(delta, 2)
            t.qty = round(min(-delta / price, positions[sym]["qty"]), 4) if price else 0
            orders.append({"symbol": sym, "side": "sell", "type": "qty", "qty": t.qty,
                           "dollars": round(-delta, 2),
                           "reason": f"score {t.final}; target {t.target_weight:.1%}"
                                     + (f"; {'; '.join(t.reasons)}" if t.reasons else "")})

    # ---------------- cash check: buys never exceed cash + sell proceeds - buffer
    cash = float(account.get("cash", 0))
    proceeds = sum(o["dollars"] for o in orders if o["side"] == "sell")
    buffer = (1 - rs.max_exposure) * equity
    available = cash + proceeds - buffer
    buys = [o for o in orders if o["side"] == "buy"]
    need = sum(o["dollars"] for o in buys)
    if need > available and need > 0:
        scale = max(0.0, available / need)
        for o in buys:
            o["dollars"] = round(o["dollars"] * scale, 2)
            if scale < 0.995:   # rounding-level trims are not worth a note
                o["reason"] += f"; scaled x{scale:.2f} to available cash"
        orders = [o for o in orders if o["side"] == "sell" or o["dollars"] >= rs.min_order_dollars]

    orders.sort(key=lambda o: 0 if o["side"] == "sell" else 1)  # sells first
    invested_after = sum(t.target_weight for t in targets.values())
    return {
        "date": today.isoformat(), "profile": profile, "equity": round(equity, 2), "cash": round(cash, 2),
        "regime": regime.get("regime"), "regime_score": regime.get("regime_score"),
        "exposure_target": round(exposure, 3), "invested_after_pct": round(100 * invested_after, 1),
        "settings": asdict(rs),
        "targets": [asdict(t) for t in sorted(targets.values(), key=lambda x: -x.final)],
        "orders": orders,
        "pm_summary": overlay.get("summary", ""),
    }


def plan_markdown(plan: dict) -> str:
    L = [f"**Equity:** ${plan['equity']:,.0f} | **Cash:** ${plan['cash']:,.0f} | "
         f"**Regime:** {plan['regime']} ({plan['regime_score']}) | "
         f"**Target exposure:** {plan['exposure_target']:.0%} | **Invested after plan:** {plan['invested_after_pct']}%",
         "", "| Symbol | Alpha | PM adj | Final | Now | Target | Action | Why |", "|---|---|---|---|---|---|---|---|"]
    for t in plan["targets"]:
        L.append(f"| {t['symbol']} | {t['alpha']} | {t['adjust']:+.0f} | {t['final']} | {t['current_weight']:.1%} | "
                 f"{t['target_weight']:.1%} | {t['action']} | {'; '.join(t['reasons'])[:140]} |")
    L += ["", "**Orders (sells first):**", ""]
    if not plan["orders"]:
        L.append("- none (portfolio already at target)")
    for o in plan["orders"]:
        size = f"{o['qty']} sh" if o.get("type") == "qty" else ("ALL" if o.get("type") == "close" else "")
        L.append(f"- {o['side'].upper()} {o['symbol']} ${o['dollars']:,.0f} {size} - {o['reason']}")
    if plan.get("pm_summary"):
        L += ["", f"**Portfolio Manager summary:** {plan['pm_summary']}"]
    return "\n".join(L)
