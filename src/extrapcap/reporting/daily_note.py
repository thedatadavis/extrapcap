from __future__ import annotations

from collections import Counter


def deterministic_summary(events: list[dict], trading_day: str) -> dict:
    """Create the facts supplied to an optional LLM; no external facts are inferred."""
    statuses = Counter(str(event.get("status", event.get("decision", "unknown"))) for event in events)
    categories = Counter(str(event.get("category", "unknown")) for event in events)
    anomalies = []
    if not events:
        anomalies.append("no_ledger_events")
    if statuses.get("escalate") or statuses.get("escalated"):
        anomalies.append("escalated_decision_present")
    if statuses.get("rejected") or statuses.get("no-go"):
        anomalies.append("rejected_candidate_present")
    if any(event.get("execution_status") == "submitted" for event in events):
        anomalies.append("paper_order_submitted_review_fills")
    return {
        "trading_day": trading_day,
        "event_count": len(events),
        "categories": dict(sorted(categories.items())),
        "statuses": dict(sorted(statuses.items())),
        "deterministic_anomalies": anomalies,
    }


def build_daily_note(events: list[dict], trading_day: str, reviewer=None) -> dict:
    """Build an observable daily note; an LLM is advisory and fail-closed."""
    summary = deterministic_summary(events, trading_day)
    note = {
        "kind": "daily_portfolio_note",
        "summary": summary,
        "note": "Paper-trading activity was replayed from the append-only ledger.",
        "anomalies": summary["deterministic_anomalies"],
        "risk_posture": "watch" if summary["deterministic_anomalies"] else "normal",
        "provider": "deterministic",
    }
    if reviewer is not None:
        judgment = reviewer.daily_note(summary)
        note.update({key: judgment[key] for key in ("note", "anomalies", "risk_posture", "reason", "provider", "model") if key in judgment})
        note["llm_input"] = summary
        note["llm_output"] = judgment
    return note
