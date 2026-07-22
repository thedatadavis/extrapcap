from __future__ import annotations

import numpy as np


def summarize_returns(returns, *, periods_per_year: int = 252, elapsed_years: float | None = None) -> dict[str, float | None]:
    """Summarize sequential risk-unit returns without hiding empty/partial data.

    ``returns`` are intentionally treated as a sequence of observations, not as
    a portfolio equity curve. Callers should pass ``elapsed_years`` only when
    the observation interval supports an annualized CAGR. This keeps proxy
    backtests from presenting per-trade statistics as investable performance.
    """
    values = np.asarray(list(returns), dtype=float)
    if values.size == 0:
        return {
            "trades": 0.0,
            "win_rate": 0.0,
            "expectancy": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "total_return": 0.0,
            "sharpe_annualized": 0.0,
            "sortino_annualized": 0.0,
            "cagr": None,
            "tail_loss_p05": 0.0,
            "worst_return": 0.0,
            "skewness": 0.0,
            "quantiles": {"p05": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0, "p95": 0.0},
        }
    equity = np.cumprod(1 + values)
    drawdown = equity / np.maximum.accumulate(equity) - 1
    wins = values[values > 0]
    losses = values[values < 0]
    volatility = values.std(ddof=1) if values.size > 1 else 0.0
    downside_deviation = np.sqrt(np.mean(np.minimum(values, 0.0) ** 2))
    population_volatility = values.std()
    skewness = float(np.mean(((values - values.mean()) / population_volatility) ** 3)) if population_volatility else 0.0
    cagr = None
    if elapsed_years is not None and elapsed_years > 0 and equity[-1] > 0:
        cagr = float(equity[-1] ** (1 / elapsed_years) - 1)
    return {
        "trades": float(values.size),
        "win_rate": float((values > 0).mean()),
        "expectancy": float(values.mean()),
        "profit_factor": float(wins.sum() / abs(losses.sum())) if losses.size else None,
        "max_drawdown": float(drawdown.min()),
        "total_return": float(equity[-1] - 1),
        "sharpe_annualized": float(values.mean() / volatility * np.sqrt(periods_per_year)) if volatility else 0.0,
        "sortino_annualized": float(values.mean() / downside_deviation * np.sqrt(periods_per_year)) if downside_deviation else 0.0,
        "cagr": cagr,
        "tail_loss_p05": float(np.quantile(values, 0.05)),
        "worst_return": float(values.min()),
        "skewness": skewness,
        "quantiles": {
            "p05": float(np.quantile(values, 0.05)),
            "p25": float(np.quantile(values, 0.25)),
            "p50": float(np.quantile(values, 0.50)),
            "p75": float(np.quantile(values, 0.75)),
            "p95": float(np.quantile(values, 0.95)),
        },
    }
