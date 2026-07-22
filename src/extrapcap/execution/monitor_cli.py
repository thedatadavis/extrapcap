from __future__ import annotations

import argparse
from datetime import date
import json

from .alpaca import AlpacaPaperClient
from .monitor import ExecutionMonitor


def main() -> None:
    parser = argparse.ArgumentParser(description="Observe one Alpaca paper order and reconcile it")
    parser.add_argument("--order-id", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    args = parser.parse_args()
    observation = ExecutionMonitor(AlpacaPaperClient.from_env()).wait_for_terminal(args.order_id, args.timeout_seconds, trading_day=date.today())
    print(json.dumps({"order": observation.order, "account": observation.account, "positions": observation.positions}, indent=2))


if __name__ == "__main__":
    main()
