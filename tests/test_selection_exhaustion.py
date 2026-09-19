import argparse
import pandas as pd
import pytest

from extrapcap.selection import core_streak_gate
from extrapcap.universe.streak_screen import StreakPolicy, screen_streaks


def test_core_streak_gate_exhaustion_negative_streak():
    # Negative streak, length < 2 -> vetoed
    ctx_short = {
        "streak_direction": "negative",
        "streak_length": 1,
        "robust_z": -2.5,
        "relative_return": 0.02,
    }
    decision = core_streak_gate(ctx_short, z_threshold=-0.5, require_exhaustion=True)
    assert not decision.allowed
    assert decision.reason == "streak_length_below_exhaustion_minimum"
    assert not decision.exhaustion_confirmed

    # Negative streak, length >= 2, unconfirmed momentum (R_rel <= 0) -> vetoed
    ctx_unconfirmed = {
        "streak_direction": "negative",
        "streak_length": 3,
        "robust_z": -2.5,
        "relative_return": -0.01,
    }
    decision = core_streak_gate(ctx_unconfirmed, z_threshold=-0.5, require_exhaustion=True)
    assert not decision.allowed
    assert decision.reason == "unconfirmed_negative_momentum"
    assert not decision.exhaustion_confirmed

    # Negative streak, length >= 2, confirmed momentum (R_rel > 0) -> approved
    ctx_confirmed = {
        "streak_direction": "negative",
        "streak_length": 3,
        "robust_z": -2.5,
        "relative_return": 0.015,
    }
    decision = core_streak_gate(ctx_confirmed, z_threshold=-0.5, require_exhaustion=True)
    assert decision.allowed
    assert decision.reason == "approved"
    assert decision.exhaustion_confirmed


def test_core_streak_gate_exhaustion_positive_streak():
    # Positive streak, length < 2 -> vetoed
    ctx_short = {
        "streak_direction": "positive",
        "streak_length": 1,
        "robust_z": 2.5,
        "relative_return": -0.02,
    }
    decision = core_streak_gate(ctx_short, z_threshold=-0.5, require_exhaustion=True)
    assert not decision.allowed
    assert decision.reason == "streak_length_below_exhaustion_minimum"
    assert not decision.exhaustion_confirmed

    # Positive streak, length >= 2, unconfirmed momentum (R_rel >= 0) -> vetoed
    ctx_unconfirmed = {
        "streak_direction": "positive",
        "streak_length": 3,
        "robust_z": 2.5,
        "relative_return": 0.01,
    }
    decision = core_streak_gate(ctx_unconfirmed, z_threshold=-0.5, require_exhaustion=True)
    assert not decision.allowed
    assert decision.reason == "unconfirmed_positive_momentum"
    assert not decision.exhaustion_confirmed

    # Positive streak, length >= 2, confirmed momentum (R_rel < 0) -> approved
    ctx_confirmed = {
        "streak_direction": "positive",
        "streak_length": 3,
        "robust_z": 2.5,
        "relative_return": -0.015,
    }
    decision = core_streak_gate(ctx_confirmed, z_threshold=-0.5, require_exhaustion=True)
    assert decision.allowed
    assert decision.reason == "approved"
    assert decision.exhaustion_confirmed


def test_core_streak_gate_backwards_compatibility():
    # Without requiring exhaustion, unexhausted streaks are still approved
    ctx = {
        "streak_direction": "negative",
        "streak_length": 1,
        "robust_z": -1.5,
        "relative_return": -0.01,
    }
    decision = core_streak_gate(ctx, z_threshold=-0.5, require_exhaustion=False)
    assert decision.allowed
    assert not decision.exhaustion_confirmed

    # Context flag require_exhaustion_bar triggers exhaustion requirement
    ctx_with_flag = {
        "streak_direction": "negative",
        "streak_length": 1,
        "robust_z": -1.5,
        "relative_return": -0.01,
        "require_exhaustion_bar": True,
    }
    decision_flag = core_streak_gate(ctx_with_flag, z_threshold=-0.5)
    assert not decision_flag.allowed
    assert decision_flag.reason == "streak_length_below_exhaustion_minimum"


def test_screen_streaks_with_exhaustion_policy():
    dates = pd.date_range("2026-08-01", periods=8, tz="UTC")
    spy_closes = [100.0 + i for i in range(8)]
    benchmark = pd.Series(spy_closes, index=dates)

    # Symbol A: negative streak continuing down every day (no exhaustion)
    # Symbol B: underperforms for first 6 days, then on day 7 turns up (exhaustion confirmed!)
    rows = []
    for index, d in enumerate(dates):
        rows.append({"date": d, "symbol": "SPY", "close": 100.0 + index})
        rows.append({"date": d, "symbol": "SYMA", "close": 100.0 - index * 2})
        b_close = 100.0 - index * 2 if index < 7 else 95.0
        rows.append({"date": d, "symbol": "SYMB", "close": b_close})

    bars = pd.DataFrame(rows)

    # Policy requiring exhaustion
    policy_exhaust = StreakPolicy(min_length=2, max_length=8, directions=("negative", "positive"), require_exhaustion=True)
    selected_exhaust, decisions_exhaust = screen_streaks(bars, benchmark, {"SYMA", "SYMB"}, policy_exhaust)
    dec_map = {d["ticker"]: d for d in decisions_exhaust}
    # SYMA has no exhaustion -> rejected
    assert not dec_map["SYMA"]["accepted"]
    assert "unconfirmed_momentum_no_exhaustion" in dec_map["SYMA"]["reasons"]
    # SYMB has confirmed exhaustion on day 7 -> accepted!
    assert dec_map["SYMB"]["accepted"]
    assert dec_map["SYMB"]["exhaustion_confirmed"]

    # Policy without requiring exhaustion
    policy_standard = StreakPolicy(min_length=2, max_length=8, directions=("negative", "positive"), require_exhaustion=False)
    selected_std, decisions_std = screen_streaks(bars, benchmark, {"SYMA", "SYMB"}, policy_standard)
    dec_std_map = {d["ticker"]: d for d in decisions_std}
    # SYMA is accepted because length 7 is between 2 and 8
    assert dec_std_map["SYMA"]["accepted"]
