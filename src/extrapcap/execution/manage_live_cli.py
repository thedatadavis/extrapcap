from __future__ import annotations

import argparse
from datetime import date
import json
import os

from .alpaca import AlpacaPaperClient
from .live_position_manager import manage_live_positions
from ..options_data import AlpacaOptionsData


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage held Extrapcap verticals from Alpaca account state")
    parser.add_argument("--registry", default="logs/orders/ids.jsonl")
    parser.add_argument("--execution-mode", choices=("dry-run", "paper-submit", "live-submit"), default="dry-run")
    parser.add_argument("--as-of", default=date.today().isoformat())
    args = parser.parse_args()
    os.environ["EXTRAPCAP_EXECUTION_MODE"] = args.execution_mode
    client = AlpacaPaperClient.from_env()
    results = manage_live_positions(
        client,
        AlpacaOptionsData(client.api_key, client.secret_key),
        registry_path=args.registry,
        as_of=date.fromisoformat(args.as_of),
    )
    print(json.dumps({"as_of": args.as_of, "execution_mode": args.execution_mode, "results": results}, indent=2))


if __name__ == "__main__":
    main()
