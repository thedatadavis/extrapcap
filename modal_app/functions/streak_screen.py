import time
from datetime import datetime, timezone
import modal
from modal_app.app import app, image, secrets
from modal_app.cf_client import CloudflareAPIClient


@app.function(
    image=image,
    secrets=secrets,
    schedule=modal.Cron("45 5 * * 1-5"),
    timeout=300,
)
def streak_screen():
    """Streak Screening Cron: Filter greenlist symbols by relative streak return and robust Z-score (5:45 AM UTC)."""
    cf = CloudflareAPIClient()
    start_time = time.time()
    run_id = cf.register_run("streak_screen")

    try:
        from extrapcap.universe.greenlist import build_greenlist_snapshot
        from extrapcap.universe.streak_screen import filter_tradable_basket

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        greenlist = build_greenlist_snapshot()

        # Generate tradable basket
        basket_df = filter_tradable_basket(greenlist=greenlist)
        rows = basket_df.to_dict(orient="records")

        # Store in D1
        cf.store_basket(as_of=today_str, rows=rows)
        cf.complete_run(run_id, summary={"tradable_candidates": len(rows)}, start_time=start_time)
        return {"status": "success", "candidates_count": len(rows)}

    except Exception as e:
        cf.fail_run(run_id, error=str(e), start_time=start_time)
        raise
