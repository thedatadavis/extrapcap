from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.request import Request, urlopen
from ..secrets import optional_paper_credentials, require_paper_credentials, require_paper_submit_enabled


@dataclass
class AlpacaPaperClient:
    """Small fail-closed Alpaca adapter. No live URL is accepted."""

    base_url: str = "https://paper-api.alpaca.markets"
    api_key: str | None = None
    secret_key: str | None = None
    dry_run: bool = True

    @classmethod
    def from_env(cls) -> "AlpacaPaperClient":
        if os.getenv("ALPACA_PAPER", "true").lower() != "true":
            raise RuntimeError("Alpaca integration is paper-only: set ALPACA_PAPER=true")
        base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        if "paper-api.alpaca.markets" not in base_url:
            raise RuntimeError("refusing non-paper Alpaca base URL")
        mode = os.getenv("EXTRAPCAP_EXECUTION_MODE", "dry-run")
        if mode not in {"dry-run", "paper-submit"}:
            raise RuntimeError("EXTRAPCAP_EXECUTION_MODE must be dry-run or paper-submit")
        if mode == "paper-submit":
            require_paper_submit_enabled()
            key, secret = require_paper_credentials()
        else:
            key, secret = optional_paper_credentials()
        return cls(base_url, key, secret, mode != "paper-submit")

    def submit_order(self, order: dict) -> dict:
        if self.dry_run:
            return {"status": "dry_run", "order": order}
        if not self.api_key or not self.secret_key:
            raise RuntimeError("missing Alpaca paper credentials")
        request = Request(
            f"{self.base_url}/v2/orders",
            data=json.dumps(order).encode(),
            headers={"APCA-API-KEY-ID": self.api_key, "APCA-API-SECRET-KEY": self.secret_key, "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read())

    def _get(self, path: str) -> dict | list:
        if not self.api_key or not self.secret_key:
            raise RuntimeError("missing Alpaca paper credentials")
        request = Request(f"{self.base_url}{path}", headers={"APCA-API-KEY-ID": self.api_key, "APCA-API-SECRET-KEY": self.secret_key})
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read())

    def _request(self, path: str, method: str) -> dict | list:
        if not self.api_key or not self.secret_key:
            raise RuntimeError("missing Alpaca paper credentials")
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
        if self.dry_run:
            return {
                "status": "dry_run",
                "open_orders": self.open_orders() if self.api_key and self.secret_key else "credentials_not_configured",
                "positions": self.positions() if self.api_key and self.secret_key else "credentials_not_configured",
            }
        return {
            "status": "paper_submit",
            "canceled_orders": self._request("/v2/orders", "DELETE"),
            "closed_positions": self._request("/v2/positions", "DELETE"),
        }

    def account(self) -> dict:
        return self._get("/v2/account")

    def open_orders(self) -> list:
        return self._get("/v2/orders?status=open&nested=true")

    def positions(self) -> list:
        return self._get("/v2/positions")

    def order(self, order_id: str, nested: bool = True) -> dict:
        suffix = "?nested=true" if nested else ""
        return self._get(f"/v2/orders/{order_id}{suffix}")
