# Extrapolation Capital

Extrapolation Capital is a paper-traded options research system built around a simple thesis: liquid markets can periodically overprice fear, but harvesting that premium is only acceptable when risk is bounded, observable, and easy to replay.

The system has two sleeves:

- **Core premium engine:** defined-risk put spreads, with baseline and higher-POP OTM variants.
- **Asymmetric opportunity engine:** a separately budgeted sleeve funded only from realized core premium.

This repository currently provides the deterministic research core: typed configuration, robust relative-return signals, trade construction, sleeve funding, hard risk checks, and an offline backtest engine. Alpaca and Nebius adapters are intentionally paper-only and environment-driven; no live trading route is supported.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
python -m extrapcap.backtest.cli --input examples/sample_bars.csv
python -m extrapcap.backtest.compare_cli --input examples/sample_bars.csv
python -m extrapcap.research.matrix_cli --input examples/sample_bars.csv
python -m extrapcap.backtest.chain_cli --input examples/sample_option_observations.csv
python -m extrapcap.orchestration.paper_run_cli --help
python -m extrapcap.orchestration.paper_run_cli --symbol ABC --price 100 --contracts examples/sample_contracts.json --snapshot examples/sample_snapshot.json --probability 0.72 --execution-mode dry-run
python -m extrapcap.data.refresh_cli --symbols SPY,AAPL --days 365
python -m extrapcap.data.features_cli --input data/normalized/bars.csv
python -m extrapcap.models.score_cli --input data/features/features.csv --model models/sniper.cbm
python -m extrapcap.universe.cli --output-dir data/universe
# then pass the timestamped greenlist CSV to extrapcap.universe.streak_cli
python -m extrapcap.diagnostics
python -m extrapcap.playback_cli --date 2026-07-22
python -m extrapcap.reporting.daily_cli --date 2026-07-22
python -m extrapcap.execution.position_manager_cli --help
python -m extrapcap.execution.manage_live_cli --help
python -m extrapcap.historical_options_cli --help
```

The sample run writes a JSON report under `reports/`. Real API keys are not needed for the offline path.

Provider refreshes write `bars.csv` plus a `bars.csv.metadata.json` provenance sidecar containing the request window, feed, symbols, row counts, and observed date bounds.

The scheduled intraday path uses `python -m extrapcap.orchestration.intraday_cli` for one provider-backed 1-minute scan per burst. It defaults to dry-run and requires a versioned Sniper artifact for either execution mode.

The scheduled operating chain is split into idempotent GitHub Actions for universe refresh, bar refresh, feature generation, model scoring, provider-backed candidate review, paper execution, reconciliation, and daily reporting. Each write job commits only its own artifact paths with a deterministic message.

## Operating modes

`end_of_day`, `hybrid`, and `intraday_loop` are configuration choices, not separate strategies. The first implementation consumes bars supplied by a data adapter, so the same strategy can be tested at daily or intraday frequency without changing decision logic.

Research results must distinguish reconstructed/approximated option data from historical chain data. Do not treat a high win rate as proof of quality; inspect expectancy, drawdown, tail loss, fill assumptions, and sleeve contribution together. Production matrix runs accept `--basket data/universe/tradable-basket.csv` to keep the streak-screened universe aligned with research.

The tradable-basket screen also uses the completed relative-return streak. A streak is a signed run of stock outperformance or underperformance versus SPY; the default screen retains lengths 2 through 5, records every decision, and is eligible for the next session only after the close. Negative streaks feed the mean-reversion/core research path; positive streaks remain available to continuation and Crash Protocol research.

See `docs/charter.md`, `docs/architecture.md`, `docs/strategy/variants.md`, and `docs/roadmap.md` for the current scope and explicit TODOs.

## Safety boundary

The execution adapter rejects live URLs and requires `ALPACA_PAPER=true`. Short options are represented only as defined-risk verticals. The LLM reviewer can veto or escalate a candidate, but cannot override hard risk controls.
Daily reports are deterministic by default. GitHub Actions enables the optional Nebius note with the NEBIUS_API_KEY secret; missing or malformed model output escalates and never changes execution state.
