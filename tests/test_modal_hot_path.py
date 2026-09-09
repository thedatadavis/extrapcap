from datetime import UTC

from extrapcap.orchestration.basket_cycle import basket_rows
from modal_app.functions.candidate_review import _event_record


def test_d1_basket_rows_hydrate_feature_payload():
    rows = basket_rows([{"symbol": "ABC", "robust_z": -2.5, "features": '{"date":"2026-08-05T04:00:00+00:00","relative_return":-0.03,"streak_length":3,"streak_direction":"negative","reversion_probability":0.72}'}])
    assert rows[0]["formation_date"] == "2026-08-05T04:00:00+00:00"
    assert rows[0]["streak_length"] == 3
    assert rows[0]["reversion_probability"] == 0.72
    assert "features" not in rows[0]


def test_event_record_flattens_broker_result():
    event = _event_record({"ticker": "ABC", "result": {"order_id": "alpaca-1", "status": "new"}})
    assert event["status"] == "new"
    assert event["category"] == "orders"


def test_modal_app_imports_cleanly():
    import modal_app.app  # noqa: F401
    from modal_app.base import app
    assert app.name == "extrapcap"


def test_candidate_review_basket_fallback(monkeypatch):
    from datetime import datetime

    import modal_app.functions.candidate_review as cr_mod
    from modal_app.cf_client import CloudflareAPIClient

    calls = []

    def mock_get_basket(self, as_of=None, run_id=None):
        calls.append(as_of)
        if as_of is not None:
            return []
        return [{"symbol": "ABC", "robust_z": -2.5, "streak_length": 3}]

    class MockDatetime:
        @classmethod
        def now(cls, tz=None):
            # 2026-08-05 is a Wednesday (weekday 2)
            return datetime(2026, 8, 5, 14, 0, 0, tzinfo=UTC)

    monkeypatch.setattr(cr_mod, "datetime", MockDatetime)
    monkeypatch.setattr(CloudflareAPIClient, "get_basket", mock_get_basket)
    monkeypatch.setattr(CloudflareAPIClient, "register_run", lambda self, wf: "test-run-1")
    monkeypatch.setattr(CloudflareAPIClient, "complete_run", lambda self, run_id, summary, start_time: None)
    monkeypatch.setattr(CloudflareAPIClient, "append_events", lambda self, events, run_id=None: None)
    monkeypatch.setattr(CloudflareAPIClient, "record_order", lambda self, event, run_id=None: None)
    monkeypatch.setattr("extrapcap.execution.alpaca.AlpacaPaperClient.from_env", lambda: type("Paper", (), {"positions": lambda self: [], "open_orders": lambda self: []})())
    monkeypatch.setattr("extrapcap.data.alpaca_market.AlpacaMarketData.resolve_assets", lambda self, symbols, strict=False: {"ABC": {"id": "asset-abc", "symbol": "ABC"}})

    def mock_run_basket(basket, trading_day, dte_min, dte_max, preferred_dte, max_submissions, **kwargs):
        assert max_submissions == 8
        assert basket[0]["alpaca_symbol"] == "ABC"
        assert basket[0]["alpaca_asset_id"] == "asset-abc"
        return [{"ticker": "ABC", "status": "new"}]

    import extrapcap.orchestration.basket_cycle
    monkeypatch.setattr(extrapcap.orchestration.basket_cycle, "run_basket", mock_run_basket)

    res = cr_mod.candidate_review.local()
    assert res["status"] == "success"
    assert res["evaluated"] == 1
    assert res["unresolved_assets"] == 0
    assert calls == ["2026-08-05", None]


