# Project charter

Extrapolation Capital is an autonomous **paper** research and execution system. Its first milestone is trustworthy replayability, not live capital deployment.

Non-goals for the MVP: unattended live trading, naked options, unlogged discretionary overrides, and claims about profitability before real historical options data is loaded. A manually invoked live execution path exists behind a separate disabled-by-default switch for controlled future validation.

Assumptions are explicit: the initial offline engine uses supplied bars and transparent option-credit approximations; historical option-chain reconstruction is a research dependency and every resulting report must label the data tier.
