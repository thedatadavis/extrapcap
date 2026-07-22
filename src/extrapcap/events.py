from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd


STRUCTURAL_TERMS = (
    "fraud",
    "doj",
    "department of justice",
    "investigation",
    "accounting issue",
    "restatement",
    "bankruptcy",
    "going concern",
    "regulatory shock",
    "subpoena",
)


@dataclass(frozen=True)
class EventDecision:
    category: str
    allowed: bool
    reason: str


def classify_headline(headline: str) -> EventDecision:
    normalized = headline.casefold()
    matched = next((term for term in STRUCTURAL_TERMS if term in normalized), None)
    if matched:
        return EventDecision("structural_risk", False, f"matched:{matched}")
    return EventDecision("noise_or_opinion", True, "no structural-risk term matched")


def earnings_blackout(trading_day: date, earnings_day: date, calendar_days: int = 3) -> EventDecision:
    distance = abs((trading_day - earnings_day).days)
    if distance <= calendar_days:
        return EventDecision("earnings", False, f"within_{calendar_days}_calendar_days")
    return EventDecision("earnings", True, "outside earnings blackout")


def decision_from_csv(path: str | Path, symbol: str, trading_day: date, reviewer=None) -> EventDecision:
    """Read a dated structural-risk event file without allowing malformed data through."""
    frame = pd.read_csv(path, parse_dates=["date"])
    required = {"date", "symbol", "structural_risk"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"event file missing required columns: {sorted(missing)}")
    matches = frame[
        (frame["date"].dt.date == trading_day)
        & (frame["symbol"].astype(str).str.upper() == symbol.upper())
    ]
    for row in matches.itertuples():
        value = row.structural_risk
        structural = value if isinstance(value, bool) else str(value).casefold() in {"1", "true", "yes", "y"}
        if structural:
            return EventDecision("structural_risk", False, "dated_event_file")
        headline = str(getattr(row, "headline", "") or "").strip()
        if headline and reviewer is not None:
            local = classify_headline(headline)
            if not local.allowed:
                return local
            try:
                judgment = reviewer.classify_headline(headline, symbol)
            except Exception as exc:
                return EventDecision("structural_risk", False, f"llm_failure:{type(exc).__name__}")
            if judgment.get("category") != "noise_or_opinion" or judgment.get("structural_risk") is not False:
                return EventDecision("structural_risk", False, f"llm:{judgment.get('reason', 'escalated')}")
    return EventDecision("noise_or_opinion", True, "no dated structural-risk event")
