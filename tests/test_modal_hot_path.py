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
    from datetime import datetime, date, timezone
    from modal_app.cf_client import CloudflareAPIClient
    import modal_app.functions.candidate_review as cr_mod

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
            return datetime(2026, 8, 5, 14, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(cr_mod, "datetime", MockDatetime)
    monkeypatch.setattr(CloudflareAPIClient, "get_basket", mock_get_basket)
    monkeypatch.setattr(CloudflareAPIClient, "register_run", lambda self, wf: "test-run-1")
    monkeypatch.setattr(CloudflareAPIClient, "complete_run", lambda self, run_id, summary, start_time: None)
    monkeypatch.setattr(CloudflareAPIClient, "append_events", lambda self, events, run_id=None: None)
    monkeypatch.setattr(CloudflareAPIClient, "record_order", lambda self, event, run_id=None: None)
    monkeypatch.setattr("extrapcap.execution.alpaca.AlpacaPaperClient.from_env", lambda: type("Paper", (), {"positions": lambda self: [], "open_orders": lambda self: []})())
    monkeypatch.setattr("extrapcap.data.alpaca_market.AlpacaMarketData.resolve_assets", lambda self, symbols, strict=False: {"ABC": {"id": "asset-abc", "symbol": "ABC"}})

    def mock_run_basket(basket, trading_day, dte_min, dte_max, preferred_dte, max_candidates, max_submissions):
        assert max_candidates == 25
        assert max_submissions == 1
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
    from datetime import datetime, timezone
    from modal_app.cf_client import CloudflareAPIClient
    import modal_app.functions.candidate_review as cr_mod

    class MockSatDatetime:
        @classmethod
        def now(cls, tz=None):
            # 2026-08-08 is a Saturday (weekday 5)
            return datetime(2026, 8, 8, 14, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(cr_mod, "datetime", MockSatDatetime)
    monkeypatch.setattr(CloudflareAPIClient, "register_run", lambda self, wf: "test-run-1")
    monkeypatch.setattr(CloudflareAPIClient, "complete_run", lambda self, run_id, summary, start_time: None)

    res = cr_mod.candidate_review.local()
    assert res["status"] == "skipped"
    assert res["reason"] == "weekend_market_closed"


def test_data_refresh_filters_bar_inserts_to_candidate_symbols(monkeypatch):
    import pandas as pd
    from modal_app.cf_client import CloudflareAPIClient
    import modal_app.functions.data_refresh as dr_mod

    upserted_bars = []

    def mock_upsert_bars(self, bars, batch_size=500):
        upserted_bars.extend(bars)

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
    monkeypatch.setattr(CloudflareAPIClient, "upsert_bars", mock_upsert_bars)
    monkeypatch.setattr("modal_app.functions.streak_screen.run_streak_screening", mock_run_streak_screening)
    monkeypatch.setattr("extrapcap.secrets.require_paper_credentials", lambda: ("key", "sec"))

    class FakeMarketData:
        def __init__(self, api_key, secret_key):
            pass
        def stock_bars(self, symbols, start, end, timeframe):
            return {
                "bars": {
                    "SPY": [{"t": "2026-08-05T04:00:00Z", "o": 1, "h": 2, "l": 1, "c": 2, "v": 100, "vw": 1.5}],
                    "BG": [{"t": "2026-08-05T04:00:00Z", "o": 10, "h": 20, "l": 10, "c": 15, "v": 200, "vw": 15.0}],
                    "XYZ": [{"t": "2026-08-05T04:00:00Z", "o": 5, "h": 5, "l": 5, "c": 5, "v": 50, "vw": 5.0}],
                }
            }

    monkeypatch.setattr("extrapcap.data.alpaca_market.AlpacaMarketData", FakeMarketData)

    # Mock greenlist fetching
    class FakeUrllib:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return b"ticker,sector,market_cap_tier\nBG,Consumer,mid\nXYZ,Technology,large\n"

    monkeypatch.setattr("urllib.request.urlopen", lambda url, timeout=30: FakeUrllib())

    res = dr_mod.data_refresh.local()
    assert res["status"] == "success"
    symbols_upserted = {b["symbol"] for b in upserted_bars}
    # XYZ (non-candidate) must NOT be upserted to D1! Only BG and SPY are upserted.
    assert symbols_upserted == {"SPY", "BG"}


def test_bayesian_reversion_model_discards_short_history():
    import pytest
    import pandas as pd
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


