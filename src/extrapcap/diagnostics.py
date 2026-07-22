from __future__ import annotations

import argparse
import json
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
            result["alpaca"].update({"reachable": True, "account_status": account.get("status"), "account_number_present": bool(account.get("account_number"))})
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
    result["ready_for_read_only_live_cycle"] = result["alpaca"].get("reachable") is True and result["nebius"].get("reachable") is True
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
    args = parser.parse_args()
    result = run_diagnostics()
    print(json.dumps(result, indent=2))
    if args.require_ready and not diagnostic_ready(result):
        raise SystemExit("provider diagnostics failed: Alpaca paper and Nebius must both be reachable")


if __name__ == "__main__":
    main()