def test_candidate_review_skips_on_weekend(monkeypatch):
    from datetime import datetime

    import modal_app.functions.candidate_review as cr_mod
    from modal_app.cf_client import CloudflareAPIClient

    class MockSatDatetime:
        @classmethod
        def now(cls, tz=None):
            # 2026-08-08 is a Saturday (weekday 5)
            return datetime(2026, 8, 8, 14, 0, 0, tzinfo=UTC)

    monkeypatch.setattr(cr_mod, "datetime", MockSatDatetime)
    monkeypatch.setattr(CloudflareAPIClient, "register_run", lambda self, wf: "test-run-1")
    monkeypatch.setattr(CloudflareAPIClient, "complete_run", lambda self, run_id, summary, start_time: None)

    res = cr_mod.candidate_review.local()
    assert res["status"] == "skipped"
    assert res["reason"] == "weekend_market_closed"


def test_data_refresh_persists_all_bars_to_modal_storage(monkeypatch):
    from datetime import datetime

    import modal_app.functions.data_refresh as dr_mod
    from modal_app.cf_client import CloudflareAPIClient

    class MockDatetime:
        @classmethod
        def now(cls, tz=None):
            # 2026-08-06 04:00:00 UTC (Thursday 00:00 EDT) treats 2026-08-05 daily bar as completed
            return datetime(2026, 8, 6, 4, 0, 0, tzinfo=UTC)

    monkeypatch.setattr(dr_mod, "datetime", MockDatetime)

    stored_bars = []
    appended_events = []
    screened_greenlist = []

    def mock_write_bar_partitions(frame, volume, **kwargs):
        stored_bars.append(frame.copy())
        return {
            "input_rows": len(frame),
            "partitions_written": 2,
            "partitions_skipped": 0,
            "partitions_purged": 0,
        }

    def mock_run_streak_screening(cf, greenlist, bars_df, run_id=None):
        screened_greenlist.extend(greenlist)
        return {
            "status": "success",
            "universe_count": len(greenlist),
            "candidates_count": 1,
            "candidate_symbols": ["BG"],
            "run_id": run_id,
        }

    monkeypatch.setattr(CloudflareAPIClient, "register_run", lambda self, wf: "test-run-refresh")
    monkeypatch.setattr(CloudflareAPIClient, "complete_run", lambda self, run_id, summary, start_time: None)
    monkeypatch.setattr(dr_mod, "write_bar_partitions", mock_write_bar_partitions)
    monkeypatch.setattr(
        CloudflareAPIClient,
        "append_events",
        lambda self, events, run_id=None: appended_events.extend(events),
    )
    monkeypatch.setattr("modal_app.functions.streak_screen.run_streak_screening", mock_run_streak_screening)
    monkeypatch.setattr("extrapcap.secrets.require_paper_credentials", lambda: ("key", "sec"))

    class FakeMarketData:
        def __init__(self, api_key, secret_key):
            pass
        def stock_bars(self, symbols, start, end, timeframe, allow_partial=False):
            assert allow_partial is True
            return {
                "bars": {
                    "SPY": [{"t": "2026-08-05T04:00:00Z", "o": 1, "h": 2, "l": 1, "c": 2, "v": 100, "vw": 1.5}],
                    "BG": [{"t": "2026-08-05T04:00:00Z", "o": 10, "h": 20, "l": 10, "c": 15, "v": 200, "vw": 15.0}],
                    "XYZ": [{"t": "2026-08-05T04:00:00Z", "o": 5, "h": 5, "l": 5, "c": 5, "v": 50, "vw": 5.0}],
                },
                "errors": {},
                "unresolved_symbols": ["AXIA"],
            }

    monkeypatch.setattr("extrapcap.data.alpaca_market.AlpacaMarketData", FakeMarketData)

    # Mock greenlist fetching
    class FakeUrllib:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return (
                b"ticker,sector,cap_tier,avg_volume,exchange\n"
                b"BG,Consumer,Mega-Cap,1000000,NMS\n"
                b"XYZ,Technology,Large-Cap,1000000,NMS\n"
                b"AXIA,Technology,Large-Cap,1000000,NMS\n"
            )

    monkeypatch.setattr("urllib.request.urlopen", lambda url, timeout=30: FakeUrllib())

    res = dr_mod.data_refresh.local()
    assert res["status"] == "success"
    assert len(stored_bars) == 1
    assert set(stored_bars[0]["symbol"]) == {"SPY", "BG", "XYZ"}
    assert res["bars_count"] == 3
    assert res["bar_partitions_written"] == 2
    assert {row["ticker"] for row in screened_greenlist} == {"BG", "XYZ"}
    assert appended_events == [
        {
            "category": "data",
            "kind": "asset_unavailable",
            "ticker": "AXIA",
            "status": "deferred",
            "reason": "not_available_in_completed_alpaca_bars",
        }
    ]
    assert res["unavailable_symbols"] == ["AXIA"]


