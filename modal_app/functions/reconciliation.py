import time
from datetime import datetime, timezone
import modal
from modal_app.base import app, image, secrets, state_mount
from modal_app.cf_client import CloudflareAPIClient
from modal_app.notifier import format_error_alert_text, format_reconciliation_text, send_resend_email


@app.function(
    image=image,
    secrets=secrets,
    volumes=state_mount,
    timeout=300,
)
def reconciliation():
    """Account Reconciliation Cron: Post-close account balance snapshot (8:30 PM UTC / 4:30 PM EDT)."""
    cf = CloudflareAPIClient()
    start_time = time.time()
    run_id = cf.register_run("reconciliation")

    try:
        from extrapcap.execution.alpaca import AlpacaPaperClient

        client = AlpacaPaperClient.from_env()
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

        # Send daily reconciliation snapshot email
        send_resend_email(
            subject=f"[Extrapcap] Reconciliation Report · {today_str} (${snapshot['equity']:,.0f})",
            text=format_reconciliation_text(snapshot),
        )

        return {"status": "success", "snapshot": snapshot}

    except Exception as e:
        cf.fail_run(run_id, error=str(e), start_time=start_time)
        send_resend_email(
            subject="[Extrapcap] ⚠️ Reconciliation Workflow Failure",
            text=format_error_alert_text("reconciliation", str(e)),
        )
        raise
