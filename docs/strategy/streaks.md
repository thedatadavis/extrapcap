# Relative streak screening

The original inspiration is Klos, Koehl, and Rottke, *Streaks in Daily Returns* (August 2023, [SSRN 3626770](https://ssrn.com/abstract=3626770)). The paper defines a streak as consecutive daily stock outperformance or underperformance relative to the market. Its main formation buckets use completed streak lengths of 2, 3, 4, and 5 trading days; the next-day portfolio goes long negative streaks and short positive streaks.

Extrapcap uses the signal as a tradable-basket screen, not as permission to bypass the rest of the system:

- `signed_streak` is positive for consecutive relative outperformance and negative for consecutive relative underperformance.
- A zero relative return breaks the streak.
- The default screen keeps absolute lengths 2 through 5 and records both directions.
- The implemented bullish core route accepts only negative streaks. Positive streaks are recorded under `bearish_reversal_watch` and deferred until a separately tested defined-risk bearish construction exists.
- Within the negative 2–5-session set, longer streaks rank first, followed by more negative robust Z. Ranking does not increase position size.
- The provider-backed core route also requires robust Z at or below the configured entry threshold (default `-2.0`). A streak can be eligible for the research basket yet still be vetoed before option-chain or LLM calls.
- Eligibility is computed after the latest completed bar and applies to the next session. The screen never uses the next-session return.
- Every symbol receives a decision record with the as-of timestamp, signed length, direction, relative return, acceptance, and rejection reason.

This adaptation differs from the paper in purpose and instrument: the paper studies value-weighted stock portfolios, while Extrapcap uses the screened stocks as underlyings for defined-risk options structures. The options layer still requires liquidity, quote quality, event, Sniper, sleeve-budget, and portfolio-risk approval.

The runnable path is:

```bash
python -m extrapcap.universe.cli --output-dir data/universe
python -m extrapcap.universe.streak_cli \
  --bars data/normalized/bars.csv \
  --greenlist data/universe/greenlist-<timestamp>.csv \
  --output data/universe/tradable-basket.csv
```

The output CSV and `.json` sidecar are pinned artifacts. The sidecar records the source bars, paper reference, policy, and all filter decisions.
