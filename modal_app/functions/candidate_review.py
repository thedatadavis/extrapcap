import time
from datetime import datetime, timezone

import modal

from modal_app.base import app, image, secrets, state_mount
from modal_app.cf_client import CloudflareAPIClient
from modal_app.notifier import format_candidate_orders_text, format_error_alert_text, send_resend_email


def _event_record(result: dict) -> dict:
    event = dict(result)
    while isinstance(event.get("result"), dict):
        nested = event.pop("result")
        event = {**event, **nested}
    status = str(event.get("status") or "").lower()
    event.setdefault("category", "orders" if status in {"accepted", "new", "filled", "submitted", "partially_filled"} else "signals")
    event.setdefault("kind", "paper_order" if event["category"] == "orders" else "candidate_review")
    return event


@app.function(image=image, secrets=secrets, volumes=state_mount, schedule=modal.Cron("45 13,15,19 * * 1-5"), timeout=600)
def candidate_review():
    cf = CloudflareAPIClient()
    start_time = time.time()
    run_id = cf.register_run("candidate_review")
    today = datetime.now(timezone.utc).date()
    try:
        from extrapcap.orchestration.basket_cycle import run_basket
        basket = cf.get_basket(as_of=today.isoformat())
        if not basket:
            raise RuntimeError("no current basket in Cloudflare D1")
        results = run_basket(basket, trading_day=today, dte_min=0, dte_max=21, preferred_dte=10)
        events = [_event_record(result) for result in results if isinstance(result, dict)]
        cf.append_events(events, run_id=run_id)
        errors = [event for event in events if event.get("status") == "error"]
        submitted = [event for event in events if event.get("category") == "orders"]
        cf.complete_run(run_id, summary={"evaluated": len(events), "submitted": len(submitted), "errors": len(errors)}, start_time=start_time)
        if submitted:
            send_resend_email(subject=f"[Extrapcap] Candidate Orders ({today.isoformat()})", text=format_candidate_orders_text(today.isoformat(), submitted))
        return {"status": "success" if not errors else "completed_with_errors", "evaluated": len(events), "submitted": len(submitted), "errors": len(errors)}
    except Exception as exc:
        cf.fail_run(run_id, error=str(exc), start_time=start_time)
        send_resend_email(subject="[Extrapcap] Candidate Review Failure", text=format_error_alert_text("Candidate Review", str(exc)))
        raise
