from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd


EASTERN = ZoneInfo("America/New_York")
DAILY_BAR_FINALIZATION_TIME = time(16, 15)


def normalize_stock_bars(payload: dict) -> pd.DataFrame:
    rows = []
    for symbol, bars in payload.get("bars", {}).items():
        for bar in bars:
            rows.append({"date": pd.to_datetime(bar["t"], utc=True), "symbol": symbol, "open": bar["o"], "high": bar["h"], "low": bar["l"], "close": bar["c"], "volume": bar["v"], "vwap": bar.get("vw")})
    if not rows:
        return pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close", "volume", "vwap"])
    return pd.DataFrame(rows).sort_values(["symbol", "date"]).reset_index(drop=True)


def completed_session_cutoff(
    now: datetime | None = None,
    finalization_time: time = DAILY_BAR_FINALIZATION_TIME,
) -> date:
    """Return the newest U.S. session date whose daily bar may be treated as final."""
    observed = now or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        raise ValueError("completed-session cutoff requires a timezone-aware timestamp")
    eastern = observed.astimezone(EASTERN)
    return eastern.date() if eastern.time() >= finalization_time else eastern.date() - timedelta(days=1)


def bar_session_date(value) -> date:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return timestamp.tz_convert(EASTERN).date()


def completed_daily_bars(
    frame: pd.DataFrame,
    now: datetime | None = None,
    finalization_time: time = DAILY_BAR_FINALIZATION_TIME,
) -> pd.DataFrame:
    """Remove the current partial Alpaca daily bar before signal formation."""
    if frame.empty:
        return frame.copy()
    if "date" not in frame.columns:
        raise ValueError("daily bars require a date column")
    cutoff = completed_session_cutoff(now, finalization_time)
    dates = pd.to_datetime(frame["date"], utc=True)
    session_dates = dates.dt.tz_convert(EASTERN).dt.date
    result = frame.loc[session_dates <= cutoff].copy()
    result["date"] = dates.loc[result.index]
    return result.reset_index(drop=True)


def completed_formation_reason(
    latest_completed_as_of,
    formation_as_of=None,
    *,
    now: datetime | None = None,
    max_age_days: int = 4,
) -> str | None:
    """Validate freshness and basket/provider alignment for a daily formation bar."""
    if max_age_days < 0:
        raise ValueError("max_age_days cannot be negative")
    latest_session = bar_session_date(latest_completed_as_of)
    cutoff = completed_session_cutoff(now)
    if latest_session > cutoff:
        return "latest_daily_bar_not_completed"
    if (cutoff - latest_session).days > max_age_days:
        return "latest_completed_bar_stale"
    if formation_as_of is not None:
        try:
            formation_session = bar_session_date(formation_as_of)
        except (TypeError, ValueError):
            return "invalid_formation_date"
        if formation_session != latest_session:
            return "formation_bar_mismatch"
    return None
