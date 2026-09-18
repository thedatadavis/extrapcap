import httpx
import pytest
from modal_app.cf_client import CloudflareAPIClient


def test_cf_client_get_basket_parses_json(monkeypatch):
    class FakeResponse:
        status_code = 200
        def json(self):
            return [{"symbol": "ABC", "robust_z": -2.4, "streak_length": 3}]

    class FakeClient:
        def __init__(self, **kwargs):
            pass
        def get(self, url):
            assert url.startswith("/api/basket?_ts=")
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    cf = CloudflareAPIClient()
    rows = cf.get_basket()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "ABC"
    assert rows[0]["robust_z"] == -2.4


def test_cf_client_register_and_complete_run(monkeypatch):
    posted = []
    patched = []

    class FakeResponse:
        status_code = 200
        def json(self):
            return {"success": True}

    class FakeClient:
        def __init__(self, **kwargs):
            pass
        def post(self, url, json=None):
            posted.append((url, json))
            return FakeResponse()
        def patch(self, url, json=None):
            patched.append((url, json))
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    cf = CloudflareAPIClient()
    run_id = cf.register_run("candidate_review")
    assert run_id.startswith("modal-")
    assert posted[0][0] == "/api/runs"
    assert posted[0][1]["workflow"] == "candidate_review"

    cf.complete_run(run_id, summary={"evaluated": 5}, start_time=100.0)
    assert patched[0][0] == "/api/runs"
    assert patched[0][1]["status"] == "completed"


def test_cf_client_universe_and_risk_events(monkeypatch):
    posted = []

    class FakeResponse:
        status_code = 200
        def json(self):
            return [{"symbol": "AAPL", "sector": "Technology"}]

    class FakeClient:
        def __init__(self, **kwargs):
            pass
        def get(self, url):
            return FakeResponse()
        def post(self, url, json=None):
            posted.append((url, json))
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    cf = CloudflareAPIClient()
    univ = cf.get_universe(symbol="AAPL")
    assert len(univ) == 1
    assert univ[0]["symbol"] == "AAPL"

    cf.store_universe([{"symbol": "AAPL", "sector": "Technology"}])
    assert posted[0][0] == "/api/universe"

    cf.store_risk_events([{"symbol": "AAPL", "event_type": "earnings", "event_date": "2026-08-10"}])
    assert posted[1][0] == "/api/risk_events"


def test_cf_client_bypasses_cached_order_and_position_reads(monkeypatch):
    requested = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return []

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def get(self, url):
            requested.append(url)
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    cf = CloudflareAPIClient()
    cf.get_orders()
    cf.get_positions()
    cf.get_active_positions()

    assert requested[0].startswith("/api/orders?_ts=")
    assert requested[1].startswith("/api/positions?_ts=")
    assert requested[2].startswith("/api/positions?active=true&_ts=")


def test_cf_client_batches_bar_writes(monkeypatch):
    posted = []

    class FakeResponse:
        status_code = 200

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def post(self, url, json=None):
            posted.append((url, json))
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    CloudflareAPIClient().upsert_bars([{"symbol": "ABC", "date": str(i)} for i in range(5)], batch_size=2)
    assert [len(payload) for _, payload in posted] == [2, 2, 1]


def test_cf_client_raises_when_event_persistence_fails(monkeypatch):
    class FakeResponse:
        status_code = 500
        text = "D1 unavailable"

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def post(self, url, json=None):
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    with pytest.raises(RuntimeError, match="event append failed"):
        CloudflareAPIClient().append_events([{"kind": "test"}])


def test_cf_client_log_and_resolve_errors(monkeypatch):
    posted = []
    patched = []
    got = []

    class FakeResponse:
        status_code = 200
        def json(self):
            return {"success": True, "id": 101}

    class FakeListResponse:
        status_code = 200
        def json(self):
            return [{"id": 101, "workflow": "daily_report", "error_message": "Test fail", "is_resolved": 0}]

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def post(self, url, json=None):
            posted.append((url, json))
            return FakeResponse()

        def get(self, url):
            got.append(url)
            return FakeListResponse()

        def patch(self, url, json=None):
            patched.append((url, json))
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    cf = CloudflareAPIClient()

    # Test log_error with exception
    try:
        raise ValueError("synthetic boom")
    except Exception as e:
        res = cf.log_error(workflow="daily_report", error=e, run_id="modal-test-123", context={"key": "val"})
        assert res["success"] is True

    assert len(posted) == 1
    assert posted[0][0] == "/api/errors"
    assert posted[0][1]["workflow"] == "daily_report"
    assert posted[0][1]["error_type"] == "ValueError"
    assert "synthetic boom" in posted[0][1]["error_message"]
    assert "Traceback" in posted[0][1]["stack_trace"]
    assert posted[0][1]["context"] == {"key": "val"}

    # Test get_errors
    errors = cf.get_errors(unresolved=True, workflow="daily_report")
    assert len(errors) == 1
    assert errors[0]["id"] == 101
    assert any("/api/errors?" in url and "unresolved=true" in url for url in got)

    # Test resolve_error
    ok = cf.resolve_error(error_id=101, resolution_notes="Auto-repaired by self-healing agent", resolved_by="antigravity-healer")
    assert ok is True
    assert len(patched) == 1
    assert patched[0][0] == "/api/errors"
    assert patched[0][1]["id"] == 101
    assert patched[0][1]["is_resolved"] == 1
    assert patched[0][1]["resolution_notes"] == "Auto-repaired by self-healing agent"
