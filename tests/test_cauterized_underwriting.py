from datetime import date
import pytest

from extrapcap.config import RiskConfig, StrategyConfig
from extrapcap.execution.orders import OrderEnvelope
from extrapcap.execution.position_manager import ManagedPosition, evaluate_credit_exit
from extrapcap.options import VerticalSpread
from extrapcap.options_data import OptionContract, OptionQuote, select_candidate_verticals


def test_otm_strike_selection_rejects_itm_puts():
    trading_day = date(2026, 8, 12)
    # Underlying price is $100.00
    # P102 is IN THE MONEY (strike > spot)
    # P100 is AT THE MONEY (strike == spot)
    # P96 is OUT OF THE MONEY (4% OTM)
    # P91 is further OUT OF THE MONEY
    contracts = [
        OptionContract("STK-P102", "STK", "2026-08-21", 102.0, "put"),
        OptionContract("STK-P100", "STK", "2026-08-21", 100.0, "put"),
        OptionContract("STK-P96", "STK", "2026-08-21", 96.0, "put"),
        OptionContract("STK-P91", "STK", "2026-08-21", 91.0, "put"),
    ]
    quotes = [
        OptionQuote("STK-P102", "now", 4.00, 4.20, 4.10, delta=-0.65),
        OptionQuote("STK-P100", "now", 2.60, 2.80, 2.70, delta=-0.50),
        OptionQuote("STK-P96", "now", 0.90, 1.05, 0.98, delta=-0.16),
        OptionQuote("STK-P91", "now", 0.20, 0.30, 0.25, delta=-0.06),
    ]

    solutions = select_candidate_verticals(
        underlying="STK",
        contracts=contracts,
        quotes=quotes,
        underlying_price=100.0,
        win_probability=0.90,
        streak_direction="negative",
        trading_day=trading_day,
        spread_types=("credit",),
        min_credit_pct_width=0.10,
        min_delta=0.08,
        max_delta=0.25,
        otm_buffer_pct=0.02,
    )

    # ITM (P102) and ATM (P100) must NOT be selected
    assert len(solutions) == 1
    short_contract = solutions[0].spread.short_strike
    assert short_contract == 96.0  # Only P96 is approved as short strike
    assert short_contract <= 100.0 * 0.98  # At least 2% OTM


def test_trailing_breakeven_protection_exit():
    env = OrderEnvelope("2026-08-12", "JPM", "sell_to_open", (), "core", 6.10)
    # Position entered at $6.10 credit.
    # Previously captured 25% profit (peak_profit_pct = 0.25).
    # Market reverses, debit rises back to entry credit ($6.15 >= $6.10).
    pos = ManagedPosition(
        env,
        entry_price=6.10,
        current_debit=6.15,
        spread_width=15.0,
        opened_at=date(2026, 8, 12),
        as_of=date(2026, 8, 15),
        expiration=date(2026, 8, 28),
        short_strike=340.0,
        long_strike=325.0,
        underlying_price=345.0,
        peak_profit_pct=0.25,
    )
    decision = evaluate_credit_exit(pos, RiskConfig())
    assert decision.action == "close"
    assert decision.reason == "trailing_breakeven_protection"


def test_catastrophic_debit_cap_at_75_percent():
    env = OrderEnvelope("2026-08-12", "ABC", "sell_to_open", (), "core", 1.0)
    # Spread width 5.0. 75% catastrophic cap is $3.75.
    pos = ManagedPosition(
        env,
        entry_price=1.0,
        current_debit=3.80,
        spread_width=5.0,
        opened_at=date(2026, 8, 12),
        as_of=date(2026, 8, 15),
        expiration=date(2026, 8, 28),
        short_strike=100.0,
        long_strike=95.0,
        underlying_price=98.0,
    )
    decision = evaluate_credit_exit(pos, RiskConfig())
    assert decision.action == "close"
    assert decision.reason == "catastrophic_debit_cap"
