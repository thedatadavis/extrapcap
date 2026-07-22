from __future__ import annotations

import argparse
from datetime import date
import json

from .alpaca import AlpacaPaperClient
from ..ledger import AuditLedger
from .reconcile import reconcile


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile the Alpaca paper account into the audit ledger")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--root", default="logs")
    args = parser.parse_args()
    snapshot = reconcile(
        AlpacaPaperClient.from_env(),
        AuditLedger(args.root),
        date.fromisoformat(args.date),
    )
    print(json.dumps(snapshot.as_dict(), indent=2))


if __name__ == "__main__":
    main()
