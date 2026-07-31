"""Modal App for Extrapolation Capital trading day workloads."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import modal

app = modal.App("extrapcap-trading-system")

# Define the Modal image with Python 3.11, git, and extrapcap dependencies
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "curl")
    .pip_install(
        "pydantic>=2.7",
        "pandas>=2.2",
        "numpy>=1.26",
        "httpx>=0.27",
        "catboost>=1.2",
        "scikit-learn>=1.5",
    )
    .copy_local_dir(".", remote_path="/root/extrapcap")
)

secrets = [modal.Secret.from_name("extrapcap-secrets")]


def _run_git_cmd(command: str) -> subprocess.CompletedProcess[str]:
    """Execute git commands in the mounted extrapcap directory."""
    cwd = "/root/extrapcap"
    result = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Git command notice ({result.returncode}):\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}")
    return result


def _sync_and_run(cmd: list[str], commit_msg: str) -> int:
    """Sync source from main into ops, execute python command, commit log changes, and push."""
    cwd = "/root/extrapcap"
    env = os.environ.copy()
    env["PYTHONPATH"] = "/root/extrapcap/src"
    env["ALPACA_PAPER"] = "true"
    env["SNIPER_MODEL_PATH"] = "models/sniper.cbm"
    env["EXTRAPCAP_EARNINGS_CALENDAR"] = "data/events/earnings.csv"
    env["EXTRAPCAP_NEWS_EVENTS"] = "data/events/news.csv"
    env["EXTRAPCAP_NEWS_LLM"] = "true"

    # Configure git identity
    _run_git_cmd("git config user.name extrapcap-bot && git config user.email extrapcap-bot@users.noreply.github.com")

    # 1. Sync source from main into ops
    _run_git_cmd("bash .github/scripts/sync-ops.sh")

    # 2. Execute workload command
    res = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    print(f"STDOUT:\n{res.stdout}")
    print(f"STDERR:\n{res.stderr}")

    # 3. Commit and push logs back to ops
    _run_git_cmd("git add -A logs data/events reports")
    _run_git_cmd(f"git diff --cached --quiet || git commit -m '{commit_msg}'")
    _run_git_cmd("bash .github/scripts/push-ops.sh")
    return res.returncode


@app.function(
    image=image,
    secrets=secrets,
    schedule=modal.Cron("0 13 * * 1-5"),  # 9:00 AM EDT
    timeout=600,
)
def pre_open_prep():
    """9:00 AM EDT: Refresh earnings blackout window and prepare opening candidates."""
    print("--- Running 9:00 AM EDT Pre-Open Prep ---")
    today = subprocess.check_output(["date", "-u", "+%F"], text=True).strip()
    subprocess.run([sys.executable, "-m", "extrapcap.earnings", "--date", today], cwd="/root/extrapcap")
    cmd = [
        sys.executable,
        "-m",
        "extrapcap.orchestration.basket_cycle",
        "--basket",
        "data/universe/tradable-basket.csv",
        "--model",
        "models/sniper.cbm",
        "--expiration-gte",
        today,
        "--max-candidates",
        "10",
        "--fast-ev",
        "--review-phase",
        "opening_prep",
        "--prep-only",
    ]
    return _sync_and_run(cmd, f"ledger: opening paper candidate prep {today}")


@app.function(
    image=image,
    secrets=secrets,
    schedule=modal.Cron("45 13 * * 1-5"),  # 9:45 AM EDT (Opening)
    timeout=600,
)
def entry_check_opening():
    """9:45 AM EDT: Opening candidate review and paper order submission."""
    print("--- Running 9:45 AM EDT Opening Entry Check ---")
    today = subprocess.check_output(["date", "-u", "+%F"], text=True).strip()
    cmd = [
        sys.executable,
        "-m",
        "extrapcap.orchestration.basket_cycle",
        "--basket",
        "data/universe/tradable-basket.csv",
        "--model",
        "models/sniper.cbm",
        "--expiration-gte",
        today,
        "--max-candidates",
        "10",
        "--fast-ev",
    ]
    return _sync_and_run(cmd, f"ledger: review paper basket opening {today}")


@app.function(
    image=image,
    secrets=secrets,
    schedule=modal.Cron("15 16 * * 1-5"),  # 12:15 PM EDT (Pre-lunch)
    timeout=600,
)
def entry_check_pre_lunch():
    """12:15 PM EDT: Midday candidate review and paper order submission."""
    print("--- Running 12:15 PM EDT Pre-Lunch Entry Check ---")
    today = subprocess.check_output(["date", "-u", "+%F"], text=True).strip()
    cmd = [
        sys.executable,
        "-m",
        "extrapcap.orchestration.basket_cycle",
        "--basket",
        "data/universe/tradable-basket.csv",
        "--model",
        "models/sniper.cbm",
        "--expiration-gte",
        today,
        "--max-candidates",
        "10",
        "--fast-ev",
    ]
    return _sync_and_run(cmd, f"ledger: review paper basket pre-lunch {today}")


@app.function(
    image=image,
    secrets=secrets,
    schedule=modal.Cron("0 19 * * 1-5"),  # 3:00 PM EDT (Afternoon)
    timeout=600,
)
def entry_check_afternoon():
    """3:00 PM EDT: Afternoon candidate review and paper order submission."""
    print("--- Running 3:00 PM EDT Afternoon Entry Check ---")
    today = subprocess.check_output(["date", "-u", "+%F"], text=True).strip()
    cmd = [
        sys.executable,
        "-m",
        "extrapcap.orchestration.basket_cycle",
        "--basket",
        "data/universe/tradable-basket.csv",
        "--model",
        "models/sniper.cbm",
        "--expiration-gte",
        today,
        "--max-candidates",
        "10",
        "--fast-ev",
    ]
    return _sync_and_run(cmd, f"ledger: review paper basket afternoon {today}")


@app.function(
    image=image,
    secrets=secrets,
    schedule=modal.Cron("*/30 13-20 * * 1-5"),  # Every 30 mins (9:30 AM to 4:30 PM EDT)
    timeout=300,
)
def position_exit_check():
    """Every 30 mins: Evaluate held paper option positions for profit/loss exit triggers."""
    print("--- Running 30-Minute Position Exit Check ---")
    today = subprocess.check_output(["date", "-u", "+%F"], text=True).strip()
    cmd = [
        sys.executable,
        "-m",
        "extrapcap.execution.position_manager",
        "--as-of",
        today,
    ]
    return _sync_and_run(cmd, f"ledger: manage paper positions {today}")


@app.function(
    image=image,
    secrets=secrets,
    schedule=modal.Cron("30 20 * * 1-5"),  # 4:30 PM EDT
    timeout=300,
)
def post_close_reconciliation():
    """4:30 PM EDT: Post-close paper account reconciliation."""
    print("--- Running 4:30 PM EDT Account Reconciliation ---")
    today = subprocess.check_output(["date", "-u", "+%F"], text=True).strip()
    cmd = [
        sys.executable,
        "-m",
        "extrapcap.execution.account_sync",
        "--as-of",
        today,
    ]
    return _sync_and_run(cmd, f"ledger: reconcile paper account {today}")


@app.function(
    image=image,
    secrets=secrets,
    schedule=modal.Cron("45 20 * * 1-5"),  # 4:45 PM EDT
    timeout=300,
)
def post_close_daily_report():
    """4:45 PM EDT: Generate daily operations report."""
    print("--- Running 4:45 PM EDT Daily Operations Report ---")
    today = subprocess.check_output(["date", "-u", "+%F"], text=True).strip()
    cmd = [
        sys.executable,
        "-m",
        "extrapcap.reporting.daily_cli",
        "--date",
        today,
        "--output",
        f"reports/daily-{today}.json",
    ]
    return _sync_and_run(cmd, f"report: daily operations {today}")
