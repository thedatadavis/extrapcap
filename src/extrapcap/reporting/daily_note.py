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


def deterministic_wsj_summary(summary: dict) -> str:
    date_str = summary.get("trading_day", "")
    evaluated = summary.get("evaluated_basket_count", 0)
    gate_passed = summary.get("streak_gate_passed_count", 0)
    prob_passed = summary.get("reversion_prob_passed_count", 0)
    orders = summary.get("orders_submitted_count", 0)
    recon = summary.get("reconciliation", {})
    pos_count = recon.get("positions_count", 0)

    p1 = (
        f"On {date_str}, Extrapolation Capital's two-sided Bayesian Fast EV quantitative model screened "
        f"{evaluated} securities across the active trading universe relative to SPY benchmark return streaks. "
        f"{gate_passed} tickers satisfied statistical streak boundaries (|Z| \u2265 2.0), and {prob_passed} candidates "
        f"cleared the empirical win probability threshold (P > 0.51)."
    )
    if orders == 0:
        p2 = (
            f"Following option chain pricing and spread liquidity evaluation, zero new paper vertical spread orders were submitted as no candidates "
            f"achieved positive net expected value (EV \u2265 $10.00). Portfolio reconciliation confirmed {pos_count} active position exposures, "
            f"preserving capital in neutral market conditions."
        )
    else:
        p2 = (
            f"Following option chain pricing, the execution engine submitted {orders} new paper order(s) meeting positive net expected value "
            f"parameters. Portfolio reconciliation confirmed {pos_count} active position(s)."
        )
    return f"{p1}\n\n{p2}"


def deterministic_summary(events: list[dict], trading_day: str) -> dict:
    """Create the facts supplied to an optional LLM; no external facts are inferred."""
    filtered_events = filter_step4_passed_events(events)
    statuses = Counter(event_status(event) for event in filtered_events)
    categories = Counter(str(event.get("category", "unknown")) for event in filtered_events)

    evaluated_tickers = set()
    gate_passed_tickers = set()
    prob_passed_tickers = set()
    submitted_tickers = set()
    reconciliation_data = {}

    for event in events:
        ticker = str(event.get("ticker") or (event.get("selection_context") or {}).get("ticker") or "").upper()
        if ticker:
            evaluated_tickers.add(ticker)

        ctx = event.get("selection_context") if isinstance(event.get("selection_context"), dict) else {}
        sig_gate = ctx.get("signal_gate") if isinstance(ctx.get("signal_gate"), dict) else {}
        if sig_gate.get("allowed") is True or event.get("reason") == "approved":
            if ticker:
                gate_passed_tickers.add(ticker)

        prob = event.get("model_probability") or ctx.get("reversion_probability") or ctx.get("model_probability")
        if isinstance(prob, (int, float)) and prob > 0.51:
            if ticker:
                prob_passed_tickers.add(ticker)

        status = str(event.get("status") or event.get("decision") or "").lower()
        if status in {"submitted", "paper_order", "go"}:
            if ticker:
                submitted_tickers.add(ticker)

        if event.get("kind") == "reconciliation":
            reconciliation_data = {
                "account": event.get("account"),
                "positions_count": len(event.get("positions") or []),
                "open_orders_count": len(event.get("open_orders") or []),
            }

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
        "evaluated_basket_count": len(evaluated_tickers),
        "streak_gate_passed_count": len(gate_passed_tickers),
        "reversion_prob_passed_count": len(prob_passed_tickers),
        "orders_submitted_count": len(submitted_tickers),
        "reconciliation": reconciliation_data,
        "categories": dict(sorted(categories.items())),
        "statuses": dict(sorted(statuses.items())),
        "deterministic_anomalies": anomalies,
    }


def build_daily_note(events: list[dict], trading_day: str, reviewer=None) -> dict:
    """Build an observable daily note; an LLM is advisory and fail-closed."""
    filtered_events = filter_step4_passed_events(events)
    summary = deterministic_summary(events, trading_day)
    note = {
        "kind": "daily_portfolio_note",
        "summary": summary,
        "note": "Paper-trading activity was replayed from the append-only ledger.",
        "wsj_summary": deterministic_wsj_summary(summary),
        "anomalies": summary["deterministic_anomalies"],
        "risk_posture": "watch" if summary["deterministic_anomalies"] else "normal",
        "provider": "deterministic",
    }
    if reviewer is not None:
        judgment = reviewer.daily_note(summary)
        note.update({key: judgment[key] for key in ("note", "wsj_summary", "anomalies", "risk_posture", "reason", "provider", "model") if key in judgment and judgment[key] is not None})
        note["llm_input"] = summary
        note["llm_output"] = judgment
    return note
