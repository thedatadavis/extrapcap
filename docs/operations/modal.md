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

Create a Modal secret named `extrapcap-secrets` containing your API keys and GitHub personal access token (for pushing log updates to the `ops` branch):

```bash
modal secret create extrapcap-secrets \
  ALPACA_API_KEY="your_alpaca_key" \
  ALPACA_SECRET_KEY="your_alpaca_secret" \
  NEBIUS_API_KEY="your_nebius_key" \
  GH_PAT="your_github_pat_with_repo_scope"
```

## Workload Schedules

| Function | Schedule (EDT) | Cron (UTC) | Description |
|---|---|---|---|
| `pre_open_prep` | 9:00 AM EDT | `0 13 * * 1-5` | Refreshes earnings calendar & prepares candidate basket |
| `entry_check_opening` | 9:45 AM EDT | `45 13 * * 1-5` | Opening candidate review & order submission |
| `entry_check_pre_lunch` | 12:15 PM EDT | `15 16 * * 1-5` | Midday candidate review & order submission |
| `entry_check_afternoon` | 3:00 PM EDT | `0 19 * * 1-5` | Afternoon candidate review & order submission |
| `position_exit_check` | Every 30 mins (9:30 AM – 4:30 PM EDT) | `*/30 13-20 * * 1-5` | Evaluates held option positions for profit/loss exit rules |
| `post_close_reconciliation` | 4:30 PM EDT | `30 20 * * 1-5` | Reconciles Alpaca paper account equity and open positions |
| `post_close_daily_report` | 4:45 PM EDT | `45 20 * * 1-5` | Renders daily operations report |

## Deployment Commands

Deploy all scheduled functions to Modal:
```bash
modal deploy src/extrapcap/orchestration/modal_app.py
```

Run a specific function manually on demand:
```bash
modal run src/extrapcap/orchestration/modal_app.py::entry_check_opening
```
