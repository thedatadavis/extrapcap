from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

import pandas as pd

from ..signals import relative_features


@dataclass(frozen=True)
class StreakPolicy:
    """Completed-close relative-streak screen inspired by SSRN 3626770."""

    min_length: int = 2
    max_length: int = 5
    directions: tuple[str, ...] = ("negative", "positive")

    def __post_init__(self) -> None:
        if self.min_length < 1 or self.max_length < self.min_length:
            raise ValueError("streak length bounds are invalid")
        if not set(self.directions).issubset({"negative", "positive"}):
            raise ValueError("streak directions must be negative or positive")


def screen_streaks(
    bars: pd.DataFrame,
    benchmark: pd.Series,
    candidate_symbols: set[str] | None = None,
    policy: StreakPolicy | None = None,
) -> tuple[pd.DataFrame, list[dict]]:
    """Select symbols whose latest *completed* relative streak is tradable.

    The output is intentionally a next-session screen: the last observed bar
    determines eligibility, and no same-bar/future return is consulted.
    """
    policy = policy or StreakPolicy()
    frame = relative_features(bars, benchmark)
    if candidate_symbols is not None:
        allowed = {symbol.upper() for symbol in candidate_symbols}
        frame = frame[frame["symbol"].str.upper().isin(allowed | {"SPY"})]
    latest = frame.sort_values(["symbol", "date"]).groupby("symbol", as_index=False).tail(1)
    latest = latest[latest["symbol"].ne("SPY")].copy()
    latest["streak_eligible"] = (
        latest["streak_length"].between(policy.min_length, policy.max_length)
        & latest["streak_direction"].isin(policy.directions)
    )
    decisions = []
    for row in latest.itertuples():
        reasons = []
        if row.streak_length < policy.min_length:
            reasons.append("streak_too_short")
        if row.streak_length > policy.max_length:
            reasons.append("streak_too_long")
        if row.streak_direction not in policy.directions:
            reasons.append("streak_direction_excluded")
        decisions.append(
            {
                "ticker": row.symbol,
                "as_of": pd.Timestamp(row.date).isoformat(),
                "signed_streak": int(row.signed_streak),
                "streak_length": int(row.streak_length),
                "streak_direction": row.streak_direction,
                "relative_return": float(row.relative_return) if pd.notna(row.relative_return) else None,
                "accepted": bool(row.streak_eligible),
                "reasons": reasons,
            }
        )
    return latest[latest["streak_eligible"]].reset_index(drop=True), decisions


def write_streak_screen(
    selected: pd.DataFrame,
    decisions: list[dict],
    output: str | Path,
    policy: StreakPolicy,
    source_bars: str,
    coverage: dict | None = None,
) -> Path:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    selected.to_csv(target, index=False)
    metadata = {
        "kind": "relative_streak_screen",
        "source_paper": "SSRN 3626770",
        "source_bars": source_bars,
        "formation_rule": "latest completed bar; eligible for next session",
        "policy": asdict(policy),
        "accepted_rows": int(len(selected)),
        "decision_rows": len(decisions),
        "decisions": decisions,
    }
    if coverage is not None:
        metadata["coverage"] = coverage
    target.with_suffix(target.suffix + ".json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return target
