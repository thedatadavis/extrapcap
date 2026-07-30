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

    def get_order(self, order_id: str) -> dict:
        if self.dry_run:
            return {"status": "filled", "id": order_id}
        return self._get(f"/orders/{order_id}")

    def cancel_order(self, order_id: str) -> dict:
        if self.dry_run:
            return {"status": "canceled", "id": order_id}
        return self._request(f"/orders/{order_id}", "DELETE")

    def execute_order_with_backoff(
        self,
        order_payload: dict,
        candidate_info: dict | None = None,
        max_attempts: int = 5,
        price_step: float = 0.02,
        backoff_delays: tuple[int, ...] = (2, 4, 8, 16, 32),
    ) -> dict:
        """Submit limit order and perform in-thread exponential backoff with price adjustments.

        - For debit spreads (side=buy or positive limit price): increase limit price by +$0.02 per attempt.
        - For credit spreads (side=sell): decrease limit price by -$0.02 per attempt.
        - Checks fill status after each backoff delay.
        - Leaves attempt 5 open as a DAY limit order if unfilled after 5 attempts.
        """
        if self.dry_run:
            return self.submit_order(order_payload)

        import time

        current_order = dict(order_payload)
        is_buy_debit = current_order.get("side") in {"buy", "buy_to_open"} or float(current_order.get("limit_price") or 0) > 0
        limit_price = float(current_order.get("limit_price") or 0)

        attempts_history = []
        last_response = None

        for attempt in range(1, max_attempts + 1):
            response = self.submit_order(current_order)
            last_response = response
            order_id = response.get("id") if isinstance(response, dict) else None

            attempts_history.append(
                {
                    "attempt": attempt,
                    "order_id": order_id,
                    "limit_price": limit_price,
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                }
            )

            if not order_id or attempt == max_attempts:
                break

            delay = backoff_delays[min(attempt - 1, len(backoff_delays) - 1)]
            time.sleep(delay)

            try:
                status_res = self.get_order(order_id)
                order_status = str(status_res.get("status", "")).lower()
                if order_status in {"filled", "partially_filled"}:
                    return {
                        **status_res,
                        "attempts_history": attempts_history,
                        "filled_attempt": attempt,
                    }
            except Exception:
                pass

            try:
                self.cancel_order(order_id)
            except Exception:
                pass

            if is_buy_debit:
                limit_price = round(limit_price + price_step, 2)
            else:
                limit_price = round(max(0.01, limit_price - price_step), 2)

            current_order["limit_price"] = str(limit_price)

        return {
            **(last_response if isinstance(last_response, dict) else {}),
            "attempts_history": attempts_history,
            "final_attempt_left_open": True,
        }


# Keep the existing import name stable while callers migrate to account-neutral
# terminology. The live path is selected only by EXTRAPCAP_EXECUTION_MODE.
AlpacaClient = AlpacaPaperClient
