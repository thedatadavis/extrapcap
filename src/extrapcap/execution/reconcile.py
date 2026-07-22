from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .alpaca import AlpacaPaperClient
from ..ledger import AuditLedger


@dataclass(frozen=True)
class Reconciliation:
    account: dict
    open_orders: list
    positions: list

    def as_dict(self) -> dict:
        return {"account": self.account, "open_orders": self.open_orders, "positions": self.positions}


def reconcile(client: AlpacaPaperClient, ledger: AuditLedger | None = None, trading_day: date | None = None) -> Reconciliation:
    snapshot = Reconciliation(client.account(), client.open_orders(), client.positions())
    if ledger:
        ledger.append("reports", {"kind": "reconciliation", **snapshot.as_dict()}, trading_day)
    return snapshot
