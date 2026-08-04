import time
from datetime import datetime, timezone
import modal
from modal_app.app import app, image, secrets
from modal_app.cf_client import CloudflareAPIClient


@app.function(
    image=image,
    secrets=secrets,
    schedule=modal.Cron("30 20 * * 1-5"),
    timeout=300,
)
def reconciliation():
    """Account Reconciliation Cron: Post-close account balance snapshot (8:30 PM UTC / 4:30 PM EDT)."""
    cf = CloudflareAPIClient()
    start_time = time.time()
    run_id = cf.register_run("reconciliation")

    try:
        from extrapcap.secrets import require_paper_credentials
        from extrapcap.execution.alpaca import AlpacaPaperClient

        key, secret = require_paper_credentials()
        client = AlpacaPaperClient(key, secret)
        account = client.account()

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        snapshot = {
            "as_of": today_str,
            "equity": float(account.get("equity", 0.0)),
            "cash": float(account.get("cash", 0.0)),
            "buying_power": float(account.get("buying_power", 0.0)),
            "portfolio_value": float(account.get("portfolio_value", account.get("equity", 0.0))),
            "daily_pnl": float(account.get("daily_pnl", 0.0)),
            "payload": account,
        }

        cf.record_account(snapshot)
        cf.complete_run(run_id, summary={"equity": snapshot["equity"], "cash": snapshot["cash"]}, start_time=start_time)
        return {"status": "success", "snapshot": snapshot}

    except Exception as e:
        cf.fail_run(run_id, error=str(e), start_time=start_time)
        raise
