# Strategy variants

Variant A (`baseline`) uses a closer-to-the-money defined-risk put spread and a selective robust-Z gate. Variant B (`improved`) moves the short strike farther OTM and accepts lower credit for a higher modeled probability of profit. The comparison must report expectancy, drawdown, tail outcomes, and return on capital—not win rate alone.

## Relative-streak basket screen

The screening layer follows the original paper's operational definition: compare each stock's daily return with the market return, then require consecutive relative outperformance or underperformance over a completed 2-, 3-, 4-, 5-, 6-, or 7-day run. The `universe.streak_cli` screen records signed streak length, direction, as-of timestamp, and rejection reason for every Greenlist symbol. It does not use the formation day's future return. Negative streaks are the primary core mean-reversion candidates; positive streaks are retained for continuation/Crash Protocol analysis rather than silently discarded.

This is a basket-selection input, not a standalone trade rule. Robust-Z, Sniper probability, liquidity, event, and portfolio-risk gates still apply downstream.

The Sniper training CLI builds next-observation labels from time-ordered features, trains CatBoost on the earliest split, and reports calibration on validation and test splits. The deterministic probability boundary remains available only for fixture-sized offline smoke tests; paper automation must pass a trained, versioned model into the backtest and execution path.
