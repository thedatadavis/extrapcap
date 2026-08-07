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
