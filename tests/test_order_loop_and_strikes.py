import time
from datetime import date, datetime, timezone

import pytest

from extrapcap.config import RiskConfig
from extrapcap.events import EventDecision
from extrapcap.options_data import (
    OptionContract,
    OptionQuote,
    select_candidate_verticals,
)
from extrapcap.orchestration.basket_cycle import run_basket
from extrapcap.orchestration.paper_run import (
    PaperRunCoordinator,
    build_candidate,
    build_candidates,
)
from extrapcap.risk import PortfolioRiskState


def _make_chain():
    contracts_payload = {
        "option_contracts": [
            {"symbol": "AAPL-P220", "underlying_symbol": "AAPL", "expiration_date": "2026-08-21", "strike_price": "220", "type": "put"},
            {"symbol": "AAPL-P215", "underlying_symbol": "AAPL", "expiration_date": "2026-08-21", "strike_price": "215", "type": "put"},
            {"symbol": "AAPL-P210", "underlying_symbol": "AAPL", "expiration_date": "2026-08-21", "strike_price": "210", "type": "put"},
            {"symbol": "AAPL-P205", "underlying_symbol": "AAPL", "expiration_date": "2026-08-21", "strike_price": "205", "type": "put"},
        ]
    }
    snapshot_payload = {
        "snapshots": {
            "AAPL-P220": {"latestQuote": {"t": "2026-08-12T16:00:00Z", "bp": 3.80, "ap": 4.00}, "latestTrade": {"p": 3.90}, "greeks": {"delta": -0.22}},
            "AAPL-P215": {"latestQuote": {"t": "2026-08-12T16:00:00Z", "bp": 1.00, "ap": 1.20}, "latestTrade": {"p": 1.10}, "greeks": {"delta": -0.15}},
            "AAPL-P210": {"latestQuote": {"t": "2026-08-12T16:00:00Z", "bp": 0.40, "ap": 0.50}, "latestTrade": {"p": 0.45}, "greeks": {"delta": -0.09}},
            "AAPL-P205": {"latestQuote": {"t": "2026-08-12T16:00:00Z", "bp": 0.10, "ap": 0.15}, "latestTrade": {"p": 0.12}, "greeks": {"delta": -0.04}},
        }
    }
    return contracts_payload, snapshot_payload


def test_select_candidate_verticals_ranks_viable_spreads_by_ev():
    contracts = [
        OptionContract("AAPL-P220", "AAPL", "2026-08-21", 220, "put"),
        OptionContract("AAPL-P215", "AAPL", "2026-08-21", 215, "put"),
        OptionContract("AAPL-P210", "AAPL", "2026-08-21", 210, "put"),
        OptionContract("AAPL-P205", "AAPL", "2026-08-21", 205, "put"),
    ]
    quotes = [
        OptionQuote("AAPL-P220", "2026-08-12T16:00:00Z", 3.80, 4.00, 3.90, delta=-0.22),
        OptionQuote("AAPL-P215", "2026-08-12T16:00:00Z", 1.00, 1.20, 1.10, delta=-0.15),
        OptionQuote("AAPL-P210", "2026-08-12T16:00:00Z", 0.40, 0.50, 0.45, delta=-0.09),
        OptionQuote("AAPL-P205", "2026-08-12T16:00:00Z", 0.10, 0.15, 0.12, delta=-0.04),
    ]
    solutions = select_candidate_verticals(
        underlying="AAPL",
        contracts=contracts,
        quotes=quotes,
        underlying_price=225.0,
        win_probability=0.75,
        trading_day=date(2026, 8, 12),
        limit=5,
    )
    assert len(solutions) >= 2
    for i in range(len(solutions) - 1):
        assert solutions[i].expected_value >= solutions[i + 1].expected_value


def test_build_candidates_yields_multiple_sized_candidates():
    contracts_payload, snapshot_payload = _make_chain()
    risk_state = PortfolioRiskState(nav=100_000.0, options_buying_power=200_000.0, options_trading_level=3)
    candidates = build_candidates(
        underlying="AAPL",
        trading_day=date(2026, 8, 12),
        underlying_price=225.0,
        contracts_payload=contracts_payload,
        snapshot_payload=snapshot_payload,
        model_probability=0.75,
        risk_state=risk_state,
        risk_config=RiskConfig(),
        event_decision=EventDecision("calendar", True, "approved"),
        selection_context={"streak_direction": "negative", "sector": "Technology"},
        limit=3,
    )
    assert len(candidates) >= 2
    for c in candidates:
        assert c.risk_decision.allowed
        assert c.envelope.quantity >= 1
        assert c.envelope.symbol == "AAPL"


