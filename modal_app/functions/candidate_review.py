import os
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
        basket_path = "data/universe/tradable-basket.csv"
        target_basket = basket_path if os.path.exists(basket_path) else "data/universe/greenlist-20260731T082041Z.csv"

        results = run_basket(
            basket=target_basket,
            expiration_gte=today_str,
            max_candidates=10,
            fast_ev=True,
        )

        events = results if isinstance(results, list) else []
        cf.append_events(events)

        orders_submitted = [e for e in events if isinstance(e, dict) and (e.get("kind") in ("paper_order", "order_submit") or e.get("status") in ("filled", "executed", "submitted"))]
        cf.complete_run(
            run_id,
            summary={"evaluated": len(events), "orders_submitted": len(orders_submitted)},
            start_time=start_time,
        )

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
