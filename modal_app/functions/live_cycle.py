import time
from datetime import date

import modal

from modal_app.base import app, image, secrets, state_mount
from modal_app.cf_client import CloudflareAPIClient


@app.function(image=image, secrets=secrets, volumes=state_mount, timeout=600)
def live_cycle(symbol: str, expiration_gte: str | None = None, expiration_lte: str | None = None):
    """Run one authenticated paper-account entry evaluation for a ticker."""
    cf = CloudflareAPIClient()
    start_time = time.time()
    run_id = cf.register_run(f"live_cycle_{symbol}")
    try:
        from extrapcap.orchestration.live_cycle import run_live_cycle
        result = run_live_cycle(symbol=symbol, trading_day=date.today(), expiration_gte=expiration_gte, expiration_lte=expiration_lte)
        cf.append_events([result], run_id=run_id)
        cf.complete_run(run_id, summary={"symbol": symbol, "status": result.get("status")}, start_time=start_time)
        return result
    except Exception as exc:
        cf.fail_run(run_id, error=str(exc), start_time=start_time)
        raise
