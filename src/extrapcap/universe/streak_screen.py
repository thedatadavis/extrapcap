from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from ..signals import relative_features


@dataclass(frozen=True)
class StreakPolicy:
    """Completed-close relative-streak screen inspired by SSRN 3626770."""

    min_length: int = 1
    max_length: int = 8
    directions: tuple[str, ...] = ("negative", "positive")
    require_exhaustion: bool = False

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
    frame["prev_streak_length"] = frame.groupby("symbol")["streak_length"].shift(1)
    frame["prev_streak_direction"] = frame.groupby("symbol")["streak_direction"].shift(1)
    frame["prev_signed_streak"] = frame.groupby("symbol")["signed_streak"].shift(1)
    frame["prev_robust_z"] = frame.groupby("symbol")["robust_z"].shift(1)

    latest = frame.sort_values(["symbol", "date"]).groupby("symbol", as_index=False).tail(1)
    latest = latest[latest["symbol"].ne("SPY")].copy()

    def _is_exhausted(row) -> bool:
        prev_dir = row["prev_streak_direction"] if pd.notna(row["prev_streak_direction"]) else None
        prev_len = row["prev_streak_length"] if pd.notna(row["prev_streak_length"]) else 0
        rel_ret = row["relative_return"] if pd.notna(row["relative_return"]) else None
        if prev_dir == "negative" and prev_len >= 2 and rel_ret is not None and rel_ret > 0:
            return True
        if prev_dir == "positive" and prev_len >= 2 and rel_ret is not None and rel_ret < 0:
            return True
        curr_len = row["streak_length"] if pd.notna(row["streak_length"]) else 0
        curr_dir = row["streak_direction"] if pd.notna(row["streak_direction"]) else None
        if curr_len >= 2 and rel_ret is not None:
            if curr_dir == "negative" and rel_ret > 0:
                return True
            if curr_dir == "positive" and rel_ret < 0:
                return True
        return False

    latest["exhaustion_confirmed"] = latest.apply(_is_exhausted, axis=1)

    if policy.require_exhaustion:
        def _is_eligible_exhausted(row) -> bool:
            if not row["exhaustion_confirmed"]:
                return False
            prev_dir = row["prev_streak_direction"] if pd.notna(row["prev_streak_direction"]) else None
            prev_len = row["prev_streak_length"] if pd.notna(row["prev_streak_length"]) else 0
            if prev_dir in policy.directions and policy.min_length <= prev_len <= policy.max_length:
                return True
            curr_dir = row["streak_direction"]
            curr_len = row["streak_length"]
            if curr_dir in policy.directions and policy.min_length <= curr_len <= policy.max_length:
                return True
            return False

        latest["streak_eligible"] = latest.apply(_is_eligible_exhausted, axis=1)
    else:
        latest["streak_eligible"] = latest["streak_length"].between(
            policy.min_length, policy.max_length
        ) & latest["streak_direction"].isin(policy.directions)

    decisions = []
    for row in latest.itertuples():
        reasons = []
        eff_len = row.streak_length
        eff_dir = row.streak_direction
        if policy.require_exhaustion and row.exhaustion_confirmed:
            if pd.notna(row.prev_streak_direction) and row.prev_streak_direction in policy.directions:
                eff_len = int(row.prev_streak_length)
                eff_dir = str(row.prev_streak_direction)
        if eff_len < policy.min_length:
            reasons.append("streak_too_short")
        if eff_len > policy.max_length:
            reasons.append("streak_too_long")
        if eff_dir not in policy.directions:
            reasons.append("streak_direction_excluded")
        if policy.require_exhaustion and not row.exhaustion_confirmed:
            reasons.append("unconfirmed_momentum_no_exhaustion")
        decisions.append(
            {
                "ticker": row.symbol,
                "as_of": pd.Timestamp(row.date).isoformat(),
                "signed_streak": int(row.signed_streak),
                "streak_length": int(eff_len),
                "streak_direction": eff_dir,
                "relative_return": float(row.relative_return)
                if pd.notna(row.relative_return)
                else None,
                "exhaustion_confirmed": bool(row.exhaustion_confirmed),
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
        "accepted_rows": len(selected),
        "decision_rows": len(decisions),
        "decisions": decisions,
    }
    if coverage is not None:
        metadata["coverage"] = coverage
    target.with_suffix(target.suffix + ".json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return target


def filter_tradable_basket(
    greenlist: list[dict], bars_df: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Filter Greenlist entries using completed market bars only.

    This is an execution input, so missing market data must fail closed. The
    previous ticker-hash fallback made every Greenlist name look tradable even
    when the persisted bars were unavailable.
    """
    if bars_df is None or bars_df.empty:
        raise RuntimeError("streak screen requires completed market bars")
    required = {"date", "symbol", "close"}
    missing = required - set(bars_df.columns)
    if missing:
        raise ValueError(f"streak bars missing required columns: {sorted(missing)}")

    bars = bars_df.copy()
    bars["symbol"] = bars["symbol"].astype(str).str.upper()
    bars["date"] = pd.to_datetime(bars["date"], utc=True)
    spy_df = bars[bars["symbol"] == "SPY"].sort_values("date")
    if spy_df.empty:
        raise RuntimeError("streak screen requires SPY benchmark bars")

    spy_series = spy_df.set_index("date")["close"]
    candidate_symbols = {
        str(item.get("ticker", "")).strip().upper() for item in greenlist if item.get("ticker")
    }
    screened_df, _ = screen_streaks(
        bars,
        spy_series,
        candidate_symbols=candidate_symbols,
    )
    sector_map = {
        str(item.get("ticker", "")).strip().upper(): str(item.get("sector") or "").strip()
        for item in greenlist
    }
    missing_sectors = sorted(ticker for ticker in candidate_symbols if not sector_map.get(ticker))
    if missing_sectors:
        raise RuntimeError("streak screen missing sector metadata: " + ", ".join(missing_sectors))
    rows = []
    for row in screened_df.itertuples():
        ticker = row.symbol
        record = {
            "date": pd.Timestamp(row.date).isoformat(),
            "symbol": ticker,
            "sector": sector_map[ticker],
            "signed_streak": int(row.signed_streak),
            "streak_length": int(row.streak_length),
            "streak_depth": int(row.streak_length),
            "streak_direction": str(row.streak_direction),
            "robust_z": float(row.robust_z) if pd.notna(row.robust_z) else None,
            "dollar_volume": float(row.dollar_volume) if pd.notna(row.dollar_volume) else None,
            "stock_return": float(row.stock_return) if pd.notna(row.stock_return) else None,
            "benchmark_return": float(row.benchmark_return)
            if pd.notna(row.benchmark_return)
            else None,
            "relative_return": float(row.relative_return)
            if pd.notna(row.relative_return)
            else None,
            "exhaustion_confirmed": bool(getattr(row, "exhaustion_confirmed", False)),
            "underlying_price": float(row.close) if pd.notna(row.close) else None,
        }
        rows.append(record)
    return pd.DataFrame(rows)
