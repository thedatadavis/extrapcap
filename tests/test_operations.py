from datetime import datetime, timezone

import pandas as pd

from extrapcap.orchestration.windows import execution_window
from extrapcap.config import RiskConfig
from extrapcap.options import VerticalSpread
from extrapcap.risk import IntradayRiskState, PortfolioRiskState, approve_candidate, approve_intraday_order
from extrapcap.data.refresh_cli import build_bar_metadata, symbols_from_greenlist
from extrapcap.data.normalize import completed_daily_bars, completed_formation_reason
from extrapcap.orchestration.intraday_cli import expiration_window
from extrapcap.execution.position_manager import ManagedPosition, build_close_envelope, evaluate_credit_exit
from extrapcap.execution.orders import OrderEnvelope


def test_execution_windows_have_open_and_close_guards():
    assert execution_window(datetime(2026, 7, 22, 9, 30)) == "market_open_guard"
    assert execution_window(datetime(2026, 7, 22, 12, 0)) == "lunch_liquidity"
    assert execution_window(datetime(2026, 7, 22, 16, 30)) == "closed"
    assert execution_window(datetime(2026, 7, 22, 14, 0, tzinfo=timezone.utc)) == "open_liquidity"


def test_risk_brakes_reject_daily_loss():
    spread = VerticalSpread("ABC", 100, 95, 1.0)
    decision = approve_candidate(spread, PortfolioRiskState(nav=100_000, daily_pnl=-2_100), RiskConfig())
    assert decision == type(decision)(False, "daily loss cap")


def test_risk_brakes_enforce_options_level_and_buying_power():
    spread = VerticalSpread("ABC", 100, 95, 1.0)
    low_level = PortfolioRiskState(nav=100_000, options_buying_power=10_000, options_trading_level=2)
    assert approve_candidate(spread, low_level, RiskConfig()).reason == "level 3 options approval required"
    low_power = PortfolioRiskState(nav=100_000, options_buying_power=100, options_trading_level=3)
    assert approve_candidate(spread, low_power, RiskConfig()).reason == "insufficient options buying power"
    blocked = PortfolioRiskState(nav=100_000, options_buying_power=10_000, options_trading_level=3, trading_blocked=True)
    assert approve_candidate(spread, blocked, RiskConfig()).reason == "account trading blocked"


def test_bar_metadata_records_request_and_observed_bounds():
    frame = pd.DataFrame([
        {"date": pd.Timestamp("2026-07-01", tz="UTC"), "symbol": "SPY"},
        {"date": pd.Timestamp("2026-07-02", tz="UTC"), "symbol": "SPY"},
    ])
    metadata = build_bar_metadata(
        frame,
        ["SPY"],
        datetime(2026, 6, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 3, tzinfo=timezone.utc),
        datetime(2026, 7, 3, tzinfo=timezone.utc),
    )
    assert metadata["row_count"] == 2
    assert metadata["requested_start"].startswith("2026-06-01")
    assert metadata["date_max"].startswith("2026-07-02")


def test_bar_metadata_records_missing_symbol_coverage():
    frame = pd.DataFrame([
        {"date": pd.Timestamp("2026-07-01", tz="UTC"), "symbol": "SPY"},
        {"date": pd.Timestamp("2026-07-01", tz="UTC"), "symbol": "ABC"},
    ])
    metadata = build_bar_metadata(
        frame,
        ["SPY", "ABC", "MISSING"],
        datetime(2026, 6, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 3, tzinfo=timezone.utc),
        datetime(2026, 7, 3, tzinfo=timezone.utc),
    )
    assert metadata["coverage"] == {
        "requested_symbol_count": 3,
        "observed_symbol_count": 2,
        "missing_symbol_count": 1,
        "missing_symbols": ["MISSING"],
        "complete": False,
    }


def test_bar_metadata_records_provider_symbol_errors():
    frame = pd.DataFrame([{"date": pd.Timestamp("2026-07-01", tz="UTC"), "symbol": "SPY"}])
    errors = {"BAD": {"status": 400, "reason": "Bad Request", "detail": "unsupported symbol"}}
    metadata = build_bar_metadata(
        frame,
        ["SPY", "BAD"],
        datetime(2026, 6, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 3, tzinfo=timezone.utc),
        datetime(2026, 7, 3, tzinfo=timezone.utc),
        symbol_errors=errors,
    )
    assert metadata["symbol_errors"] == errors
    assert metadata["coverage"]["missing_symbols"] == ["BAD"]
    assert metadata["coverage"]["symbol_errors"] == errors


