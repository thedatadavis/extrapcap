from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd


def robust_zscore(series: pd.Series, window: int = 20) -> pd.Series:
    """Rolling median/MAD z-score; zero-MAD windows are treated as neutral."""
    median = series.rolling(window).median()
    mad = series.rolling(window).apply(lambda x: np.median(np.abs(x - np.median(x))), raw=True)
    scale = 1.4826 * mad
    return (series - median).div(scale.replace(0, np.nan)).fillna(0.0)


def relative_features(bars: pd.DataFrame, benchmark: pd.Series, window: int = 20) -> pd.DataFrame:
    required = {"symbol", "date", "close"}
    missing = required - set(bars.columns)
    if missing:
        raise ValueError(f"bars missing required columns: {sorted(missing)}")
    frame = bars.sort_values(["symbol", "date"]).copy()
    frame["stock_return"] = frame.groupby("symbol")["close"].pct_change()
    bench = benchmark.sort_index().pct_change().rename("benchmark_return")
    frame = frame.join(bench, on="date")
    frame["relative_return"] = frame["stock_return"] - frame["benchmark_return"]
    frame["robust_z"] = frame.groupby("symbol")["relative_return"].transform(
        lambda s: robust_zscore(s, window)
    )
    frame["streak_depth"] = frame.groupby("symbol")["relative_return"].transform(
        lambda s: s.lt(0).groupby(s.ge(0).cumsum()).cumsum()
    )
    def signed_streak(series: pd.Series) -> pd.Series:
        values = series.to_numpy(dtype=float)
        result = np.zeros(len(values), dtype=int)
        for index, value in enumerate(values):
            if not np.isfinite(value) or value == 0:
                continue
            sign = 1 if value > 0 else -1
            previous = result[index - 1] if index else 0
            result[index] = sign * (abs(previous) + 1 if np.sign(previous) == sign else 1)
        return pd.Series(result, index=series.index, dtype="int64")

    frame["signed_streak"] = frame.groupby("symbol")["relative_return"].transform(signed_streak)
    frame["streak_length"] = frame["signed_streak"].abs()
    frame["streak_direction"] = np.select(
        [frame["signed_streak"] < 0, frame["signed_streak"] > 0],
        ["negative", "positive"],
        default="flat",
    )
    frame["turn_of_month"] = frame["date"].dt.day.le(3) | frame["date"].dt.day.ge(28)
    # Additive contextual features for future retraining. The first versioned
    # artifact uses SNIPER_FEATURES below, so these columns do not silently
    # change the production model contract.
    frame["seasonality_sin"] = np.sin(2 * np.pi * frame["date"].dt.dayofyear / 365.25)
    frame["seasonality_cos"] = np.cos(2 * np.pi * frame["date"].dt.dayofyear / 365.25)
    frame["volatility_context"] = frame.groupby("symbol")["stock_return"].transform(
        lambda s: s.rolling(window, min_periods=2).std() * np.sqrt(252)
    )
    benchmark_regime = bench.rolling(window, min_periods=2).mean()
    frame["market_regime"] = frame["date"].map(benchmark_regime)
    if "volume" in frame:
        frame["dollar_volume"] = frame["close"].abs() * frame["volume"]
        frame["liquidity_context"] = frame.groupby("symbol")["dollar_volume"].transform(
            lambda s: s.rolling(window, min_periods=2).median()
        )
    else:
        frame["dollar_volume"] = np.nan
        frame["liquidity_context"] = np.nan
    if {"high", "low"}.issubset(frame.columns):
        frame["intraday_range_pct"] = (frame["high"] - frame["low"]).div(frame["close"].abs())
    else:
        frame["intraday_range_pct"] = np.nan
    frame["ticker_identity"] = frame["symbol"].map(
        lambda value: int(hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:8], 16)
    )
    return frame


SNIPER_FEATURES = [
    "relative_return",
    "robust_z",
    "streak_depth",
    "stock_return",
    "benchmark_return",
    "turn_of_month",
]


def sniper_dataset(features: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Build next-observation labels without using future values as features."""
    frame = features.sort_values(["symbol", "date"]).copy()
    frame["next_relative_return"] = frame.groupby("symbol")["relative_return"].shift(-1)
    frame = frame.dropna(subset=SNIPER_FEATURES + ["next_relative_return"])
    x = frame[SNIPER_FEATURES].astype(float)
    y = frame["next_relative_return"].ge(0).astype(int)
    return x, y
