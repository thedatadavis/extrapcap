from extrapcap.orchestration.basket_cycle import basket_rows
from modal_app.functions.candidate_review import _event_record


def test_d1_basket_rows_hydrate_feature_payload():
    rows = basket_rows([{"symbol": "ABC", "robust_z": -2.5, "features": '{"date":"2026-08-05T04:00:00+00:00","relative_return":-0.03,"streak_length":3,"streak_direction":"negative","reversion_probability":0.72}'}])
    assert rows[0]["formation_date"] == "2026-08-05T04:00:00+00:00"
    assert rows[0]["streak_length"] == 3
    assert rows[0]["reversion_probability"] == 0.72


def test_event_record_flattens_broker_result():
    event = _event_record({"ticker": "ABC", "result": {"order_id": "alpaca-1", "status": "new"}})
    assert event["status"] == "new"
    assert event["category"] == "orders"


def test_modal_app_imports_cleanly():
    import modal_app.app  # noqa: F401
    from modal_app.base import app
    assert app.name == "extrapcap"


def test_candidate_review_basket_fallback(monkeypatch):
    from datetime import datetime, timezone
    from modal_app.cf_client import CloudflareAPIClient
    from modal_app.functions.candidate_review import candidate_review

    calls = []

    def mock_get_basket(self, as_of=None, run_id=None):
        calls.append(as_of)
        if as_of is not None:
            return []
        return [{"symbol": "ABC", "robust_z": -2.5, "streak_length": 3}]

    monkeypatch.setattr(CloudflareAPIClient, "get_basket", mock_get_basket)
    monkeypatch.setattr(CloudflareAPIClient, "register_run", lambda self, wf: "test-run-1")
    monkeypatch.setattr(CloudflareAPIClient, "complete_run", lambda self, run_id, summary, start_time: None)
    monkeypatch.setattr(CloudflareAPIClient, "append_events", lambda self, events, run_id=None: None)

    def mock_run_basket(basket, trading_day, dte_min, dte_max, preferred_dte):
        return [{"ticker": "ABC", "status": "new"}]

    import extrapcap.orchestration.basket_cycle
    monkeypatch.setattr(extrapcap.orchestration.basket_cycle, "run_basket", mock_run_basket)

    res = candidate_review.local()
    assert res["status"] == "success"
    assert res["evaluated"] == 1
    today_iso = datetime.now(timezone.utc).date().isoformat()
    assert calls == [today_iso, None]


