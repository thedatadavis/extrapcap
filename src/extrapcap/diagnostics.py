from __future__ import annotations

import argparse
import json
import math
import os
from urllib.error import HTTPError

from .execution.alpaca import PAPER_API_ROOT, AlpacaPaperClient
from .llm.nebius import NebiusReviewer


def run_diagnostics() -> dict:
    result = {"paper_only": True, "alpaca": {}, "nebius": {}}
    try:
        client = AlpacaPaperClient.from_env()
        result["alpaca"] = {
            "configured": bool(client.api_key and client.secret_key),
            "endpoint_is_paper_v2": client.base_url == PAPER_API_ROOT,
        }
        if client.api_key and client.secret_key:
            account = client.account()
            try:
                options_level = int(account.get("options_trading_level"))
            except (TypeError, ValueError):
                options_level = None
            try:
                options_buying_power = float(account.get("options_buying_power"))
            except (TypeError, ValueError):
                options_buying_power = math.nan
            result["alpaca"].update(
                {
                    "reachable": True,
                    "account_status": account.get("status"),
                    "account_number_present": bool(account.get("account_number")),
                    "options_trading_level": options_level,
                    "options_buying_power_present": math.isfinite(options_buying_power),
                    "account_trading_ready": (
                        account.get("status") == "ACTIVE"
                        and options_level is not None
                        and options_level >= 3
                        and math.isfinite(options_buying_power)
                    ),
                }
            )
        else:
            result["alpaca"]["reachable"] = False
    except Exception as exc:
        result["alpaca"].update({"reachable": False, "error_type": type(exc).__name__})
        if isinstance(exc, HTTPError):
            result["alpaca"]["http_status"] = exc.code
    try:
        reviewer = NebiusReviewer()
        result["nebius"]["configured"] = bool(reviewer.api_key)
        if reviewer.api_key:
            models = reviewer.list_models()
            result["nebius"].update({"reachable": True, "model_count": len(models.get("data", []))})
        else:
            result["nebius"]["reachable"] = False
    except Exception as exc:
        result["nebius"] = {"reachable": False, "error_type": type(exc).__name__}
    result["paper_submit_enabled"] = os.getenv("EXTRAPCAP_PAPER_SUBMIT_ENABLED", "false").lower() == "true"
    result["ready_for_read_only_live_cycle"] = result["alpaca"].get("reachable") is True and result["nebius"].get("reachable") is True
    result["ready_for_paper_submit"] = (
        result["ready_for_read_only_live_cycle"]
        and result["alpaca"].get("account_trading_ready") is True
        and result["paper_submit_enabled"]
    )
    return result


def diagnostic_ready(result: dict) -> bool:
    return result.get("ready_for_read_only_live_cycle") is True


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Alpaca paper and Nebius provider diagnostics")
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="exit non-zero unless both providers are configured and reachable",
    )
    parser.add_argument(
        "--require-paper-submit-ready",
        action="store_true",
        help="also require an active level-3 paper options account, buying power, and the submit enable switch",
    )
    args = parser.parse_args()
    result = run_diagnostics()
    print(json.dumps(result, indent=2))
    if args.require_ready and not diagnostic_ready(result):
        raise SystemExit("provider diagnostics failed: Alpaca paper and Nebius must both be reachable")
    if args.require_paper_submit_ready and not result.get("ready_for_paper_submit"):
        raise SystemExit("provider diagnostics failed: paper-submit options readiness is incomplete")


if __name__ == "__main__":
    main()
