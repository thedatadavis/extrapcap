from datetime import date

from extrapcap.events import classify_headline, decision_from_csv, earnings_blackout


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
