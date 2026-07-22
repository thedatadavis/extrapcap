from extrapcap.selection import core_streak_gate, streak_priority_key


def test_core_streak_gate_requires_negative_two_to_five_day_streak_and_z_gate():
    approved = core_streak_gate(
        {"streak_direction": "negative", "streak_length": 4, "robust_z": -2.4},
        -2.0,
    )
    assert approved.allowed
    assert approved.strategy_route == "core_mean_reversion"
    assert not core_streak_gate(
        {"streak_direction": "positive", "streak_length": 4, "robust_z": 2.4},
        -2.0,
    ).allowed
    assert core_streak_gate(
        {"streak_direction": "negative", "streak_length": 4, "robust_z": -0.4},
        -2.0,
    ).reason == "robust_z_above_entry_threshold"


def test_longer_negative_streaks_receive_higher_selection_priority():
    rows = [
        {"ticker": "TWO", "streak_direction": "negative", "streak_length": 2, "robust_z": -3.0},
        {"ticker": "FOUR", "streak_direction": "negative", "streak_length": 4, "robust_z": -2.1},
        {"ticker": "POS", "streak_direction": "positive", "streak_length": 5, "robust_z": 2.5},
    ]
    assert [row["ticker"] for row in sorted(rows, key=streak_priority_key)] == ["FOUR", "TWO", "POS"]
