# Specification completion audit

This is a living handoff, not a claim that the platform is ready for live capital.

## Implemented and locally verified

- Python package scaffold, typed configuration, CI, and scheduled workflow files.
- StockStreaks Greenlist refresh with timestamped CSV and filter-decision metadata.
- Relative-return, robust-Z, calendar, streak, and liquidity feature foundations.
- Baseline/improved defined-risk spread construction and premium-funded asymmetric ledger.
- CatBoost Sniper training, time splits, versioned artifact metadata, and calibration report.
- Chain-backed fill/expiry simulator with explicit data tiers, slippage, commissions, loss caps, and assignment flags.
- Structural-news and earnings vetoes, portfolio risk brakes, idempotent order IDs, audit ledger, replay, and reconciliation contracts.
- Bounded policy-improvement proposal loop with test/simulation/approval/rollback gates.
- Provider-backed live-cycle command and redacted provider diagnostics.
- Alpaca paper account read-only verification (`ACTIVE`), Nebius model-list/review verification, and a real-chain dry-run with resolved SPY OCC legs.
- Real Alpaca daily bars are refreshed from the pinned Greenlist plus SPY, with batched/paginated retrieval and an explicit missing-symbol coverage gate before streak evaluation.
- Normalized bar refreshes now write a provenance sidecar containing request window, symbols, IEX feed, adjustment, row counts, and observed date bounds.
- The bar-based variant report now emits win rate, expectancy, Sharpe, Sortino, max drawdown, P05 tail loss, profit factor, total return, and an explicit `modeled_option_proxy` scope.
- The research matrix now runs baseline/improved, classifier/no-classifier, turn-of-month, Crash Protocol, premium-only/asymmetric, hybrid, and intraday scenarios; missing classifier/news/intraday inputs are recorded as `not_run` rather than fabricated.
- The scheduled intraday workflow now invokes a provider-backed 1-minute scan with dynamic 2-to-35-day expiration bounds; the historical matrix still marks intraday backtests unavailable until intraday history is ingested.
- Live and intraday workflows now load the versioned `data/events/news.csv` schema when configured and fail closed on malformed structural-risk event data; the checked-in file is intentionally an empty template.
- The trained real-data model was exercised through the provider-backed SPY dry-run and correctly stopped the candidate under the crash protocol at probability `0.4524`; no order was submitted.
- Feature generation and Sniper scoring now have standalone CLIs and versionable `data/features` artifacts; scoring requires the optional CatBoost dependency and fails explicitly when it is unavailable.
- GitHub Actions now has separate idempotent jobs for feature generation, model scoring, candidate review, paper-account reconciliation, and daily replayable reports.
- Signal generation now exposes additive seasonality, volatility, market-regime, dollar-liquidity, intraday-range, and deterministic ticker-identity context columns for future model retraining.
- Intraday risk gates now convert aware timestamps to US/Eastern and enforce market windows, per-symbol daily order caps, cooldowns, and modeled-vs-observed fill-quality circuit breakers.
- Nebius review failures and malformed judgments fail closed to `escalate` and persist the bounded input/output metadata in rationale logs.
- Candidate records now persist model probability, bucket, spread, event, and risk decisions before review; dry-run registry entries are explicitly marked and cannot suppress a later paper-submit attempt.
- Nebius now has a bounded headline-classification path for dated event rows, with local structural-term precedence and fail-closed handling for missing/invalid model output; live and intraday workflows enable it explicitly.
- Backtest operating modes now have distinct behavior on multi-observation sessions: hybrid entries are restricted to close-positioning windows, intraday loop entries honor open/close windows, per-symbol session duplicate prevention, and cooldowns; daily data continues to report intraday scenarios as unavailable.
- The tradable-basket layer applies the paper-inspired signed relative-streak screen (completed lengths 2–5, both directions by default), writes every acceptance/rejection or missing-bars decision, and feeds an optional basket into the research matrix.
- The sleeve ledger now supports continuous and batched realized-premium transfers; asymmetric admission enforces reward-to-risk, open-risk, trade-count, and core-drawdown gates, with deterministic decay/time-stop exit reasons.
- A deterministic position manager now evaluates credit-spread profit targets, stop losses, and calendar time stops and constructs reversed-leg close orders. The provider-backed `manage_live_cli` matches current held OCC legs to free indicative quotes and fails closed on missing metadata/quotes; it is dry-run by default and has not submitted an exit.

## Partially complete

- Daily replay reports now include deterministic anomaly flags and an optional bounded Nebius portfolio note; the prompt, structured output, and model metadata are retained in the report when the workflow secret is configured.
- The backtest now enforces daily-loss, drawdown, ticker, and optional sector concentration gates while positions overlap; release records track risk by symbol and sector, and sector decomposition is explicitly marked unavailable when metadata is absent.
- The repository now includes guarded manual replay and paper-account-reset workflows, a versioned default configuration, and the required playback/ledger directory boundaries. Reset execution is dry-run by default and requires the exact confirmation token plus paper-submit mode.
- The institutional report now has a dependency-free SVG comparison visual, formation-date streak case studies, and P05/P50/P95 trade-return quantiles.
- Terminal paper-order observations now trigger optional bounded Nebius post-trade commentary, with the structured fill observation and model output appended to the rationale ledger.
- All new ledger events now include journal-ready ticker and OCC contract metadata, and the existing provider-backed SPY records were migrated to the same schema.
- The Astro site now generates from every dated ledger category and the latest modeled comparison report; hardcoded fixture performance and test-era journal pages were removed.
- Scheduled candidate review now scans the streak-screened basket, preserves formation context, commits its ledger, and serializes repository writes with the other operational workflows.
- The current core route now enforces completed negative streaks of 2–5 sessions plus the configured robust-Z threshold, ranks longer streaks first, and defers positive streaks to a named bearish-watch route before provider-heavy work.
- Provider-backed sizing now reconstructs NAV, daily PnL, drawdown, sleeve risk, and ticker risk from the Alpaca paper account plus the submitted-order registry; untracked option positions or orders fail closed.
- Paper submission now requires a separate persistent enable switch in addition to selecting `paper-submit`; scheduled candidate review remains dry-run until both GitHub variables are deliberately changed.

- Alpaca/Nebius paper-submit remains intentionally unexecuted; dry-run and read-only provider paths are verified. The new strict remote provider diagnostic must pass after credential changes before any turn-on decision.
- A real SPY indicative snapshot is now persisted under `data/options`; paid OPRA history is intentionally out of scope, and free multi-period historical option quotes remain unavailable.
- The institutional memo now records the real bar/model/provider evidence and its limitations; it does not claim historical option-level performance.
- Intraday looping is represented by scheduled bursts and execution windows; a persistent low-latency runner is not implemented. The provider-backed position manager is scheduled, but its paper-submit path remains unexecuted.

## Explicitly not claimed

- No live-trading route exists or is authorized.
- No performance claim is made from the sample fixtures.
- No raw API key is stored in the repository, reports, logs, or chat.
