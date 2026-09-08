import time
from datetime import datetime, timezone
import modal
from modal_app.base import app, image, secrets, state_mount
from modal_app.cf_client import CloudflareAPIClient
from modal_app.notifier import format_daily_report_text, format_error_alert_text, send_resend_email


@app.function(
    image=image,
    secrets=secrets,
    volumes=state_mount,
    timeout=600,
)
def daily_report():
    """Daily EOD Operations Report Cron (8:45 PM UTC / 4:45 PM EDT)."""
    today = datetime.now(timezone.utc).date()
    if today.weekday() >= 5:
        return {"status": "skipped", "reason": "weekend_market_closed"}

    cf = CloudflareAPIClient()
    start_time = time.time()
    run_id = cf.register_run("daily_report")

    try:
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        basket = cf.get_basket(as_of=today_str) or cf.get_basket()
        today_orders = [
            order
            for order in cf.get_orders()
            if str(order.get("created_at") or order.get("submitted_at") or "")[:10] == today_str
        ]
        submitted_count = len(today_orders)
        filled_count = len(
            [o for o in today_orders if str(o.get("status") or "").lower() == "filled"]
        )
        passed_prob_count = len(
            [b for b in basket if float(b.get("reversion_probability") or 0) >= 0.50]
        )

        report = {
            "summary": f"{len(basket)} current opportunities evaluated, {submitted_count} orders submitted ({filled_count} filled)",
            "evaluated_count": len(basket),
            "passed_gate_count": len(basket),
            "passed_prob_count": passed_prob_count,
            "submitted_count": submitted_count,
            "filled_count": filled_count,
        }

        event = {
            "journal": {
                "event_id": f"evt-report-{today_str}",
                "trading_day": today_str,
                "category": "reports",
                "kind": "daily_report",
                "title": f"Daily Operations Report · {today_str}",
                "status": "completed",
                "reason": report.get("summary", "Daily report generated."),
            },
            "report": report,
        }

        cf.append_events([event])
        cf.complete_run(
            run_id,
            summary={
                "report_date": today_str,
                "evaluated": len(basket),
                "submitted": submitted_count,
                "filled": filled_count,
            },
            start_time=start_time,
        )

        # Send daily executive report email
        summary_info = {
            "evaluated": report.get("evaluated_count", 0),
            "passed_gate": report.get("passed_gate_count", 0),
            "passed_prob": report.get("passed_prob_count", 0),
            "submitted": report.get("submitted_count", 0),
            "filled": report.get("filled_count", 0),
            "wsj_summary": report.get("portfolio_note", {}).get("wsj_summary")
            or report.get("summary", "No market commentary recorded."),
        }

        send_resend_email(
            subject=f"[Extrapcap] Daily Executive Report · {today_str}",
            text=format_daily_report_text(today_str, summary_info, []),
        )

        return {"status": "success", "report_date": today_str}

    except Exception as e:
        cf.fail_run(run_id, error=str(e), start_time=start_time)
        send_resend_email(
            subject="[Extrapcap] ⚠️ Daily Report Failure Alert",
            text=format_error_alert_text("daily_report", str(e)),
        )
        raise
