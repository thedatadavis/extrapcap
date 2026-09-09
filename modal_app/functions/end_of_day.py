"""Single scheduled post-close workflow for the Modal five-cron limit."""

from datetime import datetime, timezone
import modal

from modal_app.base import app, image, secrets, state_mount


@app.function(
    image=image,
    secrets=secrets,
    volumes=state_mount,
    schedule=modal.Cron("30 16 * * 1-5", timezone="America/New_York"),
    timeout=1200,
)
def end_of_day():
    """Reconcile first, then report and run the bounded improvement review."""
    today = datetime.now(timezone.utc).date()
    if today.weekday() >= 5:
        return {"status": "skipped", "reason": "weekend_market_closed"}

    from extrapcap.execution.alpaca import AlpacaPaperClient

    paper_client = AlpacaPaperClient.from_env()
    if hasattr(paper_client, "calendar"):
        sessions = paper_client.calendar(start=today, end=today)
        if not sessions:
            return {"status": "skipped", "reason": "market_holiday_no_session"}

    from modal_app.functions.daily_report import daily_report
    from modal_app.functions.improvement_loop import improvement_loop
    from modal_app.functions.reconciliation import reconciliation

    return {
        "reconciliation": reconciliation.local(),
        "daily_report": daily_report.local(),
        "improvement_loop": improvement_loop.local(),
    }
