from datetime import datetime, timezone
import json

from extrapcap.execution.intraday_state import build_intraday_risk_state


def test_intraday_state_deduplicates_broker_and_registry_submissions(tmp_path):
    recorded = "2026-07-22T14:15:00+00:00"
    path = tmp_path / "ids.jsonl"
    path.write_text(
        json.dumps(
            {
                "client_order_id": "xpc-1",
                "execution_status": "submitted",
                "recorded_at": recorded,
                "trading_day": "2026-07-22",
                "ticker": "SPY",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    broker_orders = [
        {
            "id": "alpaca-1",
            "client_order_id": "xpc-1",
            "created_at": recorded,
            "legs": [{"symbol": "SPY260724P00739000", "asset_class": "us_option"}],
        },
        {
            "id": "alpaca-2",
            "client_order_id": "manual-order",
            "created_at": "2026-07-22T14:30:00Z",
            "legs": [{"symbol": "SPY260724P00734000", "asset_class": "us_option"}],
        },
    ]
    state = build_intraday_risk_state(
        "SPY",
        datetime(2026, 7, 22, 15, tzinfo=timezone.utc),
        broker_orders,
        registry_path=path,
    )
    assert state.orders_today == 2
    assert state.last_order_at == datetime(2026, 7, 22, 14, 30, tzinfo=timezone.utc)


def test_intraday_state_ignores_dry_runs_other_symbols_and_prior_days(tmp_path):
    path = tmp_path / "ids.jsonl"
    rows = [
        {
            "client_order_id": "xpc-dry",
            "execution_status": "dry_run",
            "trading_day": "2026-07-22",
            "ticker": "SPY",
        },
        {
            "client_order_id": "xpc-old",
            "execution_status": "submitted",
            "trading_day": "2026-07-21",
            "ticker": "SPY",
        },
        {
            "client_order_id": "xpc-other",
            "execution_status": "submitted",
            "trading_day": "2026-07-22",
            "ticker": "AAPL",
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    state = build_intraday_risk_state(
        "SPY",
        datetime(2026, 7, 22, 15, tzinfo=timezone.utc),
        [],
        registry_path=path,
    )
    assert state.orders_today == 0
    assert state.last_order_at is None
