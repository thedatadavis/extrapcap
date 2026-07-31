"""Reconciliation and portfolio state synchronization module."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import json

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile active paper trading account state with Alpaca")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="As-of date YYYY-MM-DD")
    args = parser.parse_args()

    client = AlpacaPaperClient.from_env()
    ledger = AuditLedger()
    snapshot = reconcile(client, ledger=ledger, trading_day=date.fromisoformat(args.as_of))
    print(json.dumps(snapshot.as_dict(), indent=2))


if __name__ == "__main__":
    main()
