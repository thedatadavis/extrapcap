from __future__ import annotations

import argparse
import json

from .alpaca import AlpacaPaperClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Guarded Alpaca paper-account reset")
    parser.add_argument(
        "--confirm",
        required=True,
        help="must be RESET_PAPER_ACCOUNT before canceling orders or closing positions",
    )
    args = parser.parse_args()
    if args.confirm != "RESET_PAPER_ACCOUNT":
        raise SystemExit("refusing reset: exact confirmation token is required")
    client = AlpacaPaperClient.from_env()
    print(json.dumps(client.reset_paper_account(), indent=2))


if __name__ == "__main__":
    main()
