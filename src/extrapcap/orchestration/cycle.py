from __future__ import annotations

import argparse
import json
import os
import pandas as pd

from ..execution.alpaca import AlpacaPaperClient
from ..execution.orders import OrderEnvelope, OrderRegistry
from ..ledger import AuditLedger
from ..llm.nebius import NebiusReviewer
from ..options import build_credit_spread
from ..models.sniper import SniperModel
from ..signals import SNIPER_FEATURES


def run_cycle(input_path: str, execution_mode: str = "dry-run") -> list[dict]:
    bars = pd.read_csv(input_path, parse_dates=["date"])
    client = AlpacaPaperClient.from_env()
    client.dry_run = execution_mode != "paper-submit"
    registry = OrderRegistry()
    ledger = AuditLedger()
    reviewer = NebiusReviewer()
    sniper = None
    if execution_mode == "paper-submit":
        model_path = os.getenv("SNIPER_MODEL_PATH")
        if not model_path:
            raise RuntimeError("paper-submit requires SNIPER_MODEL_PATH for a versioned Sniper artifact")
        sniper = SniperModel.load(model_path, SNIPER_FEATURES)
    results = []
    for row in bars.sort_values("date").itertuples():
        if row.symbol == "SPY":
            continue
        spread = build_credit_spread(row.symbol, row.close, "improved")
        envelope = OrderEnvelope(str(row.date.date()), row.symbol, "sell_to_open", ({"symbol": row.symbol, "side": "sell_to_open", "ratio_qty": 1}, {"symbol": row.symbol, "side": "buy_to_open", "ratio_qty": 1}), "core", limit_price=spread.credit)
        if registry.contains(envelope.client_order_id):
            continue
        review_input = {"symbol": row.symbol, "spread": spread.__dict__, "model_loaded": sniper is not None}
        try:
            judgment = reviewer.review(review_input)
        except Exception as exc:
            judgment = {"decision": "escalate", "reason": f"reviewer failure: {type(exc).__name__}", "provider": "nebius"}
        ledger.append("rationales", {"candidate": envelope.client_order_id, "input": review_input, "judgment": judgment}, row.date.date())
        if judgment.get("decision") != "go":
            results.append({"candidate": envelope.client_order_id, "status": "not_submitted", "reason": judgment.get("decision")})
            continue
        try:
            payload = envelope.alpaca_payload()
        except ValueError as exc:
            results.append({"candidate": envelope.client_order_id, "status": "not_submitted", "reason": str(exc)})
            continue
        response = client.submit_order(payload)
        registry.record(envelope)
        ledger.append("orders", {"client_order_id": envelope.client_order_id, "response": response}, row.date.date())
        results.append({"candidate": envelope.client_order_id, "status": response.get("status", "submitted")})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one idempotent paper-cycle pass")
    parser.add_argument("--input", required=True)
    parser.add_argument("--execution-mode", choices=("dry-run", "paper-submit"), default="dry-run")
    args = parser.parse_args()
    print(json.dumps(run_cycle(args.input, args.execution_mode), indent=2))


if __name__ == "__main__":
    main()
