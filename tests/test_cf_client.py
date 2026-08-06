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
            assert url == "/api/basket"
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    cf = CloudflareAPIClient()
    rows = cf.get_basket()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "ABC"
    assert rows[0]["robust_z"] == -2.4


def test_cf_client_get_basket_returns_empty_list_on_error(monkeypatch):
    class FakeClient:
        def __init__(self, **kwargs):
            pass
        def get(self, url):
            raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx, "Client", FakeClient)
    cf = CloudflareAPIClient()
    assert cf.get_basket() == []


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
