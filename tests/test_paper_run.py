from datetime import date

from extrapcap.config import RiskConfig
from extrapcap.events import EventDecision
from extrapcap.fills import FillAssumptions
from extrapcap.orchestration.paper_run import build_candidate
from extrapcap.risk import PortfolioRiskState


def test_build_candidate_resolves_real_option_legs():
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
