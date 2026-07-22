import json
from datetime import date

from extrapcap.config import RiskConfig
from extrapcap.events import EventDecision
from extrapcap.fills import FillAssumptions
from extrapcap.execution.orders import OrderRegistry
from extrapcap.ledger import AuditLedger
from extrapcap.orchestration.paper_run import PaperRunCoordinator, build_candidate
from extrapcap.risk import PortfolioRiskState


def test_build_candidate_resolves_real_option_legs(tmp_path):
    candidate = build_candidate(
        underlying="ABC", trading_day=date(2026, 7, 22), underlying_price=100,
        contracts_payload={"option_contracts": [
            {"symbol": "ABC-short", "underlying_symbol": "ABC", "expiration_date": "2026-08-21", "strike_price": 95, "type": "put"},
            {"symbol": "ABC-long", "underlying_symbol": "ABC", "expiration_date": "2026-08-21", "strike_price": 90, "type": "put"},
        ]},
        snapshot_payload={"snapshots": {
            "ABC-short": {"latestQuote": {"bp": 2.0, "ap": 2.2}, "greeks": {"delta": -0.18}},
            "ABC-long": {"latestQuote": {"bp": 0.8, "ap": 1.0}, "greeks": {"delta": -0.08},
        }}},
        model_probability=0.72, risk_state=PortfolioRiskState(nav=100_000), risk_config=RiskConfig(),
        event_decision=EventDecision("noise_or_opinion", True, "none"), fill_assumptions=FillAssumptions(slippage_per_leg=0),
    )
    assert candidate.envelope.validate_for_submission() is None
    assert candidate.envelope.alpaca_payload()["legs"][0]["asset_class"] == "us_option"
    assert candidate.strategy_variant == "improved"

    class FakeClient:
        dry_run = True

        def submit_order(self, order):
            return {"status": "dry_run", "order": order}

    class FakeReviewer:
        def review(self, candidate):
            return {"decision": "go", "reason": "fixture", "provider": "fake"}

    coordinator = PaperRunCoordinator(
        FakeClient(),
        FakeReviewer(),
        AuditLedger(tmp_path / "logs"),
        OrderRegistry(tmp_path / "ids.jsonl"),
    )
    result = coordinator.execute(candidate)
    assert result["ticker"] == "ABC"
    assert result["contract_ids"] == ["ABC-short", "ABC-long"]
    signal = json.loads((tmp_path / "logs" / "signals" / "2026-07-22.jsonl").read_text().splitlines()[0])
    assert signal["ticker"] == "ABC"
    assert signal["contract_ids"] == ["ABC-LONG", "ABC-SHORT"]
    assert signal["contracts"][0]["role"] == "short"
    assert signal["strategy_variant"] == "improved"
