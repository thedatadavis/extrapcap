from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo


EASTERN = ZoneInfo("America/New_York")


def execution_window(now: datetime) -> str:
    """Return a named US/Eastern operating window for a timestamp.

    Naive values are treated as Eastern for backwards-compatible tests and
    local callers; timezone-aware workflow timestamps are converted explicitly.
    """
    local = now.replace(tzinfo=EASTERN) if now.tzinfo is None else now.astimezone(EASTERN)
    current = local.time()
    if current < time(9, 45):
        return "market_open_guard"
    if current < time(11, 30):
        return "open_liquidity"
    if current < time(14, 30):
        return "lunch_liquidity"
    if current < time(15, 45):
        return "close_positioning"
    if current <= time(16, 0):
        return "near_close_guard"
    return "closed"