class MockAlpacaClient:
    def __init__(self, fill_on_order_id=None, fill_after_poll_count=1):
        self.submitted = []
        self.canceled = []
        self.fill_on_order_id = fill_on_order_id
        self.fill_after_poll_count = fill_after_poll_count
        self.poll_counts = {}
        self.orders = {}

    def submit_order(self, payload):
        order_id = f"ord-{len(self.submitted) + 1}"
        record = {
            "id": order_id,
            "status": "new",
            "limit_price": payload.get("limit_price"),
            "qty": payload.get("qty"),
            "filled_qty": None,
            "filled_avg_price": None,
            "payload": payload,
        }
        self.submitted.append(record)
        self.orders[order_id] = record
        return record

    def order(self, order_id):
        record = self.orders[order_id]
        count = self.poll_counts.get(order_id, 0) + 1
        self.poll_counts[order_id] = count
        if (self.fill_on_order_id is None or self.fill_on_order_id == order_id) and count >= self.fill_after_poll_count:
            record["status"] = "filled"
            record["filled_qty"] = record["qty"]
            record["filled_avg_price"] = record["limit_price"]
        return record

    def cancel_order(self, order_id):
        self.canceled.append(order_id)
        if order_id in self.orders and self.orders[order_id]["status"] != "filled":
            self.orders[order_id]["status"] = "canceled"
        return {"id": order_id, "status": "canceled"}


def test_execute_with_fill_loop_fills_at_midpoint():
    contracts_payload, snapshot_payload = _make_chain()
    risk_state = PortfolioRiskState(nav=100_000.0, options_buying_power=200_000.0, options_trading_level=3)
    candidate = build_candidate(
        underlying="AAPL",
        trading_day=date(2026, 8, 12),
        underlying_price=225.0,
        contracts_payload=contracts_payload,
        snapshot_payload=snapshot_payload,
        model_probability=0.75,
        risk_state=risk_state,
        risk_config=RiskConfig(),
        event_decision=EventDecision("calendar", True, "approved"),
        selection_context={"streak_direction": "negative", "sector": "Technology"},
    )
    mock = MockAlpacaClient(fill_on_order_id="ord-1", fill_after_poll_count=1)
    coordinator = PaperRunCoordinator(mock)
    result = coordinator.execute_with_fill_loop(
        candidate,
        poll_timeout=1.0,
        poll_interval=0.05,
    )
    assert result["status"] == "filled"
    assert result["order_id"] == "ord-1"
    assert len(mock.submitted) == 1
    assert len(mock.canceled) == 0


def test_execute_with_fill_loop_walks_to_natural_price_on_timeout():
    contracts_payload, snapshot_payload = _make_chain()
    risk_state = PortfolioRiskState(nav=100_000.0, options_buying_power=200_000.0, options_trading_level=3)
    candidate = build_candidate(
        underlying="AAPL",
        trading_day=date(2026, 8, 12),
        underlying_price=225.0,
        contracts_payload=contracts_payload,
        snapshot_payload=snapshot_payload,
        model_probability=0.75,
        risk_state=risk_state,
        risk_config=RiskConfig(),
        event_decision=EventDecision("calendar", True, "approved"),
        selection_context={"streak_direction": "negative", "sector": "Technology"},
    )
    mock = MockAlpacaClient(fill_on_order_id="ord-2", fill_after_poll_count=1)
    coordinator = PaperRunCoordinator(mock)
    result = coordinator.execute_with_fill_loop(
        candidate,
        poll_timeout=0.1,
        poll_interval=0.02,
        natural_poll_timeout=1.0,
        natural_fallback=True,
    )
    assert result["status"] == "filled"
    assert result["order_id"] == "ord-2"
    assert len(mock.submitted) == 2
    assert "ord-1" in mock.canceled


def test_execute_with_fill_loop_cancels_all_when_unfilled():
    contracts_payload, snapshot_payload = _make_chain()
    risk_state = PortfolioRiskState(nav=100_000.0, options_buying_power=200_000.0, options_trading_level=3)
    candidate = build_candidate(
        underlying="AAPL",
        trading_day=date(2026, 8, 12),
        underlying_price=225.0,
        contracts_payload=contracts_payload,
        snapshot_payload=snapshot_payload,
        model_probability=0.75,
        risk_state=risk_state,
        risk_config=RiskConfig(),
        event_decision=EventDecision("calendar", True, "approved"),
        selection_context={"streak_direction": "negative", "sector": "Technology"},
    )
    mock = MockAlpacaClient(fill_on_order_id="none")
    coordinator = PaperRunCoordinator(mock)
    result = coordinator.execute_with_fill_loop(
        candidate,
        poll_timeout=0.1,
        poll_interval=0.02,
        natural_poll_timeout=0.1,
        natural_fallback=True,
    )
    assert result["status"] == "unfilled"
    assert result["reason"] == "fill_timeout"
    assert "ord-1" in mock.canceled
    assert "ord-2" in mock.canceled


def test_run_basket_defaults_to_multi_submission_limit():
    calls = []
    def runner(**kwargs):
        calls.append(kwargs["symbol"])
        return {"ticker": kwargs["symbol"], "status": "filled", "category": "orders"}

    basket = [
        {"ticker": f"T{i:02d}", "sector": "Tech", "streak_length": 3, "streak_direction": "negative", "robust_z": -2.0, "relative_return": -0.03, "reversion_probability": 0.70, "underlying_price": 100}
        for i in range(12)
    ]
    results = run_basket(basket, runner=runner, trading_day=date(2026, 8, 12))
    assert len(calls) == 8
    orders = [r for r in results if r.get("category") == "orders"]
    assert len(orders) == 8
