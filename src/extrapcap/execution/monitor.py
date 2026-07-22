from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import time

from ..ledger import AuditLedger
from .reconcile import sanitize_account


TERMINAL_STATUSES = {"filled", "partially_filled", "canceled", "expired", "rejected", "done_for_day"}


@dataclass(frozen=True)
class OrderObservation:
    order: dict
    account: dict
    positions: list


class ExecutionMonitor:
    def __init__(self, client, ledger: AuditLedger | None = None, reviewer=None):
        self.client = client
        self.ledger = ledger or AuditLedger()
        self.reviewer = reviewer

    def observe(self, order_id: str, trading_day: date | None = None) -> OrderObservation:
        observation = OrderObservation(
            self.client.order(order_id),
            sanitize_account(self.client.account()),
            self.client.positions(),
        )
        payload = {"order": observation.order, "account": observation.account, "positions": observation.positions}
        self.ledger.append("fills", payload, trading_day)
        if self.reviewer is not None and observation.order.get("status") in TERMINAL_STATUSES:
            try:
                commentary = self.reviewer.post_trade_commentary(payload)
            except Exception as exc:
                commentary = {
                    "commentary": "Post-trade reviewer failed; inspect the structured fill observation.",
                    "anomalies": [f"reviewer_failure:{type(exc).__name__}"],
                    "reason": "reviewer failure",
                }
            self.ledger.append(
                "rationales",
                {"kind": "post_trade_commentary", "order_id": order_id, "input": payload, "output": commentary},
                trading_day,
            )
        return observation

    def wait_for_terminal(self, order_id: str, timeout_seconds: int = 60, poll_seconds: int = 5, trading_day: date | None = None) -> OrderObservation:
        deadline = time.monotonic() + timeout_seconds
        while True:
            observation = self.observe(order_id, trading_day)
            if observation.order.get("status") in TERMINAL_STATUSES:
                return observation
            if time.monotonic() >= deadline:
                self.ledger.append("exceptions", {"order_id": order_id, "reason": "order_monitor_timeout"}, trading_day)
                return observation
            time.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))
