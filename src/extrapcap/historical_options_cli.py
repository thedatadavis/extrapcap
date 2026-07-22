from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.error import HTTPError

from .options_data import AlpacaOptionsData


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill historical option trades with feed-entitlement provenance")
    parser.add_argument("--symbols", required=True, help="comma-separated OCC option symbols")
    parser.add_argument("--start", required=True, help="RFC-3339 or YYYY-MM-DD start")
    parser.add_argument("--end", required=True, help="RFC-3339 or YYYY-MM-DD end")
    parser.add_argument("--requested-feed", choices=("opra", "indicative"), default="indicative")
    parser.add_argument("--output", default="data/options/historical-trades.json")
    parser.add_argument("--error-output", default="reports/historical-options-access.json")
    args = parser.parse_args()
    symbols = [value.strip().upper() for value in args.symbols.split(",") if value.strip()]
    request = {
        "symbols": symbols,
        "start": args.start,
        "end": args.end,
        "requested_feed": args.requested_feed,
        "provider_feed_selection": "account_agreement_default",
    }
    retrieved_at = datetime.now(timezone.utc).isoformat()
    try:
        payload, tier = AlpacaOptionsData().historical_trades_all(symbols, args.start, args.end, args.requested_feed)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1000]
        error = {
            "kind": "historical_options_access",
            "status": "blocked",
            "http_status": exc.code,
            "provider_message": body,
            "retrieved_at": retrieved_at,
            "request": request,
        }
        error_path = Path(args.error_output)
        error_path.parent.mkdir(parents=True, exist_ok=True)
        error_path.write_text(json.dumps(error, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(error, indent=2))
        raise SystemExit(2) from exc
    artifact = {
        "kind": "historical_option_trades",
        "status": "retrieved",
        "retrieved_at": retrieved_at,
        "data_tier": tier.value,
        "request": request,
        "payload": payload,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "retrieved", "output": str(output), "data_tier": tier.value, "trade_count": len(payload.get("trades", []))}, indent=2))


if __name__ == "__main__":
    main()
