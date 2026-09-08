from datetime import date, datetime, timezone
from io import BytesIO
from urllib.error import HTTPError
import pytest

from extrapcap.config import RiskConfig
from extrapcap.events import EventDecision
from extrapcap.execution.account_risk import build_portfolio_risk_state
from extrapcap.options_data import (
    AlpacaOptionsData,
    OptionContract,
    OptionQuote,
    SelectedVertical,
    select_highest_ev_vertical,
)
from extrapcap.orchestration.paper_run import _midpoint_spread, build_candidate
from extrapcap.risk import PortfolioRiskState


def test_build_portfolio_risk_state_aggregates_held_options_and_orders():
    account = {
        "equity": "100000.0",
        "last_equity": "100000.0",
        "options_buying_power": "300000.0",
        "options_trading_level": "3",
        "status": "ACTIVE",
    }
    positions = [
        {"symbol": "ONTO260918C00185000", "qty": "-2", "asset_class": "us_option"},
        {"symbol": "ONTO260918C00190000", "qty": "2", "asset_class": "us_option"},
    ]
    open_orders = [
        {
            "ticker": "AAPL",
            "qty": "4",
            "side": "sell_to_open",
            "limit_price": "0.50",
            "legs": [
                {"symbol": "AAPL260918P00220000", "asset_class": "us_option"},
                {"symbol": "AAPL260918P00217500", "asset_class": "us_option"},
            ],
        }
    ]
    state = build_portfolio_risk_state(
        account,
        positions,
        open_orders,
        sector_by_ticker={"ONTO": "Technology", "AAPL": "Technology"},
    )
    assert not state.trading_blocked
    assert state.nav == 100000.0
    # ONTO spread: (190 - 185) * 100 * 2 = $1,000
    assert state.ticker_open_risk["ONTO"] == 1000.0
    # AAPL order: (220 - 217.5 - 0.50) * 100 * 4 = 2.00 * 100 * 4 = $800
    assert state.ticker_open_risk["AAPL"] == 800.0
    assert state.core_open_risk == 1800.0
    assert state.sector_open_risk["Technology"] == 1800.0


def test_build_portfolio_risk_state_uses_durable_metadata():
    account = {
        "equity": "100000.0",
        "options_buying_power": "250000.0",
        "options_trading_level": "3",
    }
    durable_positions = [
        {
            "ticker": "ONTO",
            "spread_width": 5.0,
            "entry_credit": 0.60,
            "quantity": 1,
            "sleeve": "core",
            "legs": [{"symbol": "ONTO260918C00185000"}, {"symbol": "ONTO260918C00190000"}],
        }
    ]
    positions = [
        {"symbol": "ONTO260918C00185000", "qty": "-1", "asset_class": "us_option"},
        {"symbol": "ONTO260918C00190000", "qty": "1", "asset_class": "us_option"},
    ]
    state = build_portfolio_risk_state(account, positions, [], durable_positions=durable_positions)
    # Defined credit spread risk: (5.0 - 0.60) * 100 * 1 = $440
    assert state.core_open_risk == 440.0
    assert state.ticker_open_risk["ONTO"] == 440.0


def test_select_highest_ev_vertical_dynamic_percentage_widths():
    # Underlying price $200 with standard $10 strike interval (5% of 200)
    underlying = "BIGCO"
    trading_day = date(2026, 8, 12)
    contracts = [
        OptionContract("BIGCO-C190", underlying, "2026-08-21", 190.0, "call"),
        OptionContract("BIGCO-C200", underlying, "2026-08-21", 200.0, "call"),
    ]
    quotes = [
        OptionQuote("BIGCO-C190", "now", 12.0, 12.5, 12.25, delta=0.60),
        OptionQuote("BIGCO-C200", "now", 5.0, 5.5, 5.25, delta=0.45),
    ]
    # Without passing explicit widths, percentage-based bounds (0.5% to 5.0%) accept width=10.0
    sol = select_highest_ev_vertical(
        underlying,
        contracts,
        quotes,
        underlying_price=200.0,
        win_probability=0.85,
        streak_direction="negative",
        trading_day=trading_day,
        dte_min=0,
        dte_max=21,
    )
    assert sol.spread.width == 10.0
    assert sol.expected_value > 0


