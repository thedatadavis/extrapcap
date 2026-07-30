from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

from ..signals import relative_features


@dataclass
class BayesianReversionModel:
    """Empirical Bayesian probability model for SPY-relative streak reversion.

    Calculates conditional reversion probability:
    P(reversion | streak_length, streak_direction, day_of_week, sector)
    over a 1-year historical window of daily bars with Laplace smoothing.
    """

    counts: dict[tuple[int, str, int, str], tuple[int, int]]  # (length, dir, weekday, sector) -> (reversions, total)
    sector_priors: dict[str, float]                          # sector -> baseline reversion probability
    global_prior: float = 0.50

    @classmethod
    def fit_from_bars(cls, bars: pd.DataFrame, benchmark: pd.Series, lookback_days: int = 252) -> BayesianReversionModel:
        """Fit empirical reversion probabilities using 1 year of relative returns vs SPY."""
        frame = relative_features(bars[bars.symbol != "SPY"], benchmark)
        frame["date"] = pd.to_datetime(frame["date"])

        # Filter to 1-year lookback
        max_date = frame["date"].max()
        cutoff_date = max_date - pd.Timedelta(days=int(lookback_days * 1.5))
        recent = frame[frame["date"] >= cutoff_date].sort_values(["symbol", "date"]).copy()

        # Compute next-day relative return
        recent["next_relative_return"] = recent.groupby("symbol")["relative_return"].shift(-1)
        recent["day_of_week"] = recent["date"].dt.dayofweek  # 0=Mon, ..., 4=Fri

        # Reversion condition:
        # Negative streak: reversion if next_relative_return > 0 (stock outperforms SPY next day)
        # Positive streak: reversion if next_relative_return < 0 (stock underperforms SPY next day)
        recent = recent.dropna(subset=["next_relative_return", "streak_direction", "streak_length"])
        recent = recent[recent["streak_direction"].isin(["positive", "negative"])]

        recent["is_reversion"] = np.where(
            recent["streak_direction"] == "negative",
            recent["next_relative_return"] > 0,
            recent["next_relative_return"] < 0,
        )

        counts: dict[tuple[int, str, int, str], tuple[int, int]] = {}
        sector_counts: dict[str, tuple[int, int]] = {}

        for _, row in recent.iterrows():
            length = int(row["streak_length"])
            direction = str(row["streak_direction"])
            weekday = int(row["day_of_week"])
            sector = str(row.get("sector") or "Unknown")
            is_rev = int(row["is_reversion"])

            key = (length, direction, weekday, sector)
            revs, tot = counts.get(key, (0, 0))
            counts[key] = (revs + is_rev, tot + 1)

            s_revs, s_tot = sector_counts.get(sector, (0, 0))
            sector_counts[sector] = (s_revs + is_rev, s_tot + 1)

        sector_priors = {
            sector: (revs + 1) / (tot + 2) for sector, (revs, tot) in sector_counts.items()
        }
        total_revs = sum(r for r, _ in sector_counts.values())
        total_obs = sum(t for _, t in sector_counts.values())
        global_prior = (total_revs + 1) / (total_obs + 2) if total_obs > 0 else 0.50

        return cls(counts=counts, sector_priors=sector_priors, global_prior=global_prior)

    def predict_reversion_probability(
        self,
        streak_length: int,
        streak_direction: str,
        day_of_week: int,
        sector: str,
    ) -> float:
        """Query conditional reversion probability with Laplace smoothing and prior fallbacks."""
        key = (int(streak_length), str(streak_direction), int(day_of_week), str(sector))
        prior = self.sector_priors.get(str(sector), self.global_prior)

        if key in self.counts:
            revs, tot = self.counts[key]
            alpha = prior * 2.0
            beta = (1.0 - prior) * 2.0
            return (revs + alpha) / (tot + alpha + beta)

        fallback_revs = sum(r for (l, d, _, s), (r, _) in self.counts.items() if l == streak_length and d == streak_direction and s == sector)
        fallback_tot = sum(t for (l, d, _, s), (_, t) in self.counts.items() if l == streak_length and d == streak_direction and s == sector)

        if fallback_tot > 0:
            alpha = prior * 2.0
            beta = (1.0 - prior) * 2.0
            return (fallback_revs + alpha) / (fallback_tot + alpha + beta)

        return prior
