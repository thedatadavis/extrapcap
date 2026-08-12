"""Authenticated HTTP bridge from the Cloudflare admin console to Modal."""

import hmac
import os

from fastapi import Header, HTTPException
import modal

from modal_app.base import app, image


ADMIN_WORKFLOWS = {
    "candidate_review",
    "position_management",
    "reconciliation",
    "daily_report",
    "data_refresh",
    "streak_screen",
}


@app.function(image=image, secrets=[modal.Secret.from_name("admin-trigger")], timeout=30)
@modal.fastapi_endpoint(method="POST", label="admin-trigger")
def admin_trigger(payload: dict, authorization: str = Header(default="")) -> dict:
    expected = os.environ.get("ADMIN_TRIGGER_TOKEN", "")
    supplied = authorization.removeprefix("Bearer ").strip()
    if not expected or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid admin trigger token")
    workflow = str(payload.get("workflow") or "").strip()
    if workflow not in ADMIN_WORKFLOWS:
        raise HTTPException(status_code=400, detail="unsupported workflow")
    function_call = modal.Function.from_name("extrapcap", workflow).spawn()
    return {"accepted": True, "workflow": workflow, "function_call_id": function_call.object_id}
