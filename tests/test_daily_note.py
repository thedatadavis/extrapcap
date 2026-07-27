from extrapcap.reporting.daily_note import build_daily_note, deterministic_summary, event_status


def test_daily_note_is_deterministic_without_reviewer():
    events = [{"category": "candidates", "status": "escalate"}]
    summary = deterministic_summary(events, "2026-07-22")
    note = build_daily_note(events, "2026-07-22")
    assert summary["deterministic_anomalies"] == ["escalated_decision_present"]
    assert note["risk_posture"] == "watch"
    assert note["provider"] == "deterministic"


def test_daily_note_reviewer_output_is_recorded():
    class FakeReviewer:
        def daily_note(self, summary):
            return {
                "note": "Review the escalation.",
                "anomalies": ["escalated_decision_present"],
                "risk_posture": "escalate",
                "reason": "bounded test output",
                "provider": "nebius",
                "model": "test-model",
            }

    note = build_daily_note([], "2026-07-22", FakeReviewer())
    assert note["provider"] == "nebius"
    assert note["llm_input"]["event_count"] == 0
    assert note["llm_output"]["risk_posture"] == "escalate"


def test_event_status_reads_journal_and_judgment_envelopes():
    assert event_status({"journal": {"status": "dry_run"}}) == "dry_run"
    assert event_status({"judgment": {"decision": "go"}}) == "go"


def test_filter_step4_passed_events_filters_pre_step4_vetoed_tickers():
    from extrapcap.reporting.daily_note import filter_step4_passed_events

    events = [
        # Ticker A: fails at Step 3 signal gate
        {"ticker": "AAPL", "kind": "entry_signal_gate", "status": "vetoed", "reason": "core_requires_negative_relative_streak"},
        # Ticker B: fails at Step 4 Nasdaq earnings gate
        {"ticker": "MSFT", "kind": "event_gate", "status": "vetoed", "reason": "earnings_blackout"},
        # Ticker C: passes Step 4, reaches Step 5 candidate review
        {"ticker": "NVDA", "kind": "candidate", "status": "go", "event_decision": {"allowed": True}},
        {"ticker": "NVDA", "kind": "order", "status": "submitted"},
        # System event with no ticker
        {"category": "summary", "kind": "daily_operations_report"},
    ]
    filtered = filter_step4_passed_events(events)
    tickers = {e.get("ticker") for e in filtered if e.get("ticker")}
    assert tickers == {"NVDA"}
    assert len(filtered) == 3  # 2 NVDA events + 1 system event

