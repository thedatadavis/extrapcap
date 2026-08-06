# Modal Scheduler Setup and Deployment

This document describes how to deploy and manage Extrapolation Capital's scheduled trading day workloads on **Modal Labs**.

## Prerequisites

1. Install Modal CLI:
   ```bash
   pip install modal
   ```
2. Authenticate with Modal:
   ```bash
   modal setup
   ```

## Secret Configuration

The modular Modal application consumes four Modal secrets:

```bash
modal secret create alpaca-paper ALPACA_API_KEY="..." ALPACA_SECRET_KEY="..."
modal secret create nebius NEBIUS_API_KEY="..."
modal secret create cloudflare-api CF_APP_URL="https://extrapcap.pages.dev" CF_API_TOKEN="..."
modal secret create resend RESEND_API_KEY="..." RECIPIENT_EMAIL="..." SENDER_EMAIL="..."
```

## Workload Schedules (`modal_app/app.py`)

| Function | Schedule (EDT) | Cron (UTC) | Description |
|---|---|---|---|
| `data_refresh` | 12:00 AM EDT | `0 4 * * 1-5` | Daily market stock bars & Greenlist refresh |
| `opening_prep` | 9:00 AM EDT | `0 13 * * 1-5` | Earnings calendar blackout & opening candidate prep |
| `candidate_review` | 9:45, 11:45, 15:45 EDT | `45 13,15,19 * * 1-5` | Market-hours option candidate review & paper submission |
| `position_management` | Every 30 mins (9:00–16:00 EDT) | `*/30 13-20 * * 1-5` | Evaluates held option positions for profit/loss exit rules |
| `daily_report` | 4:45 PM EDT | `45 20 * * 1-5` | Renders EOD operations report & emails executive summary |
| `improvement_loop` | 6:15 PM EDT | `15 22 * * 1-5` | Learner feedback loop & policy optimization |

## Deployment Commands

Deploy all scheduled functions to Modal:
```bash
modal deploy modal_app/app.py
```

Run a specific function manually on demand:
```bash
modal run modal_app/app.py::candidate_review
```
