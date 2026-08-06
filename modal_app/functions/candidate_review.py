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
def candidate_review():
    """Candidate Review Cron: Market-hours option entry reviews (9:45 AM, 12:15 PM, 3:00 PM EDT)."""
    cf = CloudflareAPIClient()
    start_time = time.time()
    run_id = cf.register_run("candidate_review")

    try:
        from extrapcap.orchestration.basket_cycle import run_basket

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Fetch dynamic active basket directly from Cloudflare D1 database
        d1_basket = cf.get_basket()
        if not d1_basket:
            raise RuntimeError("No active basket found in Cloudflare D1 database for candidate_review.")

        results = run_basket(
            basket=d1_basket,
            expiration_gte=today_str,
            fast_ev=True,
        )

        events = results if isinstance(results, list) else []
        cf.append_events(events, run_id=run_id)

        orders_submitted = [
            e for e in events
            if isinstance(e, dict) and (e.get("kind") in ("paper_order", "order_submit") or e.get("status") in ("filled", "executed", "submitted"))
        ]
        cf.complete_run(
            run_id,
            summary={"evaluated": len(events), "submitted": len(orders_submitted)},
            start_time=start_time,
        )

        if orders_submitted:
            email_body = format_candidate_orders_text(orders_submitted, today_str)
            send_resend_email(
                subject=f"[Extrapcap] 🎯 Candidate Orders Executed ({today_str})",
                text_content=email_body,
            )

        return {"status": "success", "evaluated": len(events), "submitted": len(orders_submitted)}

    except Exception as e:
        cf.fail_run(run_id, error=str(e), start_time=start_time)
        alert_body = format_error_alert_text("Candidate Review", str(e))
        send_resend_email(
            subject="[Extrapcap] ⚠️ Candidate Review Failure Alert",
            text_content=alert_body,
        )
        raise
