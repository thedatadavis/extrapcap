from datetime import date
import json

from extrapcap.execution.live_position_manager import manage_live_positions
from extrapcap.execution.monitor import ExecutionMonitor
from extrapcap.execution.orders import OrderEnvelope
from extrapcap.ledger import AuditLedger
from extrapcap.options_data import DataTier


class FakeClient:
    def order(self, order_id):
        return {"id": order_id, "status": "filled", "filled_qty": "1"}

    def account(self):
        return {"id": "private-id", "account_number": "private-number", "status": "ACTIVE"}

    def positions(self):
        return [{"symbol": "SPY260724P00739000"}]


def test_monitor_records_terminal_fill(tmp_path):
    observation = ExecutionMonitor(FakeClient(), AuditLedger(tmp_path / "logs")).wait_for_terminal("abc", trading_day=date(2026, 7, 22))
    assert observation.order["status"] == "filled"
    assert list((tmp_path / "logs" / "fills").glob("*.jsonl"))
    record = json.loads(next((tmp_path / "logs" / "fills").glob("*.jsonl")).read_text())
    assert "id" not in record["account"]
    assert "account_number" not in record["account"]


def test_live_position_manager_marks_held_legs_and_dry_runs_close(tmp_path):
    class FakeOptions:
        def chain_all(self, *args, **kwargs):
            return {
                "snapshots": {
                    "SPY260724P00739000": {"latestQuote": {"bp": 0.50, "ap": 0.60}},
                    "SPY260724P00734000": {"latestQuote": {"bp": 0.45, "ap": 0.55}},
                }
            }, DataTier.INDICATIVE

    class FakeSubmitClient:
        def __init__(self):
            self.submitted = []

        def positions(self):
            return [
                {"symbol": "SPY260724P00739000", "qty": "1"},
                {"symbol": "SPY260724P00734000", "qty": "-1"},
            ]

        def submit_order(self, order):
            self.submitted.append(order)
            return {"status": "dry_run"}

    envelope = OrderEnvelope(
        "2026-07-21",
        "SPY",
        "sell_to_open",
        (
            {"symbol": "SPY260724P00739000", "asset_class": "us_option", "side": "sell", "position_intent": "sell_to_open"},
            {"symbol": "SPY260724P00734000", "asset_class": "us_option", "side": "buy", "position_intent": "buy_to_open"},
        ),
        "core",
        limit_price=0.40,
    )
    registry = tmp_path / "ids.jsonl"
    registry.write_text(
        json.dumps({
            "client_order_id": envelope.client_order_id,
            "payload": envelope.alpaca_payload(),
            "metadata": {"entry_credit": 0.40, "spread_width": 5.0, "opened_at": "2026-07-21"},
        }) + "\n",
        encoding="utf-8",
    )
    client = FakeSubmitClient()
    result = manage_live_positions(
        client,
        FakeOptions(),
        registry_path=registry,
        as_of=date(2026, 7, 22),
        ledger=AuditLedger(tmp_path / "logs"),
    )
    assert result[0]["status"] == "close"
    assert result[0]["ticker"] == "SPY"
    assert result[0]["contract_ids"] == ["SPY260724P00739000", "SPY260724P00734000"]
    assert client.submitted[0]["legs"][0]["position_intent"] == "buy_to_close"
