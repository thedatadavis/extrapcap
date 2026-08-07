from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from ..secrets import require_paper_credentials

PAPER_API_ROOT = "https://paper-api.alpaca.markets/v2"


def normalize_paper_api_root(value: str) -> str:
    parsed = urlsplit(value.rstrip("/"))
    if (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), parsed.query, parsed.fragment) not in {
        ("https", "paper-api.alpaca.markets", "", "", ""),
        ("https", "paper-api.alpaca.markets", "/v2", "", ""),
    }:
        raise RuntimeError("refusing non-paper Alpaca v2 API root")
    return PAPER_API_ROOT


@dataclass
class AlpacaPaperClient:
    """The only production execution adapter: authenticated Alpaca paper trading."""

    base_url: str = PAPER_API_ROOT
    api_key: str | None = None
    secret_key: str | None = None

    @classmethod
    def from_env(cls) -> "AlpacaPaperClient":
        if os.getenv("ALPACA_PAPER", "true").lower() != "true":
            raise RuntimeError("ALPACA_PAPER=true is required")
        key, secret = require_paper_credentials()
        return cls(normalize_paper_api_root(os.getenv("ALPACA_BASE_URL", PAPER_API_ROOT)), key, secret)

    def _request(self, path: str, method: str = "GET", payload: dict | None = None) -> dict | list:
        if not self.api_key or not self.secret_key:
            raise RuntimeError("missing Alpaca paper credentials")
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={
                "APCA-API-KEY-ID": self.api_key,
                "APCA-API-SECRET-KEY": self.secret_key,
                "Content-Type": "application/json",
            },
            method=method,
        )
        with urlopen(request, timeout=20) as response:
            body = response.read()
        return json.loads(body) if body else {}

    def submit_order(self, order: dict) -> dict:
        response = self._request("/orders", "POST", order)
        if not isinstance(response, dict) or not response.get("id"):
            raise RuntimeError("Alpaca paper order response omitted id")
        status = str(response.get("status", "")).lower()
        if status in {"rejected", "canceled", "expired", "suspended"}:
            raise RuntimeError(f"Alpaca paper order rejected: {status}")
        return response

    def account(self) -> dict:
        result = self._request("/account")
        if not isinstance(result, dict):
            raise RuntimeError("invalid Alpaca account response")
        return result

    def clock(self) -> dict:
        result = self._request("/clock")
        if not isinstance(result, dict) or not isinstance(result.get("is_open"), bool):
            raise RuntimeError("invalid Alpaca market clock response")
        return result

    def open_orders(self) -> list:
        result = self._request("/orders?status=open&nested=true")
        if not isinstance(result, list):
            raise RuntimeError("invalid Alpaca open orders response")
        return result

    def orders_after(self, after: datetime) -> list:
        query = urlencode({"status": "all", "after": after.astimezone(timezone.utc).isoformat(), "direction": "asc", "nested": "true", "limit": 500})
        result = self._request(f"/orders?{query}")
        if not isinstance(result, list):
            raise RuntimeError("invalid Alpaca order history response")
        return result

    def positions(self) -> list:
        result = self._request("/positions")
        if not isinstance(result, list):
            raise RuntimeError("invalid Alpaca positions response")
        return result

    def order(self, order_id: str, nested: bool = True) -> dict:
        result = self._request(f"/orders/{order_id}?nested=true" if nested else f"/orders/{order_id}")
        if not isinstance(result, dict):
            raise RuntimeError("invalid Alpaca order response")
        return result

    def get_order(self, order_id: str) -> dict:
        return self.order(order_id)

    def cancel_order(self, order_id: str) -> dict:
        result = self._request(f"/orders/{order_id}", "DELETE")
        if not isinstance(result, dict):
            raise RuntimeError("invalid Alpaca cancel response")
        return result

    def reset_paper_account(self) -> dict:
        canceled = self._request("/orders", "DELETE")
        closed = self._request("/positions", "DELETE")
        if not isinstance(canceled, list) or not isinstance(closed, list):
            raise RuntimeError("invalid Alpaca paper reset response")
        return {"status": "submitted", "canceled_orders": canceled, "closed_positions": closed}

    def execute_order_with_backoff(self, order_payload: dict, **_: object) -> dict:
        """Submit one midpoint order; ambiguity is surfaced to the caller."""
        return self.submit_order(order_payload)


AlpacaClient = AlpacaPaperClient
