from datetime import date
import pytest

from extrapcap.config import RiskConfig
from extrapcap.events import EventDecision
from extrapcap.options import VerticalSpread, DebitSpread, build_credit_spread
from extrapcap.options_data import (
    OptionContract,
    OptionQuote,
    select_candidate_verticals,
)
from extrapcap.orchestration.paper_run import build_candidates
from extrapcap.risk import PortfolioRiskState


def test_vertical_spread_credit_ratio_invariant():
    # Width 5.0, credit 1.50 -> 30% of width (< 35%) -> raises ValueError
    with pytest.raises(ValueError, match="violates safety policy"):
        VerticalSpread("AAPL", 220, 215, 1.50)

    # Width 5.0, credit 1.75 -> 35% of width -> succeeds
    spread_35 = VerticalSpread("AAPL", 220, 215, 1.75)
    assert spread_35.credit == 1.75
    assert spread_35.width == 5.0

    # Width 5.0, credit 2.00 -> 40% of width -> succeeds
    spread_40 = VerticalSpread("AAPL", 220, 215, 2.00)
    assert spread_40.credit == 2.00
    assert spread_40.max_profit / spread_40.max_loss == pytest.approx(2.00 / 3.00)


def test_build_credit_spread_collects_40_pct_minimum():
    spread = build_credit_spread("AAPL", 225.0, width=5.0)
    assert spread.width == 5.0
    assert spread.credit >= 2.00  # >= 40% of 5.0
    assert spread.credit / spread.width >= 0.40


def test_select_candidate_verticals_filters_by_ratios():
    trading_day = date(2026, 8, 12)
    contracts = [
        OptionContract("STK-P100", "STK", "2026-08-21", 100.0, "put"),
        OptionContract("STK-P95", "STK", "2026-08-21", 95.0, "put"),
        OptionContract("STK-P90", "STK", "2026-08-21", 90.0, "put"),
    ]
    # P100-P95 width 5: credit 2.00 (40% of width) -> accepted
    # P95-P90 width 5: credit 1.00 (20% of width) -> rejected by min_credit_pct_width=0.40
    quotes = [
        OptionQuote("STK-P100", "now", 2.60, 2.80, 2.70, delta=-0.45),
        OptionQuote("STK-P95", "now", 0.50, 0.60, 0.55, delta=-0.25),
        OptionQuote("STK-P90", "now", 0.10, 0.20, 0.15, delta=-0.10),
    ]

    solutions = select_candidate_verticals(
        underlying="STK",
        contracts=contracts,
        quotes=quotes,
        underlying_price=102.0,
        win_probability=0.70,
        streak_direction="negative",
        trading_day=trading_day,
        spread_types=("credit",),
        min_credit_pct_width=0.40,
    )
    assert len(solutions) == 1
    assert solutions[0].spread.short_strike == 100.0
    assert solutions[0].spread.long_strike == 95.0
    assert solutions[0].spread.credit == 2.00  # 2.60 - 0.60 (>= 40%)


def test_debit_reversal_route_selection():
    trading_day = date(2026, 8, 12)
    contracts_payload = {
        "option_contracts": [
            {"symbol": "AAPL-C220", "underlying_symbol": "AAPL", "expiration_date": "2026-08-21", "strike_price": "220", "type": "call"},
            {"symbol": "AAPL-C225", "underlying_symbol": "AAPL", "expiration_date": "2026-08-21", "strike_price": "225", "type": "call"},
        ]
    }
    snapshot_payload = {
        "snapshots": {
            "AAPL-C220": {"latestQuote": {"t": "2026-08-12T16:00:00Z", "bp": 3.80, "ap": 4.00}, "latestTrade": {"p": 3.90}, "greeks": {"delta": 0.50}},
            "AAPL-C225": {"latestQuote": {"t": "2026-08-12T16:00:00Z", "bp": 2.80, "ap": 3.00}, "latestTrade": {"p": 2.90}, "greeks": {"delta": 0.30}},
        }
    }
    # Midpoint debit = 3.90 - 2.90 = 1.00 on 5.0 width (20% <= 30%)
    risk_state = PortfolioRiskState(nav=100_000.0)
    candidates = build_candidates(
        underlying="AAPL",
        trading_day=trading_day,
        underlying_price=220.0,
        contracts_payload=contracts_payload,
        snapshot_payload=snapshot_payload,
        model_probability=0.75,
        risk_state=risk_state,
        risk_config=RiskConfig(),
        event_decision=EventDecision("calendar", True, "approved"),
        selection_context={
            "streak_direction": "negative",
            "sector": "Technology",
            "strategy_route": "debit_reversal",
        },
    )
    assert len(candidates) == 1
    assert candidates[0].envelope.side == "buy_to_open"
    assert isinstance(candidates[0].spread, DebitSpread)
    assert candidates[0].risk_decision.allowed
    assert isinstance(candidates[0].spread, DebitSpread)
    assert candidates[0].risk_decision.allowed
