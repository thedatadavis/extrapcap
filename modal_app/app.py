"""Deployment entry point that registers every Extrapcap Modal workflow."""

from modal_app.base import app, image, secrets, state_mount, state_volume

# Importing the deployment entry point always registers every function.  The
# function modules import modal_app.base instead, so running one module directly
# does not recursively register the full app or create name collisions.
from modal_app.functions import (  # noqa: F401
    candidate_review,
    daily_report,
    data_refresh,
    end_of_day,
    improvement_loop,
    live_cycle,
    position_management,
    reconciliation,
    streak_screen,
)

__all__ = ["app", "image", "secrets", "state_mount", "state_volume"]