def test_symbols_from_greenlist_includes_benchmark_once(tmp_path):
    path = tmp_path / "greenlist.csv"
    path.write_text("ticker,sector\nABC,Technology\nSPY,Broad Market ETF\nABC,Technology\n", encoding="utf-8")
    assert symbols_from_greenlist(path) == ["SPY", "ABC"]


def test_daily_bar_filter_excludes_current_partial_session():
    frame = pd.DataFrame(
        [
            {"date": pd.Timestamp("2026-07-21 04:00:00", tz="UTC"), "symbol": "SPY", "close": 100},
            {"date": pd.Timestamp("2026-07-22 04:00:00", tz="UTC"), "symbol": "SPY", "close": 101},
        ]
    )
    during_session = datetime(2026, 7, 22, 16, 0, tzinfo=timezone.utc)
    filtered = completed_daily_bars(frame, during_session)
    assert filtered["date"].tolist() == [pd.Timestamp("2026-07-21 04:00:00", tz="UTC")]


def test_daily_bar_filter_accepts_session_after_finalization_delay():
    frame = pd.DataFrame(
        [{"date": pd.Timestamp("2026-07-22 04:00:00", tz="UTC"), "symbol": "SPY", "close": 101}]
    )
    after_close = datetime(2026, 7, 22, 20, 16, tzinfo=timezone.utc)
    assert len(completed_daily_bars(frame, after_close)) == 1


def test_completed_formation_requires_fresh_aligned_session():
    now = datetime(2026, 7, 22, 16, 0, tzinfo=timezone.utc)
    assert completed_formation_reason("2026-07-21T04:00:00Z", "2026-07-21T04:00:00Z", now=now) is None
    assert completed_formation_reason("2026-07-21T04:00:00Z", "2026-07-22T04:00:00Z", now=now) == "formation_bar_mismatch"
    assert completed_formation_reason("2026-07-15T04:00:00Z", None, now=now) == "latest_completed_bar_stale"


def test_intraday_expiration_window_is_bounded():
    lower, upper = expiration_window(datetime(2026, 7, 22, tzinfo=timezone.utc), 2, 35)
    assert lower == "2026-07-24"
    assert upper == "2026-08-26"


def test_intraday_controls_reject_duplicate_and_bad_fill():
    now = datetime(2026, 7, 22, 15, 0, tzinfo=timezone.utc)
    cfg = RiskConfig(max_orders_per_symbol_per_day=1, intraday_cooldown_minutes=15, max_fill_deviation_pct=0.10)
    assert approve_intraday_order(IntradayRiskState("SPY", orders_today=1, now=now), cfg).reason == "symbol daily order cap"
    decision = approve_intraday_order(
        IntradayRiskState("SPY", now=now, modeled_credit=1.0, observed_credit=0.8), cfg
    )
    assert decision == type(decision)(False, "fill-quality circuit breaker")
    assert approve_intraday_order(
        IntradayRiskState("SPY", market_is_open=False, now=now), cfg
    ).reason == "broker market clock closed"


def test_position_manager_creates_defined_risk_close_orders():
    open_order = OrderEnvelope(
        "2026-07-01",
        "SPY",
        "sell_to_open",
        (
            {"symbol": "SPY-short", "asset_class": "us_option", "side": "sell", "position_intent": "sell_to_open"},
            {"symbol": "SPY-long", "asset_class": "us_option", "side": "buy", "position_intent": "buy_to_open"},
        ),
        "core",
        limit_price=1.00,
    )
    state = ManagedPosition(open_order, 1.0, 0.45, 5.0, datetime(2026, 7, 1).date(), datetime(2026, 7, 2).date())
    decision = evaluate_credit_exit(state, RiskConfig())
    assert decision == type(decision)("close", "profit_target", 0.5, 1)
    close = build_close_envelope(state, decision)
    assert close.legs[0]["position_intent"] == "buy_to_close"
    assert close.legs[1]["position_intent"] == "sell_to_close"
