import json

import pytest

from extrapcap.execution.account_risk import build_portfolio_risk_state


SHORT = "SPY260724P00739000"
LONG = "SPY260724P00734000"


def account(**overrides):
    value = {
        "status": "ACTIVE",
        "equity": "100000",
        "last_equity": "100000",
        "options_buying_power": "50000",
        "options_trading_level": 3,
        "trading_blocked": False,
        "account_blocked": False,
        "trade_suspended_by_user": False,
    }
    value.update(overrides)
    return value


def test_account_risk_reconstructs_active_vertical_from_registry(tmp_path):
    registry = tmp_path / "ids.jsonl"
    registry.write_text(
        json.dumps(
            {
                "client_order_id": "xpc-1",
                "execution_status": "submitted",
                "ticker": "SPY",
                "sleeve": "core",
                "quantity": 1,
                "contract_ids": [SHORT, LONG],
                "payload": {"qty": 1, "legs": [{"symbol": SHORT}, {"symbol": LONG}]},
                "metadata": {"spread_width": 5.0, "entry_credit": 0.40},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    state = build_portfolio_risk_state(
        account(last_equity="99000"),
        [
            {"symbol": SHORT, "qty": "-1", "asset_class": "us_option"},
            {"symbol": LONG, "qty": "1", "asset_class": "us_option"},
        ],
        [],
        registry_path=registry,
        report_root=tmp_path / "reports",
        sector_by_ticker={"SPY": "Broad Market ETF"},
    )
    assert state.core_open_risk == pytest.approx(460.0)
    assert state.daily_pnl == pytest.approx(1000.0)
    assert state.ticker_open_risk == {"SPY": pytest.approx(460.0)}
    assert state.sector_open_risk == {"Broad Market ETF": pytest.approx(460.0)}


def test_account_risk_fails_closed_when_active_sector_is_unknown(tmp_path):
    registry = tmp_path / "ids.jsonl"
    registry.write_text(
        json.dumps(
            {
                "client_order_id": "xpc-1",
                "execution_status": "submitted",
                "ticker": "SPY",
                "sleeve": "core",
                "quantity": 1,
                "contract_ids": [SHORT, LONG],
                "metadata": {"spread_width": 5.0, "entry_credit": 0.40},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="missing sector metadata"):
        build_portfolio_risk_state(
            account(),
            [{"symbol": SHORT, "qty": "-1"}, {"symbol": LONG, "qty": "1"}],
            [],
            registry_path=registry,
            report_root=tmp_path / "reports",
            sector_by_ticker={},
        )


def test_account_risk_fails_closed_on_untracked_option_position(tmp_path):
    with pytest.raises(RuntimeError, match="untracked paper option positions"):
        build_portfolio_risk_state(
            account(),
            [{"symbol": SHORT, "qty": "-1", "asset_class": "us_option"}],
            [],
            registry_path=tmp_path / "missing.jsonl",
            report_root=tmp_path / "reports",
        )


def test_account_risk_fails_closed_on_untracked_option_order(tmp_path):
    with pytest.raises(RuntimeError, match="untracked paper option orders"):
        build_portfolio_risk_state(
            account(),
            [],
            [
                {
                    "id": "alpaca-order-1",
                    "client_order_id": "unknown-order",
                    "legs": [{"symbol": SHORT, "asset_class": "us_option"}],
                }
            ],
            registry_path=tmp_path / "missing.jsonl",
            report_root=tmp_path / "reports",
        )


def test_account_risk_carries_live_options_capacity(tmp_path):
    state = build_portfolio_risk_state(
        account(options_buying_power="12345", options_trading_level=3),
        [],
        [],
        registry_path=tmp_path / "missing.jsonl",
        report_root=tmp_path / "reports",
    )
    assert state.options_buying_power == pytest.approx(12345)
    assert state.options_trading_level == 3
    assert state.trading_blocked is False


def test_account_risk_fails_closed_when_options_capacity_is_missing(tmp_path):
    incomplete = account()
    incomplete.pop("options_buying_power")
    with pytest.raises(RuntimeError, match="missing options_buying_power"):
        build_portfolio_risk_state(
            incomplete,
            [],
            [],
            registry_path=tmp_path / "missing.jsonl",
            report_root=tmp_path / "reports",
        )