def test_data_refresh_succeeds_even_if_bar_storage_fails(monkeypatch):
    from datetime import datetime

    import modal_app.functions.data_refresh as dr_mod
    from modal_app.cf_client import CloudflareAPIClient

    class MockDatetime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 8, 6, 4, 0, 0, tzinfo=UTC)

    monkeypatch.setattr(dr_mod, "datetime", MockDatetime)

    appended_events = []

    def mock_failing_write_bar_partitions(frame, volume, **kwargs):
        raise RuntimeError("Modal function has no attached volumes")

    def mock_run_streak_screening(cf, greenlist, bars_df, run_id=None):
        return {
            "status": "success",
            "universe_count": len(greenlist),
            "candidates_count": 1,
            "candidate_symbols": ["BG"],
            "run_id": run_id,
        }

    monkeypatch.setattr(CloudflareAPIClient, "register_run", lambda self, wf: "test-run-refresh")
    monkeypatch.setattr(CloudflareAPIClient, "complete_run", lambda self, run_id, summary, start_time: None)
    monkeypatch.setattr(dr_mod, "write_bar_partitions", mock_failing_write_bar_partitions)
    monkeypatch.setattr(
        CloudflareAPIClient,
        "append_events",
        lambda self, events, run_id=None: appended_events.extend(events),
    )
    monkeypatch.setattr("modal_app.functions.streak_screen.run_streak_screening", mock_run_streak_screening)
    monkeypatch.setattr("extrapcap.secrets.require_paper_credentials", lambda: ("key", "sec"))

    class FakeMarketData:
        def __init__(self, api_key, secret_key):
            pass
        def stock_bars(self, symbols, start, end, timeframe, allow_partial=False):
            return {
                "bars": {
                    "SPY": [{"t": "2026-08-05T04:00:00Z", "o": 1, "h": 2, "l": 1, "c": 2, "v": 100, "vw": 1.5}],
                    "BG": [{"t": "2026-08-05T04:00:00Z", "o": 10, "h": 20, "l": 10, "c": 15, "v": 200, "vw": 15.0}],
                },
                "errors": {},
                "unresolved_symbols": [],
            }

    monkeypatch.setattr("extrapcap.data.alpaca_market.AlpacaMarketData", FakeMarketData)

    class FakeUrllib:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def read(self):
            return b"ticker,sector\nBG,Agriculture\n"

    monkeypatch.setattr("urllib.request.urlopen", lambda url, timeout=30: FakeUrllib())

    res = dr_mod.data_refresh.local()
    assert res["status"] == "success"
    assert res["candidate_stocks"] == ["BG"]
    warning_events = [e for e in appended_events if e.get("kind") == "bar_volume_warning"]
    assert len(warning_events) == 1
    assert "Modal function has no attached volumes" in warning_events[0]["reason"]



