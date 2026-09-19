from __future__ import annotations

import math
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CoreSelectionDecision:
    allowed: bool
    reason: str
    strategy_route: str
    streak_direction: str | None
    streak_length: int | None
    robust_z: float | None
    z_threshold: float
    exhaustion_confirmed: bool = False

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


def core_streak_gate(
    context: dict,
    z_threshold: float = -0.5,
    require_exhaustion: bool | None = None,
) -> CoreSelectionDecision:
    """Gate completed streak evidence for bullish or 2-sided mean-reversion.

    Supports both 'core_mean_reversion' credit spreads and 'debit_reversal' positive-skew debit spreads.
    Optionally enforces two-stage momentum exhaustion confirmation (R_rel > 0 for oversold, R_rel < 0 for overbought).
    """
    direction = context.get("streak_direction")
    length = _positive_int(context.get("streak_length"))
    robust_z = _finite_float(context.get("robust_z"))
    
    route_pref = context.get("strategy_route") or context.get("route")
    if route_pref in {"debit_reversal", "core_mean_reversion", "bearish_reversal_watch"}:
        route = route_pref
    elif context.get("enable_debit_reversal_route"):
        route = "debit_reversal"
    elif direction == "negative":
        route = "core_mean_reversion"
    else:
        route = "bearish_reversal_watch"

    if direction not in {"negative", "positive"}:
        return CoreSelectionDecision(
            False,
            "requires_valid_relative_streak_direction",
            route,
            direction,
            length,
            robust_z,
            z_threshold,
            exhaustion_confirmed=False,
        )

    if length is None or not 1 <= length <= 8:
        return CoreSelectionDecision(
            False,
            "completed_streak_length_outside_1_to_8",
            route,
            direction,
            length,
            robust_z,
            z_threshold,
            exhaustion_confirmed=False,
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
            exhaustion_confirmed=False,
        )
    threshold = abs(float(z_threshold))
    if direction == "negative" and robust_z > -threshold:
        return CoreSelectionDecision(
            False,
            "negative_robust_z_below_threshold",
            route,
            direction,
            length,
            robust_z,
            z_threshold,
            exhaustion_confirmed=False,
        )
    if direction == "positive" and robust_z < threshold:
        return CoreSelectionDecision(
            False,
            "positive_robust_z_below_threshold",
            route,
            direction,
            length,
            robust_z,
            z_threshold,
            exhaustion_confirmed=False,
        )

    rel_return = _finite_float(context.get("relative_return"))
    if direction == "negative":
        is_exhausted = bool(length >= 2 and robust_z <= -threshold and rel_return is not None and rel_return > 0)
    else:
        is_exhausted = bool(length >= 2 and robust_z >= threshold and rel_return is not None and rel_return < 0)

    needs_exhaustion = (
        require_exhaustion
        if require_exhaustion is not None
        else bool(context.get("require_exhaustion", context.get("require_exhaustion_bar", False)))
    )
    if needs_exhaustion:
        if length < 2:
            return CoreSelectionDecision(
                False,
                "streak_length_below_exhaustion_minimum",
                route,
                direction,
                length,
                robust_z,
                z_threshold,
                exhaustion_confirmed=False,
            )
        if direction == "negative" and (rel_return is None or rel_return <= 0):
            return CoreSelectionDecision(
                False,
                "unconfirmed_negative_momentum",
                route,
                direction,
                length,
                robust_z,
                z_threshold,
                exhaustion_confirmed=False,
            )
        if direction == "positive" and (rel_return is None or rel_return >= 0):
            return CoreSelectionDecision(
                False,
                "unconfirmed_positive_momentum",
                route,
                direction,
                length,
                robust_z,
                z_threshold,
                exhaustion_confirmed=False,
            )

    return CoreSelectionDecision(
        True,
        "approved",
        route,
        direction,
        length,
        robust_z,
        z_threshold,
        exhaustion_confirmed=is_exhausted,
    )


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
