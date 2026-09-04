from datetime import date

import pandas as pd
import pytest

from modal_app.bar_store import read_bar_partitions, write_bar_partitions


class FakeVolume:
    def __init__(self):
        self.commits = 0
        self.reloads = 0

    def commit(self):
        self.commits += 1

    def reload(self):
        self.reloads += 1


def _bars():
    return pd.DataFrame(
        [
            {
                "date": "2026-08-31T04:00:00Z",
                "symbol": "SPY",
                "open": 1,
                "high": 2,
                "low": 1,
                "close": 2,
                "volume": 100,
                "vwap": 1.5,
            },
            {
                "date": "2026-09-01T04:00:00Z",
                "symbol": "AAPL",
                "open": 10,
                "high": 12,
                "low": 9,
                "close": 11,
                "volume": 200,
                "vwap": 10.5,
            },
        ]
    )


def test_write_bar_partitions_is_immutable_and_commits(tmp_path):
    pytest.importorskip("pyarrow")
    volume = FakeVolume()

    first = write_bar_partitions(
        _bars(), volume, root=str(tmp_path), reference_date=date(2026, 9, 2)
    )
    second = write_bar_partitions(
        _bars(), volume, root=str(tmp_path), reference_date=date(2026, 9, 2)
    )

    assert first["partitions_written"] == 2
    assert first["rows_written"] == 2
    assert second["partitions_written"] == 0
    assert second["partitions_skipped"] == 2
    assert volume.commits == 1


def test_read_bar_partitions_reloads_and_round_trips(tmp_path):
    pytest.importorskip("pyarrow")
    volume = FakeVolume()
    write_bar_partitions(_bars(), volume, root=str(tmp_path), reference_date=date(2026, 9, 2))

    result = read_bar_partitions(volume, root=str(tmp_path))

    assert volume.reloads == 1
    assert list(result["symbol"]) == ["SPY", "AAPL"]
    assert list(result["close"]) == [2, 11]


def test_write_bar_partitions_purges_only_old_date_partitions(tmp_path):
    pytest.importorskip("pyarrow")
    volume = FakeVolume()
    write_bar_partitions(
        _bars(), volume, root=str(tmp_path), retention_days=1, reference_date=date(2026, 9, 1)
    )

    result = write_bar_partitions(
        pd.DataFrame(), volume, root=str(tmp_path), retention_days=1, reference_date=date(2026, 9, 2)
    )

    assert result["partitions_purged"] == 1
    assert (tmp_path / "date=2026-09-01").exists()