def test_midpoint_spread_fallback_on_flat_midpoint():
    short_c = OptionContract("XYZ-S", "XYZ", "2026-08-21", 100.0, "put")
    long_c = OptionContract("XYZ-L", "XYZ", "2026-08-21", 95.0, "put")
    selected = SelectedVertical("XYZ", short_c, long_c, credit=0.80, delta=-0.18)

    # Flat or negative midpoints (e.g. wide morning quote)
    quotes = {
        "XYZ-S": OptionQuote("XYZ-S", "now", 2.0, 2.0, 2.0),
        "XYZ-L": OptionQuote("XYZ-L", "now", 2.0, 2.0, 2.0),
    }
    # Midpoint diff = 2.0 - 2.0 = 0 -> falls back to selected.credit (0.80)
    price = _midpoint_spread(selected, quotes, debit=False)
    assert price == 0.80


def test_build_candidate_scales_quantity_by_confidence():
    trading_day = date(2026, 8, 12)
    contracts_payload = {
        "option_contracts": [
            {"symbol": "STK-P95", "underlying_symbol": "STK", "expiration_date": "2026-08-21", "strike_price": "95", "type": "put"},
            {"symbol": "STK-P90", "underlying_symbol": "STK", "expiration_date": "2026-08-21", "strike_price": "90", "type": "put"},
        ]
    }
    snapshot_payload = {
        "snapshots": {
            "STK-P95": {"latestQuote": {"t": "now", "bp": 4.0, "ap": 4.2}, "latestTrade": {"p": 4.1}, "greeks": {"delta": -0.20}},
            "STK-P90": {"latestQuote": {"t": "now", "bp": 0.8, "ap": 1.0}, "latestTrade": {"p": 0.9}, "greeks": {"delta": -0.08}},
        }
    }
    risk_state = PortfolioRiskState(
        nav=100_000.0,
        options_buying_power=200_000.0,
        options_trading_level=3,
    )
    risk_config = RiskConfig()

    low_conf = build_candidate(
        underlying="STK",
        trading_day=trading_day,
        underlying_price=100.0,
        contracts_payload=contracts_payload,
        snapshot_payload=snapshot_payload,
        model_probability=0.52,
        risk_state=risk_state,
        risk_config=risk_config,
        event_decision=EventDecision("calendar", True, "approved"),
        selection_context={"streak_direction": "negative", "sector": "Tech"},
        dte_min=0,
        dte_max=21,
    )

    high_conf = build_candidate(
        underlying="STK",
        trading_day=trading_day,
        underlying_price=100.0,
        contracts_payload=contracts_payload,
        snapshot_payload=snapshot_payload,
        model_probability=0.80,
        risk_state=risk_state,
        risk_config=risk_config,
        event_decision=EventDecision("calendar", True, "approved"),
        selection_context={"streak_direction": "negative", "sector": "Tech"},
        dte_min=0,
        dte_max=21,
    )

    # High confidence allocates more contracts than low confidence
    assert high_conf.envelope.quantity > low_conf.envelope.quantity
    # Both are within portfolio limits and greater than 1
    assert low_conf.envelope.quantity >= 1
    assert high_conf.envelope.quantity >= 1
    assert high_conf.risk_decision.allowed


def test_alpaca_options_data_retries_on_429(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        if len(calls) == 1:
            raise HTTPError(request.full_url, 429, "Too Many Requests", {}, BytesIO(b"rate limit"))
        return BytesIO(b'{"option_contracts": []}')

    monkeypatch.setattr("extrapcap.options_data.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda s: None)
    provider = AlpacaOptionsData("key", "secret")
    result = provider.contracts("AAPL", "2026-08-12")
    assert len(calls) == 2
    assert result == {"option_contracts": []}
