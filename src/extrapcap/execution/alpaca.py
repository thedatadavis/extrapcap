from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from ..secrets import (
    optional_paper_credentials,
    require_live_credentials,
    require_live_submit_enabled,
    require_paper_credentials,
    require_paper_submit_enabled,
)

PAPER_API_ROOT = "https://paper-api.alpaca.markets/v2"
LIVE_API_ROOT = "https://api.alpaca.markets/v2"


def normalize_paper_api_root(value: str) -> str:
    """Return the one permitted Alpaca paper v2 API root.

    Accepting the host-only form keeps older configuration compatible while
    preventing both `/v2/v2/...` requests and lookalike-host bypasses.
    """
    parsed = urlsplit(value.rstrip("/"))
    path = parsed.path.rstrip("/")
    if (
        parsed.scheme != "https"
        or parsed.netloc != "paper-api.alpaca.markets"
        or path not in {"", "/v2"}
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("refusing non-paper Alpaca v2 API root")
    return PAPER_API_ROOT


def normalize_live_api_root(value: str) -> str:
    """Return the one permitted Alpaca live v2 API root."""
    parsed = urlsplit(value.rstrip("/"))
    path = parsed.path.rstrip("/")
    if (
        parsed.scheme != "https"
        or parsed.netloc != "api.alpaca.markets"
        or path not in {"", "/v2"}
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("refusing non-live Alpaca v2 API root")
    return LIVE_API_ROOT


@dataclass
class AlpacaPaperClient:
    """Small fail-closed Alpaca adapter for paper and explicitly enabled live modes."""

    base_url: str = PAPER_API_ROOT
    api_key: str | None = None
    secret_key: str | None = None
    dry_run: bool = True
    live: bool = False

    @classmethod
    def from_env(cls) -> "AlpacaPaperClient":
        mode = os.getenv("EXTRAPCAP_EXECUTION_MODE", "dry-run")
        if mode not in {"dry-run", "paper-submit", "live-submit"}:
            raise RuntimeError("EXTRAPCAP_EXECUTION_MODE must be dry-run, paper-submit, or live-submit")
        if mode == "live-submit":
            if os.getenv("ALPACA_PAPER", "true").lower() == "true":
                raise RuntimeError("live-submit requires ALPACA_PAPER=false")
            require_live_submit_enabled()
            base_url = normalize_live_api_root(os.getenv("ALPACA_BASE_URL", LIVE_API_ROOT))
            key, secret = require_live_credentials()
            return cls(base_url, key, secret, False, True)
        if os.getenv("ALPACA_PAPER", "true").lower() != "true":
            raise RuntimeError("paper mode requires ALPACA_PAPER=true")
        base_url = normalize_paper_api_root(os.getenv("ALPACA_BASE_URL", PAPER_API_ROOT))
        if mode == "paper-submit":
            require_paper_submit_enabled()
            key, secret = require_paper_credentials()
        else:
            key, secret = optional_paper_credentials()
        return cls(base_url, key, secret, mode != "paper-submit", False)

    def submit_order(self, order: dict) -> dict:
        if self.dry_run:
            return {"status": "dry_run", "order": order}
        if not self.api_key or not self.secret_key:
            raise RuntimeError("missing Alpaca credentials for the selected account")
        request = Request(
            f"{self.base_url}/orders",
            data=json.dumps(order).encode(),
            headers={"APCA-API-KEY-ID": self.api_key, "APCA-API-SECRET-KEY": self.secret_key, "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read())

    def _get(self, path: str) -> dict | list:
        if not self.api_key or not self.secret_key:
            raise RuntimeError("missing Alpaca credentials for the selected account")
        request = Request(f"{self.base_url}{path}", headers={"APCA-API-KEY-ID": self.api_key, "APCA-API-SECRET-KEY": self.secret_key})
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read())

    def _request(self, path: str, method: str) -> dict | list:
        if not self.api_key or not self.secret_key:
            raise RuntimeError("missing Alpaca credentials for the selected account")
        request = Request(
            f"{self.base_url}{path}",
            headers={"APCA-API-KEY-ID": self.api_key, "APCA-API-SECRET-KEY": self.secret_key},
            method=method,
        )
        with urlopen(request, timeout=20) as response:
            body = response.read()
            return json.loads(body) if body else {}

    def reset_paper_account(self) -> dict:
        """Cancel open orders and close positions; never available on a live URL."""
        if self.live:
            raise RuntimeError("paper-account reset is unavailable for a live client")
        if self.dry_run:
            return {
                "status": "dry_run",
                "open_orders": self.open_orders() if self.api_key and self.secret_key else "credentials_not_configured",
                "positions": self.positions() if self.api_key and self.secret_key else "credentials_not_configured",
            }
        return {
            "status": "paper_submit",
            "canceled_orders": self._request("/orders", "DELETE"),
            "closed_positions": self._request("/positions", "DELETE"),
        }

    def account(self) -> dict:
        return self._get("/account")

    def clock(self) -> dict:
        result = self._get("/clock")
        if not isinstance(result, dict) or not isinstance(result.get("is_open"), bool):
            raise RuntimeError("Alpaca market clock returned an invalid response")
        return result

    def open_orders(self) -> list:
        return self._get("/orders?status=open&nested=true")

    def orders_after(self, after: datetime) -> list:
        query = urlencode(
            {
                "status": "all",
                "after": after.astimezone(timezone.utc).isoformat(),
                "direction": "asc",
                "nested": "true",
                "limit": 500,
            }
        )
        result = self._get(f"/orders?{query}")
        if not isinstance(result, list):
            raise RuntimeError("Alpaca orders history returned an invalid response")
        return result

    def positions(self) -> list:
        return self._get("/positions")

    def order(self, order_id: str, nested: bool = True) -> dict:
        suffix = "?nested=true" if nested else ""
        return self._get(f"/orders/{order_id}{suffix}")


# Keep the existing import name stable while callers migrate to account-neutral
# terminology. The live path is selected only by EXTRAPCAP_EXECUTION_MODE.
AlpacaClient = AlpacaPaperClient
