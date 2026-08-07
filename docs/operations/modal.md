# Modal operations

The deployed app is paper-account only. `data_refresh` fetches 756 calendar days of completed Alpaca bars, then `streak_screen` builds the current basket and fits the ticker-specific three-session Bayesian model. A missing provider response, incomplete history, sector, event snapshot, or option quote is an error.

`candidate_review` evaluates every current-day basket opportunity. It does not apply a daily quota: capital, account risk, event gates, DTE rules, and quote quality determine which orders are submitted. Eligible expirations are 0–21 DTE. 0DTE entries are only accepted before the close-positioning cutoff and must be closed the same session; 1DTE entries have a next-session hard exit; all other entries have a three-session/three-DTE hard exit.

Nebius receives an advisory copy of each candidate. Its response is recorded but never substitutes for market data or blocks an otherwise approved paper order.
