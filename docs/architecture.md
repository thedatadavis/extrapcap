# Architecture

Data adapters produce versioned bars, option chains, news, and account snapshots. Signals produce features. Strategy variants produce defined-risk candidates. Risk controls approve or reject candidates. The LLM is a bounded qualitative reviewer after hard controls. Execution receives only approved candidates and writes every request/fill to the Git-backed ledger.

Daily bars are complete-session data only. Before 16:15 America/New_York, the current session is excluded; after that delay it may become the next completed formation bar. Candidate review verifies the basket formation date and signal values against a fresh provider recomputation, so a stale or modified artifact cannot supply the executable Z-score.

The first external data contract is the `active_tickers.csv` snapshot from `bootstrapital/stockstreaks-registry`. `extrapcap.universe.greenlist.refresh_greenlist` stores a timestamped accepted CSV and a JSON decision log. Market bars are normalized into the common `date/symbol/open/high/low/close/volume/vwap` schema.

The backtest's operating mode is behavioral when intraday observations exist: `end_of_day` admits one decision per supplied observation, `hybrid` admits only close-positioning entries, and `intraday_loop` admits open/close-window entries with session duplicate and cooldown gates. This keeps mode comparisons honest instead of labeling identical daily behavior as intraday evidence.

Daily ledger files are append-only JSONL grouped by category and trading date. `ledger_cli` stages only the requested day and commits it with a deterministic message; `playback_cli` reconstructs the event timeline without contacting a provider.

Greenlist snapshots are intentionally versioned under `data/universe`; they are not ignored because the source snapshot and filter decisions are part of research reproducibility.

Provider adapters expose both single-page and `*_all` methods. Backfill workflows must use the paginated variants and record the resulting page count; silently accepting a `next_page_token` would create an incomplete research dataset.

The chain-backed paper coordinator accepts only resolved option legs. Its ordering is: hard event gate → portfolio risk gate → Sniper bucket → Nebius qualitative review → idempotent Alpaca submission → audit ledger.

The earnings event gate consumes a versioned seven-calendar-day snapshot from Nasdaq's free expected-earnings calendar. Its metadata records every queried date, retrieval time, source, and the source's algorithmic-date caveat. Missing, stale, malformed, or incomplete coverage vetoes entry. A returned report date within three calendar days is a hard veto.

Every entry path first consults Alpaca's paper `/v2/clock` and `/v2/orders` history. Broker history is merged with submitted rows in `logs/orders/ids.jsonl` to reconstruct order counts and cooldown timestamps. Contract-specific client IDs provide Alpaca idempotency; a separate completed-signal ID prevents repricing from creating a second entry from the same daily formation.

Paper-submit requires a versioned CatBoost artifact and a feature vector; manual probability overrides are fixture-only. After a non-dry submission, the coordinator records Alpaca account, open-order, and position reconciliation in the same trading-day ledger.

`ExecutionMonitor` observes the resulting order and writes fill/account/position snapshots, including a bounded timeout exception, so a submitted order is never treated as filled merely because the POST succeeded.

Open defined-risk credit positions use the provider-agnostic `position_manager` contract for event-driven management. It evaluates current spread debit against profit-target, stop-loss, and time-stop rules, then reverses the opening legs into an idempotent close envelope. The manager is intentionally separate from quote retrieval: free indicative snapshots or a future runner can supply marks without granting the LLM authority to override hard exits.

Portfolio reconstruction uses Alpaca account, position, and open-order truth plus the submitted order registry. It requires options Level 3, positive options buying power, no broker block flag, and no untracked option position/order. Active spread risk is aggregated by sleeve, ticker, and sector using the pinned Greenlist sector map. Selected option legs must have fresh, two-sided quotes within the configured spread-width limit, and the modeled credit must meet the configured minimum percentage of spread width.

`manage_live_cli` is the provider-backed bridge: it matches registry entries only when both option legs are currently held, parses the OCC symbols, requests the current indicative quotes for the exact expiration, and records a skip on missing metadata/quotes. It defaults to `dry-run`; `paper-submit` is an explicit mode and remains paper-endpoint-only.

When `EXTRAPCAP_NEWS_LLM=true`, dated event rows with headlines are also sent to Nebius for a structured `noise_or_opinion` versus `structural_risk` classification. Local hard-term matches and dated structural flags veto before the model; missing keys, malformed JSON, invalid categories, or model disagreement fail closed to a structural-risk veto. The LLM cannot clear a hard event rule.

Dry-run and submitted order identities share deterministic IDs but have distinct registry statuses. Dry-run observations remain replayable without being treated as evidence that an order reached Alpaca, and therefore cannot block a later explicitly approved paper submission.

## Journal generation

Each dated event receives a versioned journal envelope containing a deterministic event ID, timestamp, ticker, OCC contract IDs and parsed contract details, strategy and sleeve, model context, provider, status, and readable title.

The static Astro journal scans every dated ledger category and the newest real-bar variant report during each build. It does not contain a separately maintained trade list or performance fixture. Scheduled repository writers check out the generated `ops` branch, merge source changes from `main`, and use the shared `extrapcap-ops-writer` concurrency group so runtime-state pushes serialize. GitHub Pages deploys from `ops`.

Scheduled candidate review runs the provider-backed cycle over the current streak-screened basket. The formation streak length, direction, signed depth, relative move, and robust Z-score travel with each candidate into the ledger and public journal.

The core domain modules are pure Python where possible so backtests and paper runs share decision logic. Provider adapters are side-effecting boundaries and default to dry-run.
