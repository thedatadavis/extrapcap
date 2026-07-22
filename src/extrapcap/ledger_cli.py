from __future__ import annotations

import argparse
from datetime import date
from .ledger import AuditLedger


def main() -> None:
    parser = argparse.ArgumentParser(description="Commit one Extrapcap audit day")
    parser.add_argument("--root", default="logs")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--message-prefix", default="ledger")
    args = parser.parse_args()
    committed = AuditLedger(args.root).commit_day(args.date, args.message_prefix)
    print({"date": args.date, "committed": committed})


if __name__ == "__main__":
    main()
