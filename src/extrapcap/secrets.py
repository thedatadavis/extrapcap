from __future__ import annotations

import os
import subprocess


def _secret(name: str, service: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    if os.getenv("EXTRAPCAP_KEYCHAIN_ENABLED", "true").lower() != "true":
        return None
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


def optional_paper_credentials() -> tuple[str | None, str | None]:
    """Load paper credentials when present without making read-only startup fatal."""
    return (
        _secret("ALPACA_API_KEY", "extrapcap.alpaca.api_key"),
        _secret("ALPACA_SECRET_KEY", "extrapcap.alpaca.secret_key"),
    )


def require_paper_submit_enabled() -> None:
    """Require a separate, explicit switch before any paper order mutation."""
    if os.getenv("EXTRAPCAP_PAPER_SUBMIT_ENABLED", "false").lower() != "true":
        raise RuntimeError(
            "paper-submit is disabled; set EXTRAPCAP_PAPER_SUBMIT_ENABLED=true in the paper environment"
        )


def require_live_submit_enabled() -> None:
    """Require an independent, explicit switch before live order mutation."""
    if os.getenv("EXTRAPCAP_LIVE_SUBMIT_ENABLED", "false").lower() != "true":
        raise RuntimeError(
            "live-submit is disabled; set EXTRAPCAP_LIVE_SUBMIT_ENABLED=true only after live readiness review"
        )


def require_live_credentials() -> tuple[str, str]:
    """Load credentials dedicated to the live account."""
    key = _secret("ALPACA_LIVE_API_KEY", "extrapcap.alpaca.live_api_key")
    secret = _secret("ALPACA_LIVE_SECRET_KEY", "extrapcap.alpaca.live_secret_key")
    if not key or not secret:
        raise RuntimeError("set ALPACA_LIVE_API_KEY and ALPACA_LIVE_SECRET_KEY through a secret manager")
    return key, secret


def require_nebius_key() -> str:
    key = _secret("NEBIUS_API_KEY", "extrapcap.nebius.api_key")
    if not key:
        raise RuntimeError("set NEBIUS_API_KEY through a secret manager")
    return key


def optional_nebius_key() -> str | None:
    return _secret("NEBIUS_API_KEY", "extrapcap.nebius.api_key")
