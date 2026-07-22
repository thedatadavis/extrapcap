# ADR 0002: reproducible Greenlist snapshots

## Decision

Use `bootstrapital/stockstreaks-registry` `data/active_tickers.csv` as the canonical starting universe. Each refresh writes a timestamped accepted CSV and JSON filter-decision log. Backtests reference a pinned snapshot, not a live URL.

## Rationale

Universe drift and survivorship bias can invalidate comparisons. Timestamped snapshots make the source and filtering decisions replayable.

## Consequences

The scheduled refresh workflow commits new snapshots. Historical reports must name the snapshot and explicitly describe the remaining survivorship and options-availability limitations.
