import json

import pytest

from extrapcap.execution.account_risk import build_portfolio_risk_state


SHORT = "SPY260724P00739000"
LONG = "SPY260724P00734000"


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
        {"equity": "100000", "last_equity": "99000"},
        [
            {"symbol": SHORT, "qty": "-1", "asset_class": "us_option"},
            {"symbol": LONG, "qty": "1", "asset_class": "us_option"},
        ],
        [],
        registry_path=registry,
        report_root=tmp_path / "reports",
    )
    assert state.core_open_risk == pytest.approx(460.0)
    assert state.daily_pnl == pytest.approx(1000.0)
    assert state.ticker_open_risk == {"SPY": pytest.approx(460.0)}


def test_account_risk_fails_closed_on_untracked_option_position(tmp_path):
    with pytest.raises(RuntimeError, match="untracked paper option positions"):
        build_portfolio_risk_state(
            {"equity": "100000"},
            [{"symbol": SHORT, "qty": "-1", "asset_class": "us_option"}],
            [],
            registry_path=tmp_path / "missing.jsonl",
            report_root=tmp_path / "reports",
        )


def test_account_risk_fails_closed_on_untracked_option_order(tmp_path):
    with pytest.raises(RuntimeError, match="untracked paper option orders"):
        build_portfolio_risk_state(
            {"equity": "100000"},
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
