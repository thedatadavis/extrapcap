# Architecture

Data adapters produce versioned bars, option chains, news, and account snapshots. Signals produce features. Strategy variants produce defined-risk candidates. Risk controls approve or reject candidates. The LLM is a bounded qualitative reviewer after hard controls. Execution receives only approved candidates and writes every request/fill to the Git-backed ledger.

The first external data contract is the `active_tickers.csv` snapshot from `bootstrapital/stockstreaks-registry`. `extrapcap.universe.greenlist.refresh_greenlist` stores a timestamped accepted CSV and a JSON decision log. Market bars are normalized into the common `date/symbol/open/high/low/close/volume/vwap` schema.

The backtest's operating mode is behavioral when intraday observations exist: `end_of_day` admits one decision per supplied observation, `hybrid` admits only close-positioning entries, and `intraday_loop` admits open/close-window entries with session duplicate and cooldown gates. This keeps mode comparisons honest instead of labeling identical daily behavior as intraday evidence.

Daily ledger files are append-only JSONL grouped by category and trading date. `ledger_cli` stages only the requested day and commits it with a deterministic message; `playback_cli` reconstructs the event timeline without contacting a provider.

Greenlist snapshots are intentionally versioned under `data/universe`; they are not ignored because the source snapshot and filter decisions are part of research reproducibility.

Provider adapters expose both single-page and `*_all` methods. Backfill workflows must use the paginated variants and record the resulting page count; silently accepting a `next_page_token` would create an incomplete research dataset.

The chain-backed paper coordinator accepts only resolved option legs. Its ordering is: hard event gate → portfolio risk gate → Sniper bucket → Nebius qualitative review → idempotent Alpaca submission → audit ledger.

Paper-submit requires a versioned CatBoost artifact and a feature vector; manual probability overrides are fixture-only. After a non-dry submission, the coordinator records Alpaca account, open-order, and position reconciliation in the same trading-day ledger.

`ExecutionMonitor` observes the resulting order and writes fill/account/position snapshots, including a bounded timeout exception, so a submitted order is never treated as filled merely because the POST succeeded.

Open defined-risk credit positions use the provider-agnostic `position_manager` contract for event-driven management. It evaluates current spread debit against profit-target, stop-loss, and time-stop rules, then reverses the opening legs into an idempotent close envelope. The manager is intentionally separate from quote retrieval: free indicative snapshots or a future runner can supply marks without granting the LLM authority to override hard exits.

`manage_live_cli` is the provider-backed bridge: it matches registry entries only when both option legs are currently held, parses the OCC symbols, requests the current indicative quotes for the exact expiration, and records a skip on missing metadata/quotes. It defaults to `dry-run`; `paper-submit` is an explicit mode and remains paper-endpoint-only.

When `EXTRAPCAP_NEWS_LLM=true`, dated event rows with headlines are also sent to Nebius for a structured `noise_or_opinion` versus `structural_risk` classification. Local hard-term matches and dated structural flags veto before the model; missing keys, malformed JSON, invalid categories, or model disagreement fail closed to a structural-risk veto. The LLM cannot clear a hard event rule.

Dry-run and submitted order identities share deterministic IDs but have distinct registry statuses. Dry-run observations remain replayable without being treated as evidence that an order reached Alpaca, and therefore cannot block a later explicitly approved paper submission.

The core domain modules are pure Python where possible so backtests and paper runs share decision logic. Provider adapters are side-effecting boundaries and default to dry-run.
