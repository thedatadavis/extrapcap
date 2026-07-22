from __future__ import annotations

from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class CoreSelectionDecision:
    allowed: bool
    reason: str
    strategy_route: str
    streak_direction: str | None
    streak_length: int | None
    robust_z: float | None
    z_threshold: float

    def as_dict(self) -> dict:
        return asdict(self)


def _finite_float(value) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _positive_int(value) -> int | None:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def core_streak_gate(context: dict, z_threshold: float = -2.0) -> CoreSelectionDecision:
    """Gate the currently implemented bullish core route with completed streak evidence.

    Negative market-relative streaks are the paper-inspired mean-reversion side of
    the signal. Positive streaks need a separately constructed bearish route and
    therefore cannot silently enter the bull-put engine.
    """
    direction = context.get("streak_direction")
    length = _positive_int(context.get("streak_length"))
    robust_z = _finite_float(context.get("robust_z"))
    route = "core_mean_reversion" if direction == "negative" else "bearish_reversal_watch"
    if direction != "negative":
        return CoreSelectionDecision(
            False,
            "core_requires_negative_relative_streak",
            route,
            direction,
            length,
            robust_z,
            z_threshold,
        )
    if length is None or not 2 <= length <= 5:
        return CoreSelectionDecision(
            False,
            "completed_streak_length_outside_2_to_5",
            route,
            direction,
            length,
            robust_z,
            z_threshold,
        )
    if robust_z is None:
        return CoreSelectionDecision(
            False,
            "missing_robust_z",
            route,
            direction,
            length,
            robust_z,
            z_threshold,
        )
    if robust_z > z_threshold:
        return CoreSelectionDecision(
            False,
            "robust_z_above_entry_threshold",
            route,
            direction,
            length,
            robust_z,
            z_threshold,
        )
    return CoreSelectionDecision(True, "approved", route, direction, length, robust_z, z_threshold)


def streak_priority_key(context: dict) -> tuple:
    """Rank the paper's longer streak buckets first without inventing a sizing rule."""
    direction = context.get("streak_direction")
    length = _positive_int(context.get("streak_length")) or 0
    robust_z = _finite_float(context.get("robust_z"))
    return (
        0 if direction == "negative" else 1,
        -length,
        robust_z if robust_z is not None else float("inf"),
        str(context.get("ticker", "")),
    )
