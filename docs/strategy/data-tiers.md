# Options data tiers

Every research run must record one of these tiers:

- `opra`: consolidated OPRA quotes/trades, only when a separately subscribed account provides them; this is outside the current free-data scope.
- `indicative`: Alpaca's delayed/derived feed; useful for development, not interchangeable with OPRA.
- `reconstructed`: derived option prices or chain history created from another source or assumptions.

The free-data path uses Alpaca daily/intraday bars and current indicative option snapshots. The adapter attaches the selected snapshot tier to each chain payload. Reports must not compare tiers without labeling the change.

Historical trades are intentionally out of scope for the free-data MVP: the current account returned HTTP 403 (`OPRA agreement is not signed`) even though the CLI records the requested feed separately from the provider-resolved tier. No historical option trades are claimed; current indicative snapshots and modeled/reconstructed research remain clearly labeled alternatives.

The simulator applies explicit per-leg slippage, commission, bid/ask quality, expiry intrinsic value, and conservative early-assignment exposure flags. It does not claim to reproduce historical fills until timestamped chain quotes are ingested.

`backtest.chain_engine` is the chain-backed path. It requires `data_tier` on every observation and refuses reconstructed observations unless explicitly opted in.
