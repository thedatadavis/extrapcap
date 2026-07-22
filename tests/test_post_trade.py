from datetime import date

from extrapcap.execution.monitor import ExecutionMonitor


class FakeClient:
    def order(self, order_id):
        return {"id": order_id, "status": "filled", "filled_qty": "1"}

    def account(self):
        return {"status": "ACTIVE"}

    def positions(self):
        return []


class FakeReviewer:
    def post_trade_commentary(self, observation):
        return {
            "commentary": "Filled observation recorded.",
            "anomalies": [],
            "reason": "test",
        }


def test_terminal_fill_writes_post_trade_commentary(tmp_path):
    from extrapcap.ledger import AuditLedger

    monitor = ExecutionMonitor(FakeClient(), AuditLedger(tmp_path / "logs"), FakeReviewer())
    monitor.observe("order-1", date(2026, 7, 22))
    rationale = (tmp_path / "logs" / "rationales" / "2026-07-22.jsonl").read_text()
    assert "post_trade_commentary" in rationale
    assert "Filled observation recorded." in rationale
