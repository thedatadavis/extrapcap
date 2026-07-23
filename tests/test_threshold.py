import pytest

from extrapcap.models.threshold import evaluate_threshold, select_threshold, sweep_thresholds


def test_threshold_metrics_and_sweep_are_deterministic():
    results = sweep_thresholds(
        [0.51, 0.61, 0.72, 0.91],
        [0, 1, 1, 1],
        [-1.0, 0.28, 0.28, 0.28],
        [0.50, 0.70, 0.90],
    )
    assert results[0].observations == 4
    assert results[1].observations == 2
    assert results[1].precision == 1.0
    assert results[2].proxy_expectancy == pytest.approx(0.28)


def test_select_threshold_applies_constraints_and_uses_lcb():
    results = [
        evaluate_threshold([0.5] * 50, [1] * 50, [0.1] * 50, 0.50),
        evaluate_threshold([0.6] * 50, [1] * 50, [0.2] * 50, 0.60),
    ]
    selected = select_threshold(results, minimum_observations=50)
    assert selected.threshold == 0.60


def test_select_threshold_fails_closed_when_constraints_have_no_candidate():
    result = evaluate_threshold([0.7] * 2, [1, 0], [0.1, -1.0], 0.70)
    with pytest.raises(ValueError, match="no threshold"):
        select_threshold([result], minimum_observations=50)
