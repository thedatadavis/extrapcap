from __future__ import annotations

from collections import Counter


def event_status(event: dict) -> str:
    journal = event.get("journal") if isinstance(event.get("journal"), dict) else {}
    judgment = event.get("judgment") if isinstance(event.get("judgment"), dict) else {}
    output = event.get("output") if isinstance(event.get("output"), dict) else {}
    return str(
        event.get("status")
        or event.get("decision")
        or journal.get("status")
        or judgment.get("decision")
        or output.get("decision")
        or "unknown"
    )


def deterministic_summary(events: list[dict], trading_day: str) -> dict:
    """Create the facts supplied to an optional LLM; no external facts are inferred."""
    statuses = Counter(event_status(event) for event in events)
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
