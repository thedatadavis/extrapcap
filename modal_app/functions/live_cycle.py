import time
from datetime import datetime, timezone
import modal
from modal_app.app import app, image, secrets
from modal_app.cf_client import CloudflareAPIClient


@app.function(
    image=image,
    secrets=secrets,
    timeout=600,
)
def live_cycle(
    symbol: str,
    expiration_gte: str = None,
    expiration_lte: str = None,
    execution_mode: str = "dry-run",
):
    """Ad-hoc single-ticker live paper cycle."""
    cf = CloudflareAPIClient()
    start_time = time.time()
    run_id = cf.register_run(f"live_cycle_{symbol}")

    try:
        from extrapcap.orchestration.live_cycle import run_live_cycle

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        results = run_live_cycle(
            symbol=symbol,
            expiration_gte=expiration_gte or today_str,
            expiration_lte=expiration_lte,
            execution_mode=execution_mode,
            fast_ev=True,
        )

        events = results.get("events", [])
        cf.append_events(events)
        cf.complete_run(run_id, summary={"symbol": symbol, "events_generated": len(events)}, start_time=start_time)
        return {"status": "success", "symbol": symbol, "events": events}

    except Exception as e:
        cf.fail_run(run_id, error=str(e), start_time=start_time)
        raise
