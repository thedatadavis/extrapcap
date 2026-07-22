import pandas as pd

from extrapcap.config import AppConfig, StrategyConfig
from extrapcap.research.matrix import Scenario, run_matrix
from extrapcap.backtest.engine import run_backtest


def test_research_matrix_marks_missing_dependencies_instead_of_faking_results():
    bars = pd.read_csv("examples/sample_bars.csv", parse_dates=["date"])
    benchmark = bars.loc[bars.symbol == "SPY"].set_index("date")["close"]
    results = run_matrix(
        bars[bars.symbol != "SPY"],
        benchmark,
        AppConfig(strategy=StrategyConfig(z_window=5, z_threshold=-0.5)),
    )
    by_name = {result.scenario: result for result in results}
    assert by_name["baseline_no_classifier_eod"].status == "completed"
    assert by_name["improved_classifier_eod"].reason == "classifier_model_required"
    assert by_name["improved_news_filter"].reason == "news_event_input_required"
    assert by_name["improved_intraday_loop"].reason == "intraday_bars_required"


def test_news_matrix_uses_structural_risk_events_as_vetoes():
    bars = pd.read_csv("examples/sample_bars.csv", parse_dates=["date"])
    benchmark = bars.loc[bars.symbol == "SPY"].set_index("date")["close"]
    news = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-24"]),
        "symbol": ["ABC"],
        "structural_risk": [True],
    })
    result = run_matrix(
        bars[bars.symbol != "SPY"],
        benchmark,
        AppConfig(strategy=StrategyConfig(z_window=5, z_threshold=-0.5)),
        scenarios=[Scenario("news", "improved", news_filter=True)],
        news_events=news,
    )[0]
    assert result.status == "completed"
    assert result.result["news_filter_used"] is True


def test_intraday_modes_apply_session_window_and_duplicate_gates():
    times = pd.date_range("2026-07-22 14:00:00+00:00", periods=8, freq="5min")
    rows = (
        [{"date": t, "symbol": "SPY", "close": price} for t, price in zip(times, [100, 100.1, 100, 100.1, 100, 100.1, 100, 100.1])]
        + [{"date": t, "symbol": "ABC", "close": price} for t, price in zip(times, [100, 101, 102, 103, 100, 97, 94, 91])]
    )
    frame = pd.DataFrame(rows)
    benchmark = frame.loc[frame.symbol == "SPY"].set_index("date")["close"]
    cfg = AppConfig(strategy=StrategyConfig(z_window=5, z_threshold=-0.5))
    hybrid = run_backtest(frame[frame.symbol != "SPY"], benchmark, "improved", cfg, mode="hybrid")
    intraday = run_backtest(frame[frame.symbol != "SPY"], benchmark, "improved", cfg, mode="intraday_loop")
    assert hybrid.trades == 0
    assert hybrid.intraday_vetoes > 0
    assert intraday.trades == 1
