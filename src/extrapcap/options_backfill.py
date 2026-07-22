from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .options_data import AlpacaOptionsData


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill an Alpaca option-chain snapshot with provenance")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--expiration-gte", required=True)
    parser.add_argument("--expiration-lte")
    parser.add_argument("--feed", choices=("indicative", "opra"), default="indicative")
    parser.add_argument("--output-dir", default="data/options")
    args = parser.parse_args()
    provider = AlpacaOptionsData()
    contracts = provider.contracts_all(args.symbol, args.expiration_gte, args.expiration_lte)
    payload, tier = provider.chain_all(args.symbol, expiration_gte=args.expiration_gte, expiration_lte=args.expiration_lte, feed=args.feed)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = output / f"{args.symbol.lower()}-{stamp}.json"
    path.write_text(json.dumps({"retrieved_at": datetime.now(timezone.utc).isoformat(), "underlying": args.symbol, "feed": args.feed, "data_tier": tier.value, "request": vars(args), "contracts": contracts, "payload": payload}, indent=2) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
