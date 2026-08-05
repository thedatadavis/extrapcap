import time
from datetime import datetime, timezone
import modal
from modal_app.app import app, image, secrets
from modal_app.cf_client import CloudflareAPIClient
from modal_app.notifier import format_candidate_orders_text, format_error_alert_text, send_resend_email


@app.function(
    image=image,
    secrets=secrets,
    schedule=modal.Cron("45 13,15,19 * * 1-5"),
    timeout=600,
)
def candidate_review(execution_mode: str = "paper-submit"):
    """Candidate Review Cron: Market-hours option entry reviews (9:45 AM, 12:15 PM, 3:00 PM EDT)."""
    cf = CloudflareAPIClient()
    start_time = time.time()
    run_id = cf.register_run("candidate_review")

    try:
        from extrapcap.orchestration.basket_cycle import run_basket

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        results = run_basket(
            expiration_gte=today_str,
            max_candidates=10,
            execution_mode=execution_mode,
            fast_ev=True,
        )

        events = results.get("events", [])
        cf.append_events(events)

        orders_submitted = [e for e in events if e.get("journal", {}).get("kind") in ("paper_order", "order_submit")]
        cf.complete_run(
            run_id,
            summary={"evaluated": len(events), "orders_submitted": len(orders_submitted)},
            start_time=start_time,
        )

        # Smart filtering: send email ONLY if paper orders were submitted
        if orders_submitted:
            send_resend_email(
                subject=f"[Extrapcap] 🎯 {len(orders_submitted)} Paper Order(s) Submitted · {today_str}",
                text=format_candidate_orders_text(today_str, orders_submitted),
            )

        return {"status": "success", "evaluated": len(events), "submitted": len(orders_submitted)}

    except Exception as e:
        cf.fail_run(run_id, error=str(e), start_time=start_time)
        send_resend_email(
            subject="[Extrapcap] ⚠️ Candidate Review Failure Alert",
            text=format_error_alert_text("candidate_review", str(e)),
        )
        raise
