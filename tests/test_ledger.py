import json
from datetime import date
from extrapcap.ledger import AuditLedger
from extrapcap.playback import replay_day


def test_ledger_is_replayable(tmp_path):
    ledger = AuditLedger(tmp_path / "logs")
    path = ledger.append("signals", {"symbol": "ABC", "decision": "reject"}, date(2026, 7, 22))
    assert path.exists()
    events = replay_day(tmp_path / "logs", "2026-07-22")
    assert len(events) == 1
    assert events[0]["category"] == "signals"
    assert events[0]["decision"] == "reject"
    assert events[0]["ticker"] == "ABC"
    assert events[0]["journal"]["schema_version"] == 1


def test_ledger_indexes_underlying_and_option_contracts(tmp_path):
    ledger = AuditLedger(tmp_path / "logs")
    path = ledger.append(
        "orders",
        {
            "underlying": "SPY",
            "status": "dry_run",
            "order": {
                "legs": [
                    {"asset_class": "us_option", "symbol": "SPY260724P00739000"},
                    {"asset_class": "us_option", "symbol": "SPY260724P00734000"},
                ]
            },
        },
        date(2026, 7, 22),
    )
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["ticker"] == "SPY"
    assert record["contract_ids"] == ["SPY260724P00734000", "SPY260724P00739000"]
    assert record["journal"]["contract_details"][0]["expiration"] == "2026-07-24"
