from __future__ import annotations

import os
import subprocess


def _secret(name: str, service: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    try:
        result = subprocess.run(["security", "find-generic-password", "-s", service, "-w"], capture_output=True, text=True, check=False, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def require_paper_credentials() -> tuple[str, str]:
    if os.getenv("ALPACA_PAPER", "true").lower() != "true":
        raise RuntimeError("paper-only mode is required")
    key = _secret("ALPACA_API_KEY", "extrapcap.alpaca.api_key")
    secret = _secret("ALPACA_SECRET_KEY", "extrapcap.alpaca.secret_key")
    if not key or not secret:
        raise RuntimeError("set ALPACA_API_KEY and ALPACA_SECRET_KEY through a secret manager")
    return key, secret


def require_nebius_key() -> str:
    key = _secret("NEBIUS_API_KEY", "extrapcap.nebius.api_key")
    if not key:
        raise RuntimeError("set NEBIUS_API_KEY through a secret manager")
    return key
