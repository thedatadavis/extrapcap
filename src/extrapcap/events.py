from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
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
    details: dict | None = None


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


def earnings_decision_from_csv(
    path: str | Path,
    symbol: str,
    trading_day: date,
    *,
    metadata_path: str | Path | None = None,
    calendar_days: int = 3,
    now: datetime | None = None,
    max_age_hours: float = 36,
) -> EventDecision:
    """Fail closed unless a fresh calendar covers the complete blackout window."""
    target = Path(path)
    sidecar = Path(metadata_path or f"{target}.metadata.json")
    details = {
        "ticker": symbol.upper(),
        "trading_day": trading_day.isoformat(),
        "calendar_days": calendar_days,
        "calendar_path": str(target),
        "metadata_path": str(sidecar),
    }
    if not target.exists() or not sidecar.exists():
        return EventDecision("earnings", False, "earnings_calendar_missing", details)
    try:
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        retrieved_at = datetime.fromisoformat(str(metadata["retrieved_at"]).replace("Z", "+00:00"))
        queried_dates = {date.fromisoformat(value) for value in metadata["queried_dates"]}
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return EventDecision(
            "earnings",
            False,
            f"earnings_calendar_metadata_invalid:{type(exc).__name__}",
            details,
        )
    observed_at = now or datetime.now(timezone.utc)
    if retrieved_at.tzinfo is None:
        retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)
    age_hours = (observed_at.astimezone(timezone.utc) - retrieved_at.astimezone(timezone.utc)).total_seconds() / 3600
    details.update(
        {
            "source": metadata.get("source"),
            "retrieved_at": retrieved_at.isoformat(),
            "age_hours": round(age_hours, 3),
            "coverage_start": metadata.get("coverage_start"),
            "coverage_end": metadata.get("coverage_end"),
        }
    )
    if age_hours < -0.25 or age_hours > max_age_hours:
        return EventDecision("earnings", False, "earnings_calendar_stale", details)
    required_dates = {
        trading_day + timedelta(days=offset)
        for offset in range(-calendar_days, calendar_days + 1)
    }
    missing_dates = sorted(required_dates - queried_dates)
    if missing_dates:
        details["missing_dates"] = [value.isoformat() for value in missing_dates]
        return EventDecision("earnings", False, "earnings_calendar_incomplete", details)
    try:
        frame = pd.read_csv(target, parse_dates=["date"])
    except Exception as exc:
        return EventDecision("earnings", False, f"earnings_calendar_invalid:{type(exc).__name__}", details)
    required = {"date", "symbol"}
    if missing := required - set(frame.columns):
        details["missing_columns"] = sorted(missing)
        return EventDecision("earnings", False, "earnings_calendar_invalid_columns", details)
    matches = frame[
        frame["date"].dt.date.isin(required_dates)
        & (frame["symbol"].astype(str).str.upper() == symbol.upper())
    ].sort_values("date")
    if not matches.empty:
        earnings_dates = [value.date().isoformat() for value in matches["date"]]
        details["earnings_dates"] = earnings_dates
        return EventDecision("earnings", False, f"earnings_blackout:{earnings_dates[0]}", details)
    return EventDecision("earnings", True, "outside earnings blackout", details)


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
