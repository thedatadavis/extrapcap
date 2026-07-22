# Extrapolation Capital — research memo

**As of:** 2026-07-22  
**Status:** paper-only research; no order has been submitted.

## Executive summary

Extrapolation Capital tests a simple claim: liquid, sharp downside moves can create a repeatable opportunity to sell bounded downside risk, provided the system rejects structural breaks and refuses ambiguous model states. The implementation expresses that claim as transactions-as-code: a core defined-risk premium sleeve, a premium-funded asymmetric sleeve, a CatBoost Sniper classifier, hard risk gates, and a bounded Nebius review layer.

The current evidence is deliberately mixed. A six-symbol Alpaca bar dataset is now versioned locally and supports a reproducible signal/model run. The tradable-basket screen now includes the paper-inspired signed relative streak: completed 2-to-5-day underperformance and outperformance versus SPY are recorded before downstream liquidity, Sniper, event, and risk gates. On that bar-only proxy, the improved OTM construction produced more wins and a higher proxy profit factor, while the baseline collected more premium and had higher proxy expectancy. These figures are risk-unit simulations with modeled option credits and one-bar exits, not historical option-chain performance. A single real SPY indicative chain snapshot supports contract resolution and dry-run order construction, but is not enough for a historical performance claim.

The first real provider-backed cycle used the newly trained model, scored SPY at `0.4524`, and stopped under the Crash Protocol. That is the intended safety behavior: a low probability of mean reversion does not become a premium sale merely because a quote exists.

## Hypothesis and operating design

The thesis combines extrapolation bias, mean reversion, and variance-risk-premium harvesting. Panic can stretch realized-move expectations; liquid defined-risk spreads may monetize that gap. The system treats bounded risk and liquidity quality as prerequisites, not post-trade preferences. Income generation and convex opportunity capture are separate sleeves: 15% of realized core premium funds the asymmetric budget, subject to independent caps.

Variant A is the premium-maximizing baseline. Variant B moves the short put farther OTM, targeting the configured 0.15–0.20 delta band and accepting less credit for higher modeled POP. A classifier probability below 0.50 routes to the Crash Protocol; 0.50–0.65 is a strict Trap-zone rejection; 0.65 and above is eligible for bullish premium review. The optional intraday mode is implemented as scheduled 15-minute bursts with duplicate-order and execution-window controls.

## Data and universe

The canonical universe adapter consumes the `active_tickers.csv` data contract from `bootstrapital/stockstreaks-registry`, records source metadata, and writes timestamped Greenlist snapshots and filter decisions. The current real bar refresh used Alpaca daily bars for `SPY`, `AAPL`, `MSFT`, `NVDA`, `AMZN`, and `GOOGL`: 3,006 observations, 501 per symbol, from 2024-07-23 through 2026-07-22 UTC.

The real options artifact is `data/options/spy-20260722T135625Z.json`: 2,046 contracts and 4,092 quote snapshots across five pages, with an indicative feed. It resolved a one-contract SPY 2026-07-24 put vertical (`739/734`) at a quoted credit of $0.39 and a dry-run limit credit of $0.35. Paid OPRA history is intentionally out of scope; free multi-period chain history, corporate-action normalization, and survivorship analysis remain open research work.

## Model

The versioned artifact is `models/sniper.cbm`, trained from the normalized six-symbol bar dataset with features `relative_return`, `robust_z`, `streak_depth`, `stock_return`, `benchmark_return`, and `turn_of_month`. The time-ordered report in `reports/sniper/evaluation.json` records:

| Split | Brier | ECE |
|---|---:|---:|
| Validation | 0.2595 | 0.0837 |
| Test | 0.2628 | 0.0760 |

This is calibration evidence, not proof of economic edge. Feature importance and probability histograms are part of the model-report contract; a future retraining workflow must replace the artifact only after the same evaluation and approval gates pass.

## Proxy backtest results

The refreshed engine enforces overlapping core-risk, daily-loss, drawdown,
ticker, and optional sector concentration gates. Sector concentration remains
explicitly unavailable for the current real-bar artifact because no sector
metadata is present.

The visual comparison is committed at reports/assets/variant-comparison.svg,
and formation-date examples from the signed streak basket are in
reports/case-studies-2026-07-22.md. The comparison table now includes P05,
median, and P95 trade-return quantiles so the high win rate is not presented
without its loss-tail context.

