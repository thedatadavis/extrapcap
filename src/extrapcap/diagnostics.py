from __future__ import annotations

import json

from .execution.alpaca import AlpacaPaperClient
from .llm.nebius import NebiusReviewer


def run_diagnostics() -> dict:
    result = {"paper_only": True, "alpaca": {}, "nebius": {}}
    try:
        client = AlpacaPaperClient.from_env()
        result["alpaca"] = {"configured": bool(client.api_key and client.secret_key), "endpoint_is_paper": "paper-api.alpaca.markets" in client.base_url}
        if client.api_key and client.secret_key:
            account = client.account()
            result["alpaca"].update({"reachable": True, "account_status": account.get("status"), "account_number_present": bool(account.get("account_number"))})
        else:
            result["alpaca"]["reachable"] = False
    except Exception as exc:
        result["alpaca"] = {"reachable": False, "error_type": type(exc).__name__}
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


def main() -> None:
    print(json.dumps(run_diagnostics(), indent=2))


if __name__ == "__main__":
    main()
