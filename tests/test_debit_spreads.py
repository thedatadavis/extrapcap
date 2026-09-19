from datetime import date
import pytest

from extrapcap.config import RiskConfig
from extrapcap.events import EventDecision
from extrapcap.options import (
    BrokenWingButterfly,
    DebitSpread,
    build_asymmetric_debit_spread,
    build_broken_wing_butterfly,
    build_positive_skew_debit_spread,
)
from extrapcap.options_data import (
    OptionContract,
    OptionQuote,
    SelectedDebitVertical,
    ExpectedValueSolution,
)
from extrapcap.orchestration.paper_run import candidate_from_solution
from extrapcap.risk import PortfolioRiskState


def test_debit_spread_validation():
    # Valid positive-skew debit spread (debit <= 0.30 * width)
    spread = DebitSpread("AAPL", 220, 225, 1.25, contracts=1, direction="bullish")
    assert spread.width == 5.0
    assert spread.debit == 1.25
    assert spread.max_loss == 125.0
    assert spread.max_profit == 375.0
    assert spread.reward_multiple == 3.0

    # Debit <= 0 raises ValueError
    with pytest.raises(ValueError, match="debit must be positive"):
        DebitSpread("AAPL", 220, 225, 0.0)

    # Debit >= width raises ValueError
    with pytest.raises(ValueError, match="debit must be positive and less than spread width"):
        DebitSpread("AAPL", 220, 225, 5.0)

    # Debit > 0.30 * width raises ValueError (hard invariant: violates 1:3 reward-to-risk policy)
    with pytest.raises(ValueError, match="violates 1:3 reward-to-risk policy"):
        DebitSpread("AAPL", 220, 225, 1.60)  # 1.60 / 5.0 = 32%


def test_build_positive_skew_debit_spread():
    # Bullish: long 100, short 105, width 5.0, debit = 1.25 (25% of width)
    bullish = build_positive_skew_debit_spread("SPY", 100.0, direction="bullish", width=5.0)
    assert bullish.direction == "bullish"
    assert bullish.long_strike == 100.0
    assert bullish.short_strike == 105.0
    assert bullish.debit == 1.25
    assert bullish.reward_multiple == 3.0
    assert bullish.sleeve == "asymmetric"

    # Bearish: long 100, short 95, width 5.0, debit = 1.25 (25% of width)
    bearish = build_positive_skew_debit_spread("SPY", 100.0, direction="bearish", width=5.0)
    assert bearish.direction == "bearish"
    assert bearish.long_strike == 100.0
    assert bearish.short_strike == 95.0
    assert bearish.debit == 1.25
    assert bearish.reward_multiple == 3.0

    # build_asymmetric_debit_spread backward compatibility
    asym = build_asymmetric_debit_spread("SPY", 100.0, direction="bullish", width=5.0)
    assert asym.reward_multiple >= 3.0


def test_broken_wing_butterfly():
    # Bullish Broken Wing Butterfly: lower 95, middle 100, upper 104, net_credit 0.50
    # lower_width = 5.0, upper_width = 4.0 (broken upper wing)
    bwb = BrokenWingButterfly("AAPL", 95.0, 100.0, 104.0, net_credit=0.50, direction="bullish")
    assert bwb.lower_width == 5.0
    assert bwb.upper_width == 4.0
    assert bwb.max_loss == 50.0  # (5.0 - 4.0 - 0.50) * 100
    assert bwb.max_profit == 450.0  # (4.0 + 0.50) * 100

    # Negative credit raises ValueError
    with pytest.raises(ValueError, match="flat or net credit"):
        BrokenWingButterfly("AAPL", 95.0, 100.0, 104.0, net_credit=-0.10)

    # Invalid strike order raises ValueError
    with pytest.raises(ValueError, match="lower < middle < upper"):
        BrokenWingButterfly("AAPL", 100.0, 95.0, 105.0, net_credit=0.50)

    # Builder
    built_bwb = build_broken_wing_butterfly("AAPL", 100.0, direction="bullish")
    assert built_bwb.middle_strike < built_bwb.upper_strike
    assert built_bwb.lower_strike < built_bwb.middle_strike
    assert built_bwb.net_credit >= 0.10


def test_candidate_from_solution_enforces_debit_invariant():
    c_long = OptionContract("XYZ-C100", "XYZ", "2026-08-21", 100.0, "call")
    c_short = OptionContract("XYZ-C105", "XYZ", "2026-08-21", 105.0, "call")
    # Natural midpoint debit > 0.30 * width (e.g. 1.80 on 5.0 width = 36%)
    quotes = [
        OptionQuote("XYZ-C100", "now", 3.00, 3.20, 3.10),
        OptionQuote("XYZ-C105", "now", 1.20, 1.40, 1.30),
    ]
    quote_map = {q.symbol: q for q in quotes}
    # Midpoint debit = 3.10 - 1.30 = 1.80 > 1.50 (30% of width 5.0)
    selected = SelectedDebitVertical("XYZ", c_long, c_short, debit=1.80, delta=0.50)
    spread = DebitSpread("XYZ", 100.0, 105.0, debit=1.25)
    sol = ExpectedValueSolution(spread, selected, expected_value=50.0, max_profit=375.0, max_risk=125.0, expiration="2026-08-21", dte=9)

    candidate = candidate_from_solution(
        sol,
        underlying="XYZ",
        trading_day=date(2026, 8, 12),
        model_probability=0.70,
        quotes=quotes,
        quote_map=quote_map,
        risk_state=PortfolioRiskState(nav=100_000),
        risk_config=RiskConfig(),
        event_decision=EventDecision("calendar", True, "approved"),
        selection_context={"sector": "Technology", "strategy_route": "debit_reversal"},
        snapshot_payload={},
    )
    # Hard invariant: rejected because natural midpoint debit exceeds 30% of width
    assert not candidate.risk_decision.allowed
    assert "exceeds 30% of width" in candidate.risk_decision.reason
    assert candidate.envelope.side == "buy_to_open"
