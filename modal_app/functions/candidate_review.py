import time
from datetime import datetime, timezone

import modal

from modal_app.base import app, image, secrets, state_mount
from modal_app.cf_client import CloudflareAPIClient
from modal_app.notifier import (
    format_candidate_orders_text,
    format_error_alert_text,
    send_resend_email,
)


def _event_record(result: dict) -> dict:
    event = dict(result)
    while isinstance(event.get("result"), dict):
        nested = event.pop("result")
        event = {**event, **nested}
    status = str(event.get("status") or "").lower()
    event.setdefault(
        "category",
        "orders"
        if status in {"accepted", "new", "pending_new", "filled", "submitted", "partially_filled"}
        else "signals",
    )
    event.setdefault("kind", "paper_order" if event["category"] == "orders" else "candidate_review")
    return event


def _attach_asset_identities(basket: list[dict]) -> tuple[list[dict], int]:
    from extrapcap.data.alpaca_market import AlpacaMarketData

    symbols = [str(row.get("symbol") or row.get("ticker") or "").strip().upper() for row in basket]
    identities = AlpacaMarketData().resolve_assets(symbols, strict=False)
    enriched = []
    for row, symbol in zip(basket, symbols, strict=True):
        asset = identities.get(symbol)
        if asset:
            enriched.append(
                {**row, "alpaca_symbol": asset["symbol"], "alpaca_asset_id": asset["id"]}
            )
    return enriched, len(set(symbols)) - len(identities)


@app.function(
    image=image,
    secrets=secrets,
    volumes=state_mount,
    schedule=modal.Cron("45 13,15,19 * * 1-5"),
    timeout=2400,
)
def candidate_review():
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
    run_id = cf.register_run("candidate_review")
    try:
        from extrapcap.orchestration.basket_cycle import run_basket

        if paper_client.positions() or paper_client.open_orders():
            summary = {"skipped": True, "reason": "paper_exposure_already_exists"}
            cf.complete_run(run_id, summary=summary, start_time=start_time)
            return {"status": "skipped", **summary}
        basket = cf.get_basket(as_of=today.isoformat()) or cf.get_basket()
        if not basket:
            raise RuntimeError("no current basket in Cloudflare D1")
        basket, unresolved_assets = _attach_asset_identities(basket)
        results = run_basket(
            basket,
            trading_day=today,
            dte_min=0,
            dte_max=21,
            preferred_dte=10,
            max_submissions=1,
        )
        events = [_event_record(result) for result in results if isinstance(result, dict)]
        for event in events:
            if event.get("category") != "orders":
                continue
            try:
                cf.record_order(event, run_id=run_id)
            except Exception:
                if event.get("order_id"):
                    paper_client.cancel_order(str(event["order_id"]))
                raise
        cf.append_events(events, run_id=run_id)
        errors = [event for event in events if event.get("status") == "error"]
        submitted = [event for event in events if event.get("category") == "orders"]
        deferred = sum(int(event.get("deferred") or 0) for event in events)
        evaluated = len(
            [event for event in events if event.get("kind") != "basket_selection_summary"]
        )
        cf.complete_run(
            run_id,
            summary={
                "evaluated": evaluated,
                "submitted": len(submitted),
                "errors": len(errors),
                "deferred": deferred,
                "unresolved_assets": unresolved_assets,
            },
            start_time=start_time,
        )
        if submitted:
            send_resend_email(
                subject=f"[Extrapcap] Candidate Orders ({today.isoformat()})",
                text=format_candidate_orders_text(today.isoformat(), submitted),
            )
        return {
            "status": "success" if not errors else "completed_with_errors",
            "evaluated": evaluated,
            "submitted": len(submitted),
            "errors": len(errors),
            "deferred": deferred,
            "unresolved_assets": unresolved_assets,
        }
    except Exception as exc:
        cf.fail_run(run_id, error=str(exc), start_time=start_time)
        send_resend_email(
            subject="[Extrapcap] Candidate Review Failure",
            text=format_error_alert_text("Candidate Review", str(exc)),
        )
        raise
