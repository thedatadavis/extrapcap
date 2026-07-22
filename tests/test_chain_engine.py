import pandas as pd
import pytest

from extrapcap.backtest.chain_engine import run_chain_backtest


def test_chain_backtest_caps_expiry_loss_and_reports_tier():
    observations = pd.DataFrame([
        {"entry_date": "2026-07-01", "underlying": "ABC", "expiry": "2026-07-02", "short_strike": 100, "long_strike": 95, "short_bid": 1.5, "long_ask": 0.4, "expiry_underlying_close": 102, "data_tier": "indicative"},
        {"entry_date": "2026-07-02", "underlying": "ABC", "expiry": "2026-07-03", "short_strike": 100, "long_strike": 95, "short_bid": 1.5, "long_ask": 0.4, "expiry_underlying_close": 80, "data_tier": "indicative"},
    ])
    result = run_chain_backtest(observations)
    assert result.trades == 2
    assert result.wins == 1
    assert result.total_pnl < 0


def test_reconstructed_data_requires_explicit_opt_in():
    row = {"entry_date": "2026-07-01", "underlying": "ABC", "expiry": "2026-07-02", "short_strike": 100, "long_strike": 95, "short_bid": 1.5, "long_ask": 0.4, "expiry_underlying_close": 102, "data_tier": "reconstructed"}
    with pytest.raises(ValueError, match="allow_reconstructed"):
        run_chain_backtest(pd.DataFrame([row]))
