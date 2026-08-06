import modal

app = modal.App("extrapcap")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "httpx>=0.27.0",
        "pandas>=2.2.0",
        "numpy>=1.26.0",
        "pydantic>=2.7.0",
        "requests>=2.31.0",
        "pytz>=2024.1",
    )
    .add_local_dir("src/extrapcap", remote_path="/root/src/extrapcap", copy=True)
    .add_local_dir("modal_app", remote_path="/root/modal_app", copy=True)
    .add_local_file("pyproject.toml", remote_path="/root/pyproject.toml", copy=True)
    .run_commands("pip install -e /root")
    .env({"PYTHONPATH": "/root:/root/src"})
)

secrets = [
    modal.Secret.from_name("alpaca-paper"),
    modal.Secret.from_name("nebius"),
    modal.Secret.from_name("cloudflare-api"),
    modal.Secret.from_name("resend"),
]

import sys


def load_all_functions():
    """Register all cron workflow functions on the app for deployment."""
    from modal_app.functions import (
        candidate_review,
        daily_report,
        data_refresh,
        improvement_loop,
        live_cycle,
        opening_prep,
        position_management,
        reconciliation,
        streak_screen,
    )


# Automatically load all functions when deploying or running app.py directly.
# When running an individual function file (e.g. streak_screen.py), that file registers itself.
if any("app.py" in arg for arg in sys.argv) or __name__ == "__main__":
    load_all_functions()


