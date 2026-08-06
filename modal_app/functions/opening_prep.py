import time
from datetime import datetime, timezone
import modal
from modal_app.app import app, image, secrets
from modal_app.cf_client import CloudflareAPIClient


@app.function(
    image=image,
    secrets=secrets,
    schedule=modal.Cron("0 13 * * 1-5"),
    timeout=600,
)
def opening_prep():
    """Opening Prep Cron: Pre-market candidate evaluation in dry-run mode (1:00 PM UTC / 9:00 AM EDT)."""
    cf = CloudflareAPIClient()
    start_time = time.time()
    run_id = cf.register_run("opening_prep")

    try:
        from extrapcap.orchestration.basket_cycle import run_basket

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Fetch dynamic active basket directly from Cloudflare D1 database
        d1_basket = cf.get_basket()
        if not d1_basket:
            raise RuntimeError("No active basket found in Cloudflare D1 database for opening_prep.")

        results = run_basket(
            basket=d1_basket,
            expiration_gte=today_str,
            max_candidates=10,
            review_phase="opening_prep",
            fast_ev=True,
            prep_only=True,
        )

        events = results if isinstance(results, list) else []
        cf.append_events(events)
        cf.complete_run(run_id, summary={"evaluated": len(events)}, start_time=start_time)
        return {"status": "success", "evaluated": len(events)}

    except Exception as e:
        cf.fail_run(run_id, error=str(e), start_time=start_time)
        raise
