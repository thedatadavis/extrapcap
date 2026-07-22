from datetime import date, datetime, timezone
import json

from extrapcap.earnings import refresh_earnings_calendar
from extrapcap.events import (
    classify_headline,
    decision_from_csv,
    earnings_blackout,
    earnings_decision_from_csv,
)


def test_structural_news_and_earnings_are_hard_vetoes():
    assert classify_headline("Company faces DOJ investigation").allowed is False
    assert classify_headline("Analyst discusses market sentiment").allowed is True
    assert earnings_blackout(date(2026, 7, 22), date(2026, 7, 24)).allowed is False
    assert earnings_blackout(date(2026, 7, 22), date(2026, 8, 1)).allowed is True


def test_dated_event_file_is_a_hard_structural_veto(tmp_path):
    path = tmp_path / "events.csv"
    path.write_text("date,symbol,structural_risk\n2026-07-22,SPY,true\n", encoding="utf-8")
    decision = decision_from_csv(path, "SPY", date(2026, 7, 22))
    assert decision.allowed is False
    assert decision.category == "structural_risk"


def test_llm_headline_classification_cannot_clear_structural_terms(tmp_path):
    class FakeReviewer:
        def classify_headline(self, headline, symbol):
            return {"category": "noise_or_opinion", "structural_risk": False, "reason": "fake"}

    path = tmp_path / "events.csv"
    path.write_text(
        "date,symbol,structural_risk,headline\n"
        "2026-07-22,ABC,false,Company faces DOJ investigation\n",
        encoding="utf-8",
    )
    decision = decision_from_csv(path, "ABC", date(2026, 7, 22), FakeReviewer())
    assert decision.allowed is False
    assert decision.reason == "matched:doj"


def test_llm_headline_classification_can_veto_ambiguous_headline(tmp_path):
    class FakeReviewer:
        def classify_headline(self, headline, symbol):
            return {"category": "structural_risk", "structural_risk": True, "reason": "investigation"}

    path = tmp_path / "events.csv"
    path.write_text(
        "date,symbol,structural_risk,headline\n"
        "2026-07-22,ABC,false,Company announces a review\n",
        encoding="utf-8",
    )
    decision = decision_from_csv(path, "ABC", date(2026, 7, 22), FakeReviewer())
    assert decision.allowed is False
    assert decision.reason == "llm:investigation"


def test_earnings_refresh_writes_complete_versioned_window(tmp_path):
    def fake_fetcher(day):
        return (
            [{
                "date": day.isoformat(),
                "symbol": "ABC",
                "report_time": "after-hours",
                "company_name": "ABC Inc.",
                "fiscal_quarter_ending": "Jun/2026",
                "eps_forecast": "$1.00",
                "estimate_count": "4",
            }]
            if day == date(2026, 7, 24)
            else []
        )

    calendar, metadata_path, metadata = refresh_earnings_calendar(
        date(2026, 7, 22),
        tmp_path / "earnings.csv",
        retrieved_at=datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
        fetcher=fake_fetcher,
    )
    assert metadata["queried_dates"] == [
        "2026-07-19",
        "2026-07-20",
        "2026-07-21",
        "2026-07-22",
        "2026-07-23",
        "2026-07-24",
        "2026-07-25",
    ]
    decision = earnings_decision_from_csv(
        calendar,
        "ABC",
        date(2026, 7, 22),
        metadata_path=metadata_path,
        now=datetime(2026, 7, 22, 13, tzinfo=timezone.utc),
    )
    assert decision.allowed is False
    assert decision.reason == "earnings_blackout:2026-07-24"


def test_earnings_gate_fails_closed_on_stale_or_incomplete_coverage(tmp_path):
    calendar = tmp_path / "earnings.csv"
    calendar.write_text("date,symbol\n", encoding="utf-8")
    metadata_path = tmp_path / "earnings.csv.metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "source": "test",
                "retrieved_at": "2026-07-20T00:00:00+00:00",
                "queried_dates": ["2026-07-22"],
            }
        ),
        encoding="utf-8",
    )
    stale = earnings_decision_from_csv(
        calendar,
        "ABC",
        date(2026, 7, 22),
        metadata_path=metadata_path,
        now=datetime(2026, 7, 22, 13, tzinfo=timezone.utc),
    )
    assert stale.reason == "earnings_calendar_stale"
    metadata = json.loads(metadata_path.read_text())
    metadata["retrieved_at"] = "2026-07-22T12:00:00+00:00"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    incomplete = earnings_decision_from_csv(
        calendar,
        "ABC",
        date(2026, 7, 22),
        metadata_path=metadata_path,
        now=datetime(2026, 7, 22, 13, tzinfo=timezone.utc),
    )
    assert incomplete.reason == "earnings_calendar_incomplete"
