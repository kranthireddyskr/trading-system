from __future__ import annotations

from datetime import datetime


POSITIVE_KEYWORDS = {
    "beats",
    "surge",
    "rally",
    "strong",
    "growth",
    "upgrade",
    "outperform",
    "expands",
    "profit",
    "record",
    "partnership",
    "bullish",
    "momentum",
    "guidance",
    "raises",
}

NEGATIVE_KEYWORDS = {
    "misses",
    "drop",
    "falls",
    "weak",
    "downgrade",
    "lawsuit",
    "probe",
    "cuts",
    "bearish",
    "loss",
    "fraud",
    "warning",
    "recall",
    "delay",
    "decline",
}


def parse_timestamp(value):
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def headline_sentiment(text):
    cleaned = text.lower().replace(".", " ").replace(",", " ")
    score = 0.0
    for token in cleaned.split():
        if token in POSITIVE_KEYWORDS:
            score += 1.0
        elif token in NEGATIVE_KEYWORDS:
            score -= 1.0
    return score
