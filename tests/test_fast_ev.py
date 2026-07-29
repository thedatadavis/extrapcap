from datetime import date
import pytest

from extrapcap.options_data import (
    OptionContract,
    OptionQuote,
    select_highest_ev_vertical,
)
from extrapcap.orchestration.paper_run import (
    PaperRunCoordinator,
    build_fast_ev_candidate,
)
from extrapcap.events import EventDecision
from extrapcap.execution.account_risk import PortfolioRiskState
from extrapcap.config import RiskConfig


def test_select_highest_ev_vertical_calculates_correct_ev():
    contracts = [
        OptionContract("CF260828P00113000", "CF", "2026-08-28", 113.0, "put"),
        OptionContract("CF260828P00118000", "CF", "2026-08-28", 118.0, "put"),
    ]
    quotes = [
        OptionQuote("CF260828P00113000", None, bid=2.00, ask=2.20, last=2.10, delta=-0.20),
        OptionQuote("CF260828P00118000", None, bid=4.00, ask=4.50, last=4.25, delta=-0.40),
    ]

    # Debit spread: long 118.0 put @ 4.50 ask, short 113.0 put @ 2.00 bid -> net debit = 2.50
    # Width = 5.00 -> Max Profit = (5.00 - 2.50) * 100 = $250. Max Risk = 2.50 * 100 = $250.
    # With win_prob = 0.60: EV = 0.60 * 250 - 0.40 * 250 = 150 - 100 = $50.00 >= $10.00.
    sol = select_highest_ev_vertical("CF", contracts, quotes, 120.0, win_probability=0.60, min_ev=10.0)

    assert sol.expected_value == pytest.approx(50.0)
    assert sol.max_profit == pytest.approx(250.0)
    assert sol.max_risk == pytest.approx(250.0)


def test_build_fast_ev_candidate_rejects_low_probability():
    contracts_payload = {
        "option_contracts": [
            {"symbol": "CF260828P00113000", "underlying_symbol": "CF", "expiration_date": "2026-08-28", "strike_price": 113.0, "type": "put"},
            {"symbol": "CF260828P00118000", "underlying_symbol": "CF", "expiration_date": "2026-08-28", "strike_price": 118.0, "type": "put"},
        ]
    }
    snapshot_payload = {
        "snapshots": {
            "CF260828P00113000": {"latestQuote": {"bp": 2.00, "ap": 2.20}},
            "CF260828P00118000": {"latestQuote": {"bp": 4.00, "ap": 4.50}},
        }
    }
    risk_state = PortfolioRiskState(100000.0, 0.0, 0.0, 0.0, 0.0, 0, {}, {}, 100000.0, 3, False)

    with pytest.raises(ValueError, match="<= 0.51 threshold"):
        build_fast_ev_candidate(
            underlying="CF",
            trading_day=date(2026, 7, 28),
            underlying_price=120.0,
            contracts_payload=contracts_payload,
            snapshot_payload=snapshot_payload,
            model_probability=0.50,
            risk_state=risk_state,
            risk_config=RiskConfig(),
            event_decision=EventDecision("earnings", True, "ok"),
            selection_context={"sector": "Basic Materials"},
        )


def test_paper_run_coordinator_fast_ev_auto_approves():
    contracts_payload = {
        "option_contracts": [
            {"symbol": "CF260828P00113000", "underlying_symbol": "CF", "expiration_date": "2026-08-28", "strike_price": 113.0, "type": "put"},
            {"symbol": "CF260828P00118000", "underlying_symbol": "CF", "expiration_date": "2026-08-28", "strike_price": 118.0, "type": "put"},
        ]
    }
    snapshot_payload = {
        "snapshots": {
            "CF260828P00113000": {"latestQuote": {"bp": 2.00, "ap": 2.20}},
            "CF260828P00118000": {"latestQuote": {"bp": 4.00, "ap": 4.50}},
        }
    }
    risk_state = PortfolioRiskState(100000.0, 0.0, 0.0, 0.0, 0.0, 0, {}, {}, 100000.0, 3, False)

    candidate = build_fast_ev_candidate(
        underlying="CF",
        trading_day=date(2026, 7, 28),
        underlying_price=120.0,
        contracts_payload=contracts_payload,
        snapshot_payload=snapshot_payload,
        model_probability=0.60,
        risk_state=risk_state,
        risk_config=RiskConfig(),
        event_decision=EventDecision("earnings", True, "ok"),
        selection_context={"sector": "Basic Materials"},
    )

    class MockClient:
        dry_run = True
        def submit_order(self, payload):
            return {"status": "accepted", "id": "ord-123"}

    class ErrorReviewer:
        def review(self, input_data):
            raise RuntimeError("Should not be called in fast EV mode")

    coordinator = PaperRunCoordinator(MockClient(), ErrorReviewer(), fast_ev=True)
    res = coordinator.execute(candidate)
    assert res.get("client_order_id") == candidate.envelope.client_order_id
