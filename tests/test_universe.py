import json

import pandas as pd

from extrapcap.universe.greenlist import GreenlistFilter, filter_greenlist, load_sector_map, refresh_greenlist
from extrapcap.universe.streak_cli import bar_coverage, missing_bar_decisions
from extrapcap.universe.streak_screen import StreakPolicy, screen_streaks


def test_greenlist_logs_acceptance_and_rejection():
    rows = [
        {"ticker": "A", "cap_tier": "Mega-Cap", "avg_volume": "1000000", "exchange": "NMS"},
        {"ticker": "B", "cap_tier": "Small-Cap", "avg_volume": "1000000", "exchange": "NMS"},
    ]
    accepted, decisions = filter_greenlist(rows, GreenlistFilter())
    assert [row["ticker"] for row in accepted] == ["A"]
    assert decisions[1]["reasons"] == ["cap_tier_excluded"]


def test_greenlist_snapshot_does_not_truncate_accepted_universe(monkeypatch, tmp_path):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            rows = ["ticker,cap_tier,avg_volume,exchange,sector"]
            rows.extend(f"TICKER{index},Mega-Cap,1000000,NMS,Technology" for index in range(1001))
            return ("\n".join(rows) + "\n").encode()

    monkeypatch.setattr("extrapcap.universe.greenlist.urlopen", lambda *_args, **_kwargs: Response())
    snapshot = refresh_greenlist(tmp_path)
    assert len(snapshot.read_text(encoding="utf-8").splitlines()) == 1002
    metadata = json.loads(snapshot.with_suffix(".json").read_text(encoding="utf-8"))
    assert metadata["raw_rows"] == 1001
    assert metadata["accepted_rows"] == 1001


def test_streak_screen_uses_signed_completed_relative_streaks():
    dates = pd.date_range("2026-01-01", periods=6, tz="UTC")
    bars = pd.DataFrame(
        [{"date": day, "symbol": "SPY", "close": 100.0 + index} for index, day in enumerate(dates)]
        + [{"date": day, "symbol": "ABC", "close": 100.0 - index * 2} for index, day in enumerate(dates)]
    )
    benchmark = bars[bars.symbol.eq("SPY")].set_index("date")["close"]
    selected, decisions = screen_streaks(bars, benchmark, {"ABC"}, StreakPolicy(2, 5, ("negative",)))
    assert selected.iloc[0]["streak_direction"] == "negative"
    assert selected.iloc[0]["streak_length"] == 5
    assert decisions[0]["accepted"] is True


def test_sector_map_is_loaded_from_versioned_greenlist(tmp_path):
    path = tmp_path / "greenlist-test.csv"
    path.write_text("ticker,sector\nABC,Technology\nBAD,N/A\n", encoding="utf-8")
    result = load_sector_map(path)
    assert result["ABC"] == "Technology"
    assert result["SPY"] == "Broad Market ETF"
    assert "BAD" not in result


def test_bar_coverage_records_every_greenlist_ticker_without_bars():
    greenlist = pd.DataFrame([
        {"ticker": "ABC", "sector": "Technology"},
        {"ticker": "MISSING", "sector": "Energy"},
    ])
    bars = pd.DataFrame([
        {"date": pd.Timestamp("2026-01-01", tz="UTC"), "symbol": "SPY", "close": 100.0},
        {"date": pd.Timestamp("2026-01-01", tz="UTC"), "symbol": "ABC", "close": 100.0},
    ])
    coverage = bar_coverage(greenlist, bars)
    assert coverage["requested_symbol_count"] == 3
    assert coverage["missing_symbols"] == ["MISSING"]
    assert coverage["complete"] is False
    assert missing_bar_decisions(greenlist, coverage)[0]["reasons"] == ["missing_bars"]
