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
- complete-session daily-bar enforcement and formation-value reconciliation
- free expected-earnings blackout snapshot with fail-closed coverage checks
- broker-clock, persistent order-count/cooldown, and completed-signal idempotency gates
- options buying-power/approval, quote-quality, ticker, and sector risk gates
- provider-backed 1-minute intraday scan bursts with dynamic expiration windows
- empirical execution-gate evaluation: measure time-of-day spreads, depth, slippage, fill quality, and outcomes, then replace hard-coded gates with data-driven rules and A/B/C ticker classes that can carry different execution hurdles
- scheduled normalized-bar refresh and versioned Sniper artifact publication
- Nebius structured review and immutable daily ledger commits
- credential injection from the operator's secret manager (keys were intentionally not persisted by the agent)

## Research backlog

- multi-period free indicative option history if a freely available source becomes accessible; otherwise retain modeled/reconstructed chain replay
- overlapping-position, margin, and portfolio-equity accounting
- persistent low-latency runner and fill-quality studies beyond the scheduled indicative-quote exit manager; the backtest now models the operating-window and duplicate/cooldown rules available to that runner
- broader structural-news data ingestion and regime decomposition
- regime case studies
- safe contextual-bandit recommendations
- sector metadata ingestion and multi-sector real-data replay
- realistic overlapping option marks and partial-fill path
