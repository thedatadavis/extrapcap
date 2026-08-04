import time
from datetime import datetime, timezone
import modal
from modal_app.app import app, image, secrets
from modal_app.cf_client import CloudflareAPIClient


@app.function(
    image=image,
    secrets=secrets,
    schedule=modal.Cron("15 22 * * 1-5"),
    timeout=600,
)
def improvement_loop():
    """Policy Improvement Learner Cron (10:15 PM UTC / 6:15 PM EDT)."""
    cf = CloudflareAPIClient()
    start_time = time.time()
    run_id = cf.register_run("improvement_loop")

    try:
        from extrapcap.improvement import run_improvement_cycle

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        proposal = run_improvement_cycle(as_of_date=today_str)

        event = {
            "journal": {
                "event_id": f"evt-proposal-{today_str}",
                "trading_day": today_str,
                "category": "proposals",
                "kind": "policy_improvement",
                "title": f"Policy Improvement Proposal · {today_str}",
                "status": proposal.get("status", "recorded"),
                "reason": proposal.get("rationale", "Policy improvement evaluation complete."),
            },
            "proposal": proposal,
        }

        cf.append_events([event])
        cf.complete_run(run_id, summary={"proposal_status": proposal.get("status")}, start_time=start_time)
        return {"status": "success", "proposal": proposal}

    except Exception as e:
        cf.fail_run(run_id, error=str(e), start_time=start_time)
        raise
