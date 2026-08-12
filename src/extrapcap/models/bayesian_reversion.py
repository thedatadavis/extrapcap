"""Ticker-specific empirical Bayesian reversion model."""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from ..signals import relative_features


MIN_HISTORY_BARS = 30
MIN_LABELED_OBSERVATIONS = 10
PRIOR_STRENGTH = 20.0
HORIZON_SESSIONS = 3


def streak_bucket(length: int) -> int:
    """Keep sparse long streaks statistically usable without erasing ticker identity."""
    return min(max(int(length), 1), 5)


@dataclass(frozen=True)
class BayesianEvidence:
    symbol: str
    direction: str
    streak_length: int
    day_of_week: int
    probability: float
    cell_reversions: int
    cell_observations: int
    ticker_reversions: int
    ticker_observations: int


@dataclass
class BayesianReversionModel:
    """P(reversion within three sessions | one ticker's observed history)."""

    counts: dict[tuple[str, str, int, int], tuple[int, int]]
    ticker_priors: dict[tuple[str, str], tuple[int, int]]

    @classmethod
    def fit_from_bars(
        cls,
        bars: pd.DataFrame,
        benchmark: pd.Series,
        *,
        lookback_days: int = 756,
        min_history_bars: int = MIN_HISTORY_BARS,
        min_labeled_observations: int = MIN_LABELED_OBSERVATIONS,
    ) -> "BayesianReversionModel":
        required = {"symbol", "date", "close"}
        missing = required - set(bars.columns)
        if missing:
            raise ValueError(f"Bayesian bars missing required columns: {sorted(missing)}")
        if "SPY" not in set(bars["symbol"].astype(str).str.upper()):
            raise ValueError("Bayesian training requires SPY bars")

        frame = bars.copy()
        frame["symbol"] = frame["symbol"].astype(str).str.upper()
        frame["date"] = pd.to_datetime(frame["date"], utc=True)
        frame["close"] = pd.to_numeric(frame["close"], errors="raise")
        frame = frame.sort_values(["symbol", "date"])
        benchmark = benchmark.copy()
        benchmark.index = pd.to_datetime(benchmark.index, utc=True)
        benchmark = pd.to_numeric(benchmark, errors="raise")
        features = relative_features(frame[frame["symbol"] != "SPY"], benchmark)
        if features.empty:
            return cls(counts={}, ticker_priors={})

        cutoff = features["date"].max() - pd.Timedelta(days=lookback_days)
        features = features[features["date"] >= cutoff].sort_values(["symbol", "date"])

        # Discard tickers that do not meet minimum history bars
        coverage = features.groupby("symbol")["date"].nunique()
        valid_symbols = set(coverage[coverage >= min_history_bars].index)
        features = features[features["symbol"].isin(valid_symbols)]
        if features.empty:
            return cls(counts={}, ticker_priors={})

        grouped = features.groupby("symbol", sort=False)
        future_returns = pd.concat(
            [grouped["relative_return"].shift(-offset).rename(f"future_{offset}") for offset in range(1, HORIZON_SESSIONS + 1)],
            axis=1,
        )
        labeled = features.join(future_returns)
        future_columns = [f"future_{offset}" for offset in range(1, HORIZON_SESSIONS + 1)]
        labeled = labeled.dropna(subset=future_columns)
        labeled["day_of_week"] = labeled["date"].dt.dayofweek
        labeled["is_reversion"] = np.where(
            labeled["streak_direction"] == "negative",
            labeled[future_columns].cumsum(axis=1).gt(0).any(axis=1),
            labeled[future_columns].cumsum(axis=1).lt(0).any(axis=1),
        )
        labeled = labeled[labeled["streak_direction"].isin(["negative", "positive"])]

        # Discard tickers with fewer than min_labeled_observations
        outcome_counts = labeled.groupby("symbol").size()
        valid_outcomes = set(outcome_counts[outcome_counts >= min_labeled_observations].index)
        labeled = labeled[labeled["symbol"].isin(valid_outcomes)]

        counts: dict[tuple[str, str, int, int], tuple[int, int]] = {}
        ticker_priors: dict[tuple[str, str], tuple[int, int]] = {}

        for row in labeled.itertuples(index=False):
            symbol = str(row.symbol).upper()
            direction = str(row.streak_direction)
            outcome = int(bool(row.is_reversion))
            prior_key = (symbol, direction)
            prior_reversions, prior_total = ticker_priors.get(prior_key, (0, 0))
            ticker_priors[prior_key] = (prior_reversions + outcome, prior_total + 1)
            cell_key = (symbol, direction, streak_bucket(row.streak_length), int(row.day_of_week))
            cell_reversions, cell_total = counts.get(cell_key, (0, 0))
            counts[cell_key] = (cell_reversions + outcome, cell_total + 1)

        return cls(counts=counts, ticker_priors=ticker_priors)

    def predict_reversion_probability(
        self,
        *,
        symbol: str,
        streak_length: int,
        streak_direction: str,
        day_of_week: int,
    ) -> float:
        return self.predict_evidence(
            symbol=symbol,
            streak_length=streak_length,
            streak_direction=streak_direction,
            day_of_week=day_of_week,
        ).probability

    def predict_evidence(
        self,
        *,
        symbol: str,
        streak_length: int,
        streak_direction: str,
        day_of_week: int,
    ) -> BayesianEvidence:
        symbol = str(symbol).strip().upper()
        direction = str(streak_direction).strip().lower()
        prior_key = (symbol, direction)

        if prior_key not in self.ticker_priors:
            raise KeyError(f"Bayesian evidence unavailable for {symbol} {direction}: ticker lacks required historical observations")

        ticker_reversions, ticker_observations = self.ticker_priors[prior_key]
        if ticker_observations < MIN_LABELED_OBSERVATIONS:
            raise ValueError(f"Bayesian evidence insufficient for {symbol} {direction}: {ticker_observations} < {MIN_LABELED_OBSERVATIONS}")

        cell_key = (symbol, direction, streak_bucket(streak_length), int(day_of_week))
        cell_reversions, cell_observations = self.counts.get(cell_key, (0, 0))

        prior = (ticker_reversions + 1.0) / (ticker_observations + 2.0)
        alpha = prior * PRIOR_STRENGTH
        beta = (1.0 - prior) * PRIOR_STRENGTH
        probability = (cell_reversions + alpha) / (cell_observations + alpha + beta)
        if not math.isfinite(probability):
            raise ValueError(f"Bayesian probability calculation invalid for {symbol}")

        return BayesianEvidence(
            symbol=symbol,
            direction=direction,
            streak_length=int(streak_length),
            day_of_week=int(day_of_week),
            probability=float(probability),
            cell_reversions=cell_reversions,
            cell_observations=cell_observations,
            ticker_reversions=ticker_reversions,
            ticker_observations=ticker_observations,
        )

