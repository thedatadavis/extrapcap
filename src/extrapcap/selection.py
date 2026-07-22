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


def completed_signal_alignment_reason(
    formation: dict,
    live: dict,
    *,
    z_tolerance: float = 1e-6,
    return_tolerance: float = 1e-8,
) -> str | None:
    """Require a versioned basket row to match fresh provider recomputation."""
    if _positive_int(formation.get("streak_length")) != _positive_int(live.get("streak_length")):
        return "formation_streak_length_mismatch"
    if formation.get("streak_direction") != live.get("streak_direction"):
        return "formation_streak_direction_mismatch"
    formation_z = _finite_float(formation.get("robust_z"))
    live_z = _finite_float(live.get("robust_z"))
    if formation_z is None or live_z is None or abs(formation_z - live_z) > z_tolerance:
        return "formation_robust_z_mismatch"
    formation_return = _finite_float(formation.get("relative_return"))
    live_return = _finite_float(live.get("relative_return"))
    if (
        formation_return is None
        or live_return is None
        or abs(formation_return - live_return) > return_tolerance
    ):
        return "formation_relative_return_mismatch"
    return None


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
