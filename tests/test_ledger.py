from datetime import date
from extrapcap.ledger import AuditLedger
from extrapcap.playback import replay_day


def test_ledger_is_replayable(tmp_path):
    ledger = AuditLedger(tmp_path / "logs")
    path = ledger.append("signals", {"symbol": "ABC", "decision": "reject"}, date(2026, 7, 22))
    assert path.exists()
    events = replay_day(tmp_path / "logs", "2026-07-22")
    assert events == [{"category": "signals", "decision": "reject", "symbol": "ABC"}]
