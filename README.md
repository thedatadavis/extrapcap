# Extrapolation Capital

Extrapolation Capital is a paper-traded options research system built around a simple thesis: liquid markets can periodically overprice fear, but harvesting that premium is only acceptable when risk is bounded, observable, and easy to replay.

The system has two sleeves:

- **Core premium engine:** defined-risk put spreads, with baseline and higher-POP OTM variants.
- **Asymmetric opportunity engine:** a separately budgeted sleeve funded only from realized core premium.

This repository provides the research core, trade construction, risk engine, Modal serverless execution pipeline, and Cloudflare Pages SSR dashboard backed by Cloudflare D1.

## System Architecture

- **Compute Platform**: [Modal](https://modal.com) — Serverless Python crons for market data refresh, streak screening, pre-market prep, candidate review, position management, reconciliation, and daily EOD reporting.
- **Database**: Cloudflare D1 — Managed SQLite database storing all trading events, active positions, order registries, stock bars, and account history.
- **Dashboard**: [Cloudflare Pages](https://extrapcap.pages.dev) — Astro SSR web application with real-time D1 bindings and an interactive option spread visualizer.
- **Admin Console**: Available at `/admin` (password-protected) for monitoring workflow execution runs and position status.

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
```

## Modal Deployment

```bash
# Set credentials in Modal secrets
modal secret create alpaca-paper ALPACA_API_KEY=... ALPACA_SECRET_KEY=...
modal secret create nebius NEBIUS_API_KEY=...
modal secret create cloudflare-api CF_APP_URL=https://extrapcap.pages.dev CF_API_TOKEN=...

# Deploy cron functions
modal deploy modal_app/app.py
```

## Cloudflare D1 & Pages Deployment

```bash
# Build and deploy Astro SSR application
pnpm build
pnpm wrangler pages deploy dist --project-name=extrapcap

# Database migrations
pnpm wrangler d1 execute extrapcap --remote --file=schema.sql
```

## Operating modes

`end_of_day`, `hybrid`, and `intraday_loop` are configuration choices, not separate strategies. The first implementation consumes bars supplied by a data adapter, so the same strategy can be tested at daily or intraday frequency without changing decision logic.

The tradable-basket screen uses the completed relative-return streak versus SPY. The default screen retains lengths 2 through 7, records every decision, and ranks longer negative streaks with robust Z at or below `-2.0` first.
