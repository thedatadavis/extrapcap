"""Single scheduled post-close workflow for the Modal five-cron limit."""

import modal

from modal_app.base import app, image, secrets, state_mount


@app.function(
    image=image,
    secrets=secrets,
    volumes=state_mount,
    schedule=modal.Cron("30 20 * * 1-5"),
    timeout=1200,
)
def end_of_day():
    """Reconcile first, then report and run the bounded improvement review."""
    from modal_app.functions.daily_report import daily_report
    from modal_app.functions.improvement_loop import improvement_loop
    from modal_app.functions.reconciliation import reconciliation

    return {
        "reconciliation": reconciliation.local(),
        "daily_report": daily_report.local(),
        "improvement_loop": improvement_loop.local(),
    }