The comparison in `reports/real-bars-variant-comparison-2026-07-22.md` uses real daily bars but modeled spread credits, one-bar expiration-style exits, and normalized risk-unit returns. It now emits both risk-unit diagnostics and a fixed-$100,000 daily portfolio curve with win rate, expectancy, Sharpe, Sortino, max drawdown, P05 tail loss, profit factor, and total-return diagnostics, but it is useful for testing implementation and relative trade-offs only.

| Variant | Trades | Wins | Win rate | Premium | Proxy expectancy | Portfolio return | Portfolio drawdown | Proxy profit factor |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 810 | 743 | 91.7% | $121,500 | 0.3342 | 114.63% | -1.42% | 7.66 |
| Improved OTM | 810 | 802 | 99.0% | $89,100 | 0.2721 | 106.59% | -0.44% | 41.58 |

The improved structure traded premium for fewer modeled losses; the baseline generated more gross premium and higher per-risk-unit expectancy in this simplified sample. The engine also exercised the 15% premium-funding ledger and recorded asymmetric deployment, but its current continuation debit-spread treatment is intentionally conservative and not a substitute for a chain-based convexity study. The portfolio curve is an improved NAV accounting baseline, but it is not decision-grade: it does not yet model overlapping position margin, option-level mark-to-market, or time-weighted cash flows.

The ablation matrix in `reports/research-matrix-2026-07-22.md` makes the remaining comparison boundary explicit. With the real-data artifact, classifier scenarios completed; news filtering remains `not_run` without a dated event file, and intraday looping remains `not_run` because the refreshed dataset contains one daily observation per symbol/session. The Crash Protocol is modeled with the asymmetric 3%-of-NAV open-risk cap, but its debit pricing is still approximated.

## Execution and judgment layer

Alpaca is hard-wired to the paper endpoint and rejects non-paper routing. The coordinator requires resolved option legs, applies event and portfolio controls before the model bucket, asks Nebius for a structured bounded review, then produces an idempotent multi-leg order. It supports `dry-run`, `paper-submit`, and replay paths. The real Alpaca account returned `ACTIVE`; Nebius model listing and structured review also succeeded through the OpenAI-compatible Token Factory endpoint ([API introduction](https://docs.tokenfactory.nebius.com/api-reference/introduction), [model listing](https://docs.tokenfactory.nebius.com/api-reference/models/list-models)). No raw key is stored in the repository or report files.

The real model-backed SPY cycle returned `vetoed / crash_protocol`, so no order was sent. A separate full-chain dry-run demonstrated the resolved OCC legs and mleg payload with a positive model override; that override was fixture-only and did not submit an order. This separation keeps provider reachability, candidate construction, and model behavior observable without conflating a dry-run with a fill.

## What worked, what failed, and what remains

What worked: the provider boundaries are paper-only and redacted; real bars normalized successfully; the CatBoost artifact trained and loaded; a real chain was paginated and persisted; Nebius returned structured judgment; the real low-probability cycle stopped safely; and 33 unit/integration tests plus Ruff pass.

What failed or is not identifiable yet: the first Nebius endpoint/model defaults were stale and had to be corrected; automated macOS Keychain writes were blocked by desktop authorization; the option snapshot is indicative and only one day; no paper order has been submitted; and historical option-level CAGR, Sharpe, Sortino, tail loss, utilization, assignment, and intraday fill-quality conclusions cannot be identified from the present data.

## Operating roadmap

**MVP:** keep all scheduled workflows in dry-run, refresh real bars and Greenlist snapshots, retrain only through the versioned evaluation report, and collect paper observations with explicit approval before any `paper-submit` run.

**Production hardening:** add multi-period free indicative history if a freely available source becomes accessible, realistic bid/ask and partial-fill replay, overlapping-position/margin accounting, sector metadata, earnings/news feeds, daily report generation, and a manual paper-submit approval gate.

**Research backlog:** compare every required ablation (classifier, news filter, overlays, Crash Protocol, sleeve mix, and operating mode), quantify regime and sector decomposition, and only then assess bounded policy proposals from the RL-style improvement loop. The learner can recommend configuration changes but cannot submit orders.

The next external-state action is intentionally explicit: approve one supervised paper-submit smoke test after reviewing the current account, candidate, and risk envelope. Until then, the system remains paper-only and dry-run by default.
