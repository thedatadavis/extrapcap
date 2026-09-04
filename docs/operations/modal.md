# Modal operations

The deployed app is paper-account only. `data_refresh` fetches 90 calendar days of completed Alpaca bars, writes them as immutable daily Parquet partitions to the shared `extrapcap-state` Modal Volume, then `streak_screen` reloads those partitions to build the current basket and fit the ticker-specific three-session Bayesian model. D1 remains the transactional control plane for runs, events, the current basket, orders, positions, and account history. A missing provider response, incomplete history, sector, event snapshot, or option quote is an error.

Each session date is written once under `/data/market_bars/date=YYYY-MM-DD/bars.parquet`. The writer commits the Volume after changes and purges partitions older than 365 days. If a historical partition must be corrected, remove that specific partition from the Volume and rerun the refresh for its session date; normal refreshes never rewrite an existing partition.

`candidate_review` evaluates every current-day basket opportunity. It does not apply a daily quota: capital, account risk, event gates, DTE rules, and quote quality determine which orders are submitted. Eligible expirations are 0–21 DTE. 0DTE entries are only accepted before the close-positioning cutoff and must be closed the same session; 1DTE entries have a next-session hard exit; all other entries have a three-session/three-DTE hard exit.

Nebius receives an advisory copy of each candidate. Its response is recorded but never substitutes for market data or blocks an otherwise approved paper order.
