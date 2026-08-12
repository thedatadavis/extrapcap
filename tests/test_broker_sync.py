from datetime import UTC, date, datetime

import pytest

from extrapcap.execution.broker_sync import synchronize_broker_state
from extrapcap.execution.position_manager import manage_live_positions

LONG = "ABC260821C00050000"
SHORT = "ABC260821C00055000"


def _configured_legs():
    return [
        {
            "symbol": LONG,
            "asset_class": "us_option",
            "side": "buy",
            "position_intent": "buy_to_open",
            "ratio_qty": 1,
        },
        {
            "symbol": SHORT,
            "asset_class": "us_option",
            "side": "sell",
            "position_intent": "sell_to_open",
            "ratio_qty": 1,
        },
    ]


def _broker_positions(long_price=2.4, short_price=0.6):
    return [
        {"symbol": LONG, "asset_class": "us_option", "qty": "1", "current_price": str(long_price)},
        {
            "symbol": SHORT,
            "asset_class": "us_option",
            "qty": "-1",
            "current_price": str(short_price),
        },
    ]


class SyncClient:
    def orders_after(self, _after):
        return [
            {
                "id": "broker-1",
                "client_order_id": "xpc-1",
                "status": "filled",
                "filled_at": "2026-08-12T14:00:00Z",
                "filled_qty": "1",
                "filled_avg_price": "1.80",
                "legs": [
                    {"symbol": LONG, "filled_avg_price": "2.30"},
                    {"symbol": SHORT, "filled_avg_price": "0.50"},
                ],
            }
        ]

    def positions(self):
        return _broker_positions()

    def open_orders(self):
        return []


class SyncStore:
    def __init__(self):
        self.created = []
        self.updated = []

    def get_active_positions(self):
        return []

    def get_orders(self):
        return [
            {
                "client_order_id": "xpc-1",
                "ticker": "ABC",
                "sleeve": "asymmetric",
                "side": "buy_to_open",
                "strategy_variant": "bearish_reversal_watch",
                "quantity": 1,
                "legs": _configured_legs(),
                "metadata": {"selection_context": {"robust_z": -2.4}},
            }
        ]

    def update_order(self, *args, **kwargs):
        self.updated.append((args, kwargs))

    def create_position(self, position, run_id=None):
        self.created.append((position, run_id))
        return 1

    def close_position(self, *_args, **_kwargs):
        raise AssertionError("position should not close")


def test_sync_materializes_filled_order_as_durable_position():
    store = SyncStore()
    summary = synchronize_broker_state(
        SyncClient(),
        store,
        run_id="run-1",
        now=datetime(2026, 8, 12, 15, tzinfo=UTC),
    )
    assert summary["positions_created"] == 1
    position, run_id = store.created[0]
    assert run_id == "run-1"
    assert position["entry_debit"] == 1.8
    assert position["long_symbol"] == LONG
    assert position["short_symbol"] == SHORT
    assert position["metadata"]["entry_client_order_id"] == "xpc-1"
    assert position["legs"][0]["entry_price"] == 2.3


class PositionClient:
    def __init__(self, positions):
        self._positions = positions
        self.submitted = []

    def positions(self):
        return self._positions

    def open_orders(self):
        return []

    def submit_order(self, payload):
        self.submitted.append(payload)
        return {
            "id": "close-1",
            "client_order_id": payload["client_order_id"],
            "status": "pending_new",
        }


def _durable_position(expiration="2026-08-21"):
    return {
        "id": 7,
        "ticker": "ABC",
        "long_symbol": LONG,
        "short_symbol": SHORT,
        "long_strike": 50,
        "short_strike": 55,
        "spread_width": 5,
        "entry_debit": 1.8,
        "entry_credit": None,
        "opened_at": "2026-08-12",
        "expiration": expiration,
        "sleeve": "asymmetric",
        "quantity": 1,
        "legs": _configured_legs(),
        "metadata": {"entry_client_order_id": "xpc-1"},
    }


def test_position_manager_refuses_orphan_broker_legs():
    client = PositionClient(_broker_positions())
    with pytest.raises(RuntimeError, match="require D1 entry metadata"):
        manage_live_positions(client, None, positions=[], as_of=date(2026, 8, 12))


def test_position_manager_submits_deterministic_forced_exit():
    client = PositionClient(_broker_positions())
    [record] = manage_live_positions(
        client,
        None,
        positions=[_durable_position(expiration="2026-08-14")],
        as_of=date(2026, 8, 12),
    )
    assert record["status"] == "close_submitted"
    assert record["reason"] == "forced_exit_dte_2"
    assert record["metadata"]["close_broker_order_id"] == "close-1"
    assert client.submitted[0]["order_class"] == "mleg"
