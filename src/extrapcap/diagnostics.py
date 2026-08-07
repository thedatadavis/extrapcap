from __future__ import annotations

import argparse
import json
import math

from .execution.alpaca import PAPER_API_ROOT, AlpacaPaperClient
from .llm.nebius import NebiusReviewer


def run_diagnostics() -> dict:
    result = {"paper_only": True, "alpaca": {}, "nebius": {}}
    try:
        client = AlpacaPaperClient.from_env()
        account = client.account()
        level = int(account.get("options_trading_level"))
        buying_power = float(account.get("options_buying_power"))
        result["alpaca"] = {"configured": True, "reachable": True, "endpoint_is_paper_v2": client.base_url == PAPER_API_ROOT, "account_status": account.get("status"), "options_trading_level": level, "options_buying_power_present": math.isfinite(buying_power), "account_trading_ready": account.get("status") == "ACTIVE" and level >= 3 and math.isfinite(buying_power)}
    except Exception as exc:
        result["alpaca"] = {"configured": False, "reachable": False, "error_type": type(exc).__name__}
    try:
        reviewer = NebiusReviewer()
        result["nebius"] = {"configured": bool(reviewer.api_key), "reachable": bool(reviewer.api_key)}
    except Exception as exc:
        result["nebius"] = {"configured": False, "reachable": False, "error_type": type(exc).__name__}
    result["ready_for_paper_trading"] = result["alpaca"].get("account_trading_ready") is True
    return result


def diagnostic_ready(result: dict) -> bool:
    return result.get("ready_for_paper_trading") is True


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Alpaca paper-account diagnostics")
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    result = run_diagnostics()
    print(json.dumps(result, indent=2))
    if args.require_ready and not diagnostic_ready(result):
        raise SystemExit("paper-account diagnostics failed")


if __name__ == "__main__":
    main()
