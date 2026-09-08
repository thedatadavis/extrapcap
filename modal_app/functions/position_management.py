import time
from datetime import datetime, timezone
import modal
from modal_app.base import app, image, secrets, state_mount
from modal_app.cf_client import CloudflareAPIClient
from modal_app.notifier import (
    format_error_alert_text,
    format_position_exits_text,
    send_resend_email,
)


@app.function(
    image=image,
    secrets=secrets,
    volumes=state_mount,
    schedule=modal.Cron("*/30 13-20 * * 1-5"),
    timeout=300,
)
def position_management():
    """Position Management Cron: Every 30 minutes during market hours."""
    today = datetime.now(timezone.utc).date()
    if today.weekday() >= 5:
        return {"status": "skipped", "reason": "weekend_market_closed"}

    from extrapcap.execution.alpaca import AlpacaPaperClient

    paper_client = AlpacaPaperClient.from_env()
    if hasattr(paper_client, "clock"):
        clock = paper_client.clock()
        if not clock.get("is_open"):
            return {
                "status": "skipped",
                "reason": "broker_market_clock_closed",
                "next_open": clock.get("next_open"),
            }

    cf = CloudflareAPIClient()
    start_time = time.time()
    run_id = cf.register_run("position_management")

    try:
        from extrapcap.options_data import AlpacaOptionsData
        from extrapcap.execution.position_manager import manage_live_positions
        from extrapcap.execution.broker_sync import synchronize_broker_state

        paper_client = AlpacaPaperClient.from_env()
        options_client = AlpacaOptionsData.from_env()

        today_str = today.strftime("%Y-%m-%d")
        sync = synchronize_broker_state(paper_client, cf, run_id=run_id)
        positions = cf.get_active_positions()
        records = manage_live_positions(
            paper_client, options_client, positions=positions, as_of=today
        )

        # Report events and closed positions to Cloudflare D1
        closed_count = 0
        events_to_post = []
        exit_events = []

        for record in records:
            events_to_post.append(record)
            if record.get("legs") is not None or record.get("metadata") is not None:
                cf.update_position(
                    record["position_id"], legs=record.get("legs"), metadata=record.get("metadata")
                )
            if record.get("status") == "broker_closed":
                pos_id = record.get("position_id")
                reason = record.get("reason", "Exit rule triggered")
                if pos_id:
                    cf.close_position(pos_id, reason, run_id=run_id)
                closed_count += 1
                exit_events.append(record)

        cf.append_events(events_to_post, run_id=run_id)
        cf.complete_run(
            run_id,
            summary={"evaluated": len(records), "exits_triggered": closed_count, **sync},
            start_time=start_time,
        )

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