def test_bayesian_reversion_model_discards_short_history():
    import pandas as pd
    import pytest

    from extrapcap.models.bayesian_reversion import BayesianReversionModel

    # Create dummy bars for SPY, AAPL (long history >= 40 bars), and NEWCO (short history < 30 bars)
    dates = pd.date_range("2026-01-01", periods=40, freq="D", tz="UTC")
    spy_bars = [{"symbol": "SPY", "date": d, "close": 500.0 + i} for i, d in enumerate(dates)]
    aapl_bars = [{"symbol": "AAPL", "date": d, "close": 150.0 + i} for i, d in enumerate(dates)]
    newco_bars = [{"symbol": "NEWCO", "date": d, "close": 50.0 + i} for i, d in enumerate(dates[:15])]

    bars_df = pd.DataFrame(spy_bars + aapl_bars + newco_bars)
    benchmark = bars_df.loc[bars_df["symbol"] == "SPY"].set_index("date")["close"]

    model = BayesianReversionModel.fit_from_bars(bars_df, benchmark)
    assert ("AAPL", "negative") in model.ticker_priors or ("AAPL", "positive") in model.ticker_priors
    assert ("NEWCO", "negative") not in model.ticker_priors

    # NEWCO should raise KeyError because it lacks sufficient ticker-specific history and is discarded
    with pytest.raises((KeyError, ValueError)):
        model.predict_evidence(symbol="NEWCO", streak_length=3, streak_direction="negative", day_of_week=1)


def test_position_management_skips_when_market_clock_closed(monkeypatch):
    from datetime import UTC, datetime
    import modal_app.functions.position_management as pm_mod

    class MockWeekdayDatetime:
        @classmethod
        def now(cls, tz=None):
            # 2026-09-07 is a Monday (weekday 0, Labor Day)
            return datetime(2026, 9, 7, 14, 0, 0, tzinfo=UTC)

    monkeypatch.setattr(pm_mod, "datetime", MockWeekdayDatetime)
    monkeypatch.setattr(
        "extrapcap.execution.alpaca.AlpacaPaperClient.from_env",
        lambda: type("Paper", (), {"clock": lambda self: {"is_open": False, "next_open": "2026-09-08T09:30:00-04:00"}})()
    )

    res = pm_mod.position_management.local()
    assert res["status"] == "skipped"
    assert res["reason"] == "broker_market_clock_closed"
    assert res["next_open"] == "2026-09-08T09:30:00-04:00"


def test_candidate_review_skips_when_market_clock_closed(monkeypatch):
    from datetime import UTC, datetime
    import modal_app.functions.candidate_review as cr_mod

    class MockWeekdayDatetime:
        @classmethod
        def now(cls, tz=None):
            # 2026-09-07 is a Monday (weekday 0, Labor Day)
            return datetime(2026, 9, 7, 14, 0, 0, tzinfo=UTC)

    monkeypatch.setattr(cr_mod, "datetime", MockWeekdayDatetime)
    monkeypatch.setattr(
        "extrapcap.execution.alpaca.AlpacaPaperClient.from_env",
        lambda: type("Paper", (), {"clock": lambda self: {"is_open": False, "next_open": "2026-09-08T09:30:00-04:00"}})()
    )

    res = cr_mod.candidate_review.local()
    assert res["status"] == "skipped"
    assert res["reason"] == "broker_market_clock_closed"
    assert res["next_open"] == "2026-09-08T09:30:00-04:00"


def test_end_of_day_skips_when_holiday_calendar_empty(monkeypatch):
    from datetime import UTC, datetime
    import modal_app.functions.end_of_day as eod_mod

    class MockWeekdayDatetime:
        @classmethod
        def now(cls, tz=None):
            # 2026-09-07 is a Monday (weekday 0, Labor Day)
            return datetime(2026, 9, 7, 20, 30, 0, tzinfo=UTC)

    monkeypatch.setattr(eod_mod, "datetime", MockWeekdayDatetime)
    monkeypatch.setattr(
        "extrapcap.execution.alpaca.AlpacaPaperClient.from_env",
        lambda: type("Paper", (), {"calendar": lambda self, start, end: []})()
    )

    res = eod_mod.end_of_day.local()
    assert res["status"] == "skipped"
    assert res["reason"] == "market_holiday_no_session"

