from extrapcap.reporting.daily_note import build_daily_note, deterministic_summary


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
