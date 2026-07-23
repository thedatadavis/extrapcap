from __future__ import annotations

from dataclasses import asdict, dataclass
import math

import numpy as np


@dataclass(frozen=True)
class ThresholdResult:
    threshold: float
    observations: int
    positives: int
    precision: float
    proxy_expectancy: float
    proxy_expectancy_lcb95: float
    proxy_max_drawdown: float

    def as_dict(self) -> dict:
        return asdict(self)


def _max_drawdown(values: np.ndarray) -> float:
    if values.size == 0:
        return 0.0
    curve = np.cumsum(values)
    peaks = np.maximum.accumulate(np.concatenate(([0.0], curve)))
    drawdowns = np.concatenate(([0.0], curve)) - peaks
    return float(drawdowns.min())


def evaluate_threshold(
    probabilities,
    labels,
    proxy_returns,
    threshold: float,
) -> ThresholdResult:
    probabilities = np.asarray(probabilities, dtype=float)
    labels = np.asarray(labels, dtype=int)
    proxy_returns = np.asarray(proxy_returns, dtype=float)
    if not (len(probabilities) == len(labels) == len(proxy_returns)):
        raise ValueError("probabilities, labels, and proxy_returns must align")
    selected = proxy_returns[probabilities >= threshold]
    positives = labels[probabilities >= threshold]
    observations = int(selected.size)
    if observations == 0:
        expectancy = lcb = precision = 0.0
    else:
        expectancy = float(selected.mean())
        standard_error = float(selected.std(ddof=1) / math.sqrt(observations)) if observations > 1 else 0.0
        lcb = expectancy - 1.96 * standard_error
        precision = float(positives.mean())
    return ThresholdResult(
        threshold=float(threshold),
        observations=observations,
        positives=int(positives.sum()),
        precision=precision,
        proxy_expectancy=expectancy,
        proxy_expectancy_lcb95=lcb,
        proxy_max_drawdown=_max_drawdown(selected),
    )


def sweep_thresholds(
    probabilities,
    labels,
    proxy_returns,
    thresholds,
) -> list[ThresholdResult]:
    return [
        evaluate_threshold(probabilities, labels, proxy_returns, threshold)
        for threshold in thresholds
    ]


def select_threshold(
    results: list[ThresholdResult],
    *,
    minimum_observations: int = 50,
    minimum_expectancy_lcb95: float = 0.0,
    maximum_drawdown: float = -0.10,
) -> ThresholdResult:
    eligible = [
        result
        for result in results
        if result.observations >= minimum_observations
        and result.proxy_expectancy_lcb95 >= minimum_expectancy_lcb95
        and result.proxy_max_drawdown >= maximum_drawdown
    ]
    if not eligible:
        raise ValueError("no threshold satisfies the baseline constraints")
    return max(
        eligible,
        key=lambda result: (
            result.proxy_expectancy_lcb95,
            result.precision,
            -result.threshold,
        ),
    )
