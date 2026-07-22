# Roadmap

## MVP

- deterministic signal and backtest engine
- transparent metrics and versioned CatBoost Sniper interface
- baseline/improved defined-risk variants
- funded asymmetric ledger
- audit log schema and paper-only provider adapters
- CI and replay smoke tests

## Production hardening

- stockstreaks-registry snapshot ingestion
- Alpaca bars/options contract snapshots and option-chain data quality checks
- historical option chains and realistic fills
- CatBoost calibration and OOS reporting
- Alpaca reconciliation, idempotency, and scheduled paper workflows
- provider-backed live cycle over recent bars, option contracts, and chain snapshots
- provider-backed 1-minute intraday scan bursts with dynamic expiration windows
- scheduled normalized-bar refresh and versioned Sniper artifact publication
- Nebius structured review and immutable daily ledger commits
- credential injection from the operator's secret manager (keys were intentionally not persisted by the agent)

## Research backlog

- multi-period free indicative option history if a freely available source becomes accessible; otherwise retain modeled/reconstructed chain replay
- overlapping-position, margin, and portfolio-equity accounting
- persistent low-latency runner and fill-quality studies beyond the scheduled indicative-quote exit manager; the backtest now models the operating-window and duplicate/cooldown rules available to that runner
- news/structural-event data feed and regime decomposition
- regime case studies
- safe contextual-bandit recommendations
