import time
from datetime import datetime, timezone
import modal
from modal_app.app import app, image, secrets
from modal_app.cf_client import CloudflareAPIClient
from modal_app.notifier import format_error_alert_text, format_position_exits_text, send_resend_email


@app.function(
    image=image,
    secrets=secrets,
    schedule=modal.Cron("*/30 13-20 * * 1-5"),
    timeout=300,
)
def position_management():
    """Position Management Cron: Every 30 minutes during market hours."""
    cf = CloudflareAPIClient()
    start_time = time.time()
    run_id = cf.register_run("position_management")

    try:
        from extrapcap.secrets import require_paper_credentials
        from extrapcap.execution.alpaca import AlpacaPaperClient
        from extrapcap.options_data import AlpacaOptionsData
        from extrapcap.execution.position_manager import manage_live_positions

        key, secret = require_paper_credentials()
        paper_client = AlpacaPaperClient.from_env()
        options_client = AlpacaOptionsData(key, secret)

        # Execute position manager loop
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        records = manage_live_positions(
            as_of_date=today_str,
            paper_client=paper_client,
            options_client=options_client,
        )

        # Report events and closed positions to Cloudflare D1
        closed_count = 0
        events_to_post = []
        exit_events = []

        for record in records:
            events_to_post.append(record)
            if record.get("journal", {}).get("kind") in ("position_exit", "position_close", "exit_signal"):
                pos_id = record.get("position_id")
                reason = record.get("journal", {}).get("reason", "Exit rule triggered")
                if pos_id:
                    cf.close_position(pos_id, reason)
                closed_count += 1
                exit_events.append(record)

        cf.append_events(events_to_post)
        cf.complete_run(run_id, summary={"evaluated": len(records), "exits_triggered": closed_count}, start_time=start_time)

        # Smart filtering: send email ONLY if positions were closed
        if closed_count > 0:
            send_resend_email(
                subject=f"[Extrapcap] 🛑 {closed_count} Position Exit(s) Executed · {today_str}",
                text=format_position_exits_text(today_str, exit_events),
            )

        return {"status": "success", "evaluated": len(records), "closed": closed_count}

    except Exception as e:
        cf.fail_run(run_id, error=str(e), start_time=start_time)
        send_resend_email(
            subject="[Extrapcap] ⚠️ Position Management Failure Alert",
            text=format_error_alert_text("position_management", str(e)),
        )
        raise
