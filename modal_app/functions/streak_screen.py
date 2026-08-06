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
        from urllib.request import urlopen
        from extrapcap.universe.greenlist import SOURCE_URL, GreenlistFilter, filter_greenlist, _read_csv
        from extrapcap.universe.streak_screen import filter_tradable_basket

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Fetch greenlist registry from source URL
        with urlopen(SOURCE_URL, timeout=30) as response:
            raw_text = response.read().decode("utf-8")
        raw_rows = _read_csv(raw_text)
        accepted_greenlist, _ = filter_greenlist(raw_rows, GreenlistFilter())

        # Generate tradable basket
        basket_df = filter_tradable_basket(greenlist=accepted_greenlist)
        rows = basket_df.to_dict(orient="records")

        # Store greenlist universe metadata in D1
        cf.store_universe(accepted_greenlist)

        # Store in D1 with run_id provenance
        cf.store_basket(as_of=today_str, rows=rows, run_id=run_id)
        cf.complete_run(run_id, summary={"universe_count": len(accepted_greenlist), "tradable_candidates": len(rows)}, start_time=start_time)
        return {"status": "success", "universe_count": len(accepted_greenlist), "candidates_count": len(rows), "run_id": run_id}

    except Exception as e:
        cf.fail_run(run_id, error=str(e), start_time=start_time)
        raise
