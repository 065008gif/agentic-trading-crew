"""
Technical indicators, written in plain pandas so they run identically on
Linux and Windows with no compiled dependencies.

The set follows the professor's suggested feature tree (trend, momentum,
volume, volatility, statistics) and uses the same formulas as pandas_ta.
Every function takes a DataFrame with columns open/high/low/close/volume
(oldest row first) and returns a Series aligned to it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------- trend
def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def _wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    prev = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"],
                      (df["high"] - prev).abs(),
                      (df["low"] - prev).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return _wilder(true_range(df), n)


def adx(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """ADX with +DI / -DI (Wilder)."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr = _wilder(true_range(df), n)
    plus_di = 100 * _wilder(plus_dm, n) / tr
    minus_di = 100 * _wilder(minus_dm, n) / tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return pd.DataFrame({"adx": _wilder(dx, n), "plus_di": plus_di, "minus_di": minus_di})


# ---------------------------------------------------------------- momentum
def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    gain = _wilder(d.clip(lower=0), n)
    loss = _wilder((-d).clip(lower=0), n)
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.fillna(100.0).where(loss.notna())


def macd(s: pd.Series, fast: int = 12, slow: int = 26, sig: int = 9) -> pd.DataFrame:
    line = s.ewm(span=fast, adjust=False).mean() - s.ewm(span=slow, adjust=False).mean()
    signal = line.ewm(span=sig, adjust=False).mean()
    return pd.DataFrame({"macd": line, "signal": signal, "hist": line - signal})


def roc(s: pd.Series, n: int) -> pd.Series:
    return 100 * (s / s.shift(n) - 1)


def tsi(s: pd.Series, long: int = 25, short: int = 13) -> pd.Series:
    d = s.diff()
    num = d.ewm(span=long, adjust=False).mean().ewm(span=short, adjust=False).mean()
    den = d.abs().ewm(span=long, adjust=False).mean().ewm(span=short, adjust=False).mean()
    return 100 * num / den.replace(0, np.nan)


# ---------------------------------------------------------------- volume
def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def cmf(df: pd.DataFrame, n: int = 20) -> pd.Series:
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    mfm = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / rng
    mfv = mfm.fillna(0) * df["volume"]
    return mfv.rolling(n).sum() / df["volume"].rolling(n).sum()


def mfi(df: pd.DataFrame, n: int = 14) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    flow = tp * df["volume"]
    pos = flow.where(tp > tp.shift(1), 0.0).rolling(n).sum()
    neg = flow.where(tp < tp.shift(1), 0.0).rolling(n).sum()
    return 100 - 100 / (1 + pos / neg.replace(0, np.nan))


def pvo(df: pd.DataFrame, fast: int = 12, slow: int = 26) -> pd.Series:
    v = df["volume"]
    f, s = v.ewm(span=fast, adjust=False).mean(), v.ewm(span=slow, adjust=False).mean()
    return 100 * (f - s) / s.replace(0, np.nan)


# ---------------------------------------------------------------- volatility
def bollinger(s: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = sma(s, n)
    sd = s.rolling(n).std(ddof=0)
    upper, lower = mid + k * sd, mid - k * sd
    return pd.DataFrame({"mid": mid, "upper": upper, "lower": lower,
                         "width": (upper - lower) / mid,
                         "pctb": (s - lower) / (upper - lower).replace(0, np.nan)})


def donchian(df: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    # previous n bars (excluding today) so "breakout" means today beat them
    return pd.DataFrame({"upper": df["high"].shift(1).rolling(n).max(),
                         "lower": df["low"].shift(1).rolling(n).min()})


# ---------------------------------------------------------------- statistics
def zscore(s: pd.Series, n: int = 20) -> pd.Series:
    return (s - sma(s, n)) / s.rolling(n).std(ddof=0).replace(0, np.nan)


def slope_pct(s: pd.Series, n: int) -> pd.Series:
    """Percent change of a series over n bars (used for OBV / EMA slope)."""
    base = s.shift(n).abs().replace(0, np.nan)
    return 100 * (s - s.shift(n)) / base


# ---------------------------------------------------------------- snapshot
def snapshot(df: pd.DataFrame, bench: pd.DataFrame | None = None) -> dict:
    """Latest value of every indicator for one symbol, as plain floats."""
    c = df["close"]
    a = adx(df)
    m = macd(c)
    bb = bollinger(c)
    dc = donchian(df)
    at = atr(df)
    ob = obv(df)

    def last(x, nd=2):
        v = x.iloc[-1] if isinstance(x, pd.Series) else x
        return None if v is None or pd.isna(v) else round(float(v), nd)

    snap = {
        "close": last(c, 2),
        "ema20": last(ema(c, 20)), "ema50": last(ema(c, 50)), "ema200": last(ema(c, 200)),
        "ema20_slope5": last(slope_pct(ema(c, 20), 5)),
        "adx": last(a["adx"], 1), "plus_di": last(a["plus_di"], 1), "minus_di": last(a["minus_di"], 1),
        "rsi14": last(rsi(c, 14), 1), "rsi2": last(rsi(c, 2), 1),
        "macd_hist": last(m["hist"], 3), "macd_hist_prev": last(m["hist"].shift(1), 3),
        "roc5": last(roc(c, 5)), "roc10": last(roc(c, 10)), "roc20": last(roc(c, 20)),
        "tsi": last(tsi(c), 1),
        "cmf": last(cmf(df), 3), "mfi": last(mfi(df), 1), "pvo": last(pvo(df), 1),
        "obv_slope10": last(slope_pct(ob, 10)),
        "rel_volume": last(df["volume"].iloc[-1] / df["volume"].rolling(20).mean().iloc[-1]),
        "atr_pct": last(100 * at / c),
        "bb_width": last(bb["width"], 3), "bb_pctb": last(bb["pctb"], 2),
        "bb_width_rank": last(bb["width"].rolling(120, min_periods=40).rank(pct=True), 2),
        "donchian_breakout": bool(c.iloc[-1] > dc["upper"].iloc[-1]) if pd.notna(dc["upper"].iloc[-1]) else False,
        "donchian_breakdown": bool(c.iloc[-1] < dc["lower"].iloc[-1]) if pd.notna(dc["lower"].iloc[-1]) else False,
        "zscore20": last(zscore(c, 20)),
        "ret_1d": last(roc(c, 1)), "ret_20d": last(roc(c, 20)),
        "dist_high20_pct": last(100 * (c / df["high"].rolling(20).max() - 1)),
        # chandelier-style protective stop: highest close of 10 bars minus 2.5 ATR
        "chandelier_stop": last(c.rolling(10).max() - 2.5 * at),
        "bars": int(len(df)),
        "as_of": str(df.index[-1])[:10],
    }
    if bench is not None and len(bench) > 21:
        b = bench["close"].reindex(df.index).ffill()
        snap["rs_vs_spy_20d"] = last(roc(c, 20) - roc(b, 20))
        snap["rs_vs_spy_5d"] = last(roc(c, 5) - roc(b, 5))
        # rolling beta to the benchmark over 60 days
        r, rb = c.pct_change(), b.pct_change()
        cov = r.rolling(60).cov(rb)
        var = rb.rolling(60).var()
        snap["beta60"] = last(cov / var.replace(0, np.nan))
    return snap
