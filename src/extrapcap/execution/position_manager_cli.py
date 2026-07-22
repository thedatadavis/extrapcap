from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path

from .orders import OrderEnvelope
from .position_manager import ManagedPosition, build_close_envelope, evaluate_credit_exit
from ..config import RiskConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate open credit positions for deterministic exits")
    parser.add_argument("--input", required=True, help="JSON object with a positions array")
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--output")
    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    decisions = []
    for item in payload.get("positions", []):
        envelope_data = item["envelope"]
        envelope = OrderEnvelope(
            envelope_data["trading_day"],
            envelope_data["symbol"],
            envelope_data["side"],
            tuple(envelope_data["legs"]),
            envelope_data["sleeve"],
            envelope_data.get("limit_price"),
            envelope_data.get("quantity", 1),
        )
        position = ManagedPosition(
            envelope,
            float(item["entry_credit"]),
            float(item["current_debit"]),
            float(item["spread_width"]),
            date.fromisoformat(item["opened_at"]),
            date.fromisoformat(args.as_of),
        )
        decision = evaluate_credit_exit(position, RiskConfig())
        row = {"symbol": envelope.symbol, "client_order_id": envelope.client_order_id, **decision.__dict__}
        if decision.action == "close":
            row["close_order"] = build_close_envelope(position, decision).alpaca_payload()
        decisions.append(row)
    result = {"as_of": args.as_of, "positions": decisions}
    encoded = json.dumps(result, indent=2) + "\n"
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
