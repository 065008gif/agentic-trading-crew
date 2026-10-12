"""
Tiny finance headline sentiment scorer (no downloads, no API).
Counts weighted bullish/bearish phrases in a headline and returns -1..+1.
The LLM news agent reads the headlines too; this gives it a numeric anchor.
"""

import re

POS = {
    "beat": 2, "beats": 2, "tops": 2, "surge": 2, "surges": 2, "soar": 2, "soars": 2, "record": 1.5,
    "raises guidance": 3, "raises outlook": 3, "upgrade": 2, "upgraded": 2, "outperform": 1.5,
    "buy rating": 1.5, "price target raised": 2, "raises price target": 2, "strong demand": 1.5,
    "rally": 1.5, "rallies": 1.5, "jumps": 1.5, "gains": 1, "partnership": 1, "contract": 1,
    "wins": 1, "approval": 1.5, "approved": 1.5, "buyback": 1.5, "repurchase": 1.5,
    "expands": 1, "breakout": 1, "all-time high": 1.5, "bullish": 1.5, "accelerat": 1,
}
NEG = {
    "miss": 2, "misses": 2, "plunge": 2.5, "plunges": 2.5, "tumble": 2, "tumbles": 2, "sinks": 2,
    "cuts guidance": 3, "lowers guidance": 3, "weak guidance": 2.5, "downgrade": 2, "downgraded": 2,
    "underperform": 1.5, "sell rating": 1.5, "price target cut": 2, "lowers price target": 2,
    "lawsuit": 1.5, "probe": 1.5, "investigation": 1.5, "sec charges": 2.5, "recall": 1.5,
    "layoffs": 1, "falls": 1, "drops": 1, "slides": 1, "warns": 2, "warning": 1.5, "delay": 1,
    "bearish": 1.5, "export ban": 2, "tariff": 1, "short seller": 2, "fraud": 3, "bankruptcy": 3,
    "halted": 1.5, "slump": 1.5, "decelerat": 1,
}


def score_headline(text: str) -> float:
    t = text.lower()
    pos = sum(w for k, w in POS.items() if re.search(r"\b" + re.escape(k), t))
    neg = sum(w for k, w in NEG.items() if re.search(r"\b" + re.escape(k), t))
    if pos == neg == 0:
        return 0.0
    return round((pos - neg) / (pos + neg), 2)
