from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .alpaca import AlpacaPaperClient
from ..ledger import AuditLedger


PRIVATE_ACCOUNT_FIELDS = {"id", "account_number"}


def sanitize_account(account: dict) -> dict:
    """Preserve operating metrics while excluding private account identifiers."""
    return {key: value for key, value in account.items() if key not in PRIVATE_ACCOUNT_FIELDS}


@dataclass(frozen=True)
class Reconciliation:
    account: dict
    open_orders: list
    positions: list

    def as_dict(self) -> dict:
        return {"account": self.account, "open_orders": self.open_orders, "positions": self.positions}


def reconcile(client: AlpacaPaperClient, ledger: AuditLedger | None = None, trading_day: date | None = None) -> Reconciliation:
    snapshot = Reconciliation(sanitize_account(client.account()), client.open_orders(), client.positions())
    if ledger:
        ledger.append("reports", {"kind": "reconciliation", **snapshot.as_dict()}, trading_day)
    return snapshot
