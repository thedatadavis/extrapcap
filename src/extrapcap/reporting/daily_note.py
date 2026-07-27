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


def filter_step4_passed_events(events: list[dict]) -> list[dict]:
    """Filter ledger events so only tickers passing Step 4 (Hard Event Gate) are written up in daily reports."""
    vetoed_at_or_before_step4 = set()
    passed_step4_tickers = set()

    for event in events:
        ticker = str(event.get("ticker") or event.get("symbol") or "").upper()
        if not ticker:
            continue
        kind = str(event.get("kind", ""))
        reason = str(event.get("reason", "")).lower()
        status = str(event.get("status", "")).lower()
        event_dec = event.get("event_decision")
        sig_gate = event.get("signal_gate") or (event.get("selection_context") or {}).get("signal_gate")

        is_pre_step4_veto = (
            kind in {"data_integrity_gate", "entry_signal_gate", "event_gate"}
            or (status == "vetoed" and any(k in reason for k in ("streak", "greenlist", "event_gate", "earnings", "news")))
            or (isinstance(event_dec, dict) and not event_dec.get("allowed", True))
            or (isinstance(sig_gate, dict) and not sig_gate.get("allowed", True))
        )

        if is_pre_step4_veto:
            vetoed_at_or_before_step4.add(ticker)
        else:
            passed_step4_tickers.add(ticker)

    qualified_tickers = passed_step4_tickers - vetoed_at_or_before_step4

    filtered = []
    for event in events:
        ticker = str(event.get("ticker") or event.get("symbol") or "").upper()
        if not ticker or ticker in qualified_tickers:
            filtered.append(event)
    return filtered


def deterministic_summary(events: list[dict], trading_day: str) -> dict:
    """Create the facts supplied to an optional LLM; no external facts are inferred."""
    filtered_events = filter_step4_passed_events(events)
    statuses = Counter(event_status(event) for event in filtered_events)
    categories = Counter(str(event.get("category", "unknown")) for event in filtered_events)
    anomalies = []
    if not filtered_events:
        anomalies.append("no_ledger_events")
    if statuses.get("escalate") or statuses.get("escalated"):
        anomalies.append("escalated_decision_present")
    if statuses.get("rejected") or statuses.get("no-go"):
        anomalies.append("rejected_candidate_present")
    if any(event.get("execution_status") == "submitted" for event in filtered_events):
        anomalies.append("paper_order_submitted_review_fills")
    return {
        "trading_day": trading_day,
        "event_count": len(filtered_events),
        "categories": dict(sorted(categories.items())),
        "statuses": dict(sorted(statuses.items())),
        "deterministic_anomalies": anomalies,
    }


def build_daily_note(events: list[dict], trading_day: str, reviewer=None) -> dict:
    """Build an observable daily note; an LLM is advisory and fail-closed."""
    filtered_events = filter_step4_passed_events(events)
    summary = deterministic_summary(filtered_events, trading_day)
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
