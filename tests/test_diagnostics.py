from urllib.error import HTTPError

from extrapcap.diagnostics import diagnostic_ready, run_diagnostics


def test_diagnostics_is_redacted_and_safe_without_keys(monkeypatch):
    monkeypatch.setenv("EXTRAPCAP_KEYCHAIN_ENABLED", "false")
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    result = run_diagnostics()
    assert "api_key" not in str(result).lower()
    assert result["paper_only"] is True
    assert not diagnostic_ready(result)


def test_diagnostics_reports_safe_alpaca_http_status(monkeypatch):
    class FakeClient:
        api_key = "configured"
        secret_key = "configured"
        base_url = "https://paper-api.alpaca.markets/v2"

        def account(self):
            raise HTTPError(self.base_url, 401, "unauthorized", {}, None)

    class FakeReviewer:
        api_key = "configured"

        def list_models(self):
            return {"data": []}

    monkeypatch.setattr("extrapcap.diagnostics.AlpacaPaperClient.from_env", lambda: FakeClient())
    monkeypatch.setattr("extrapcap.diagnostics.NebiusReviewer", FakeReviewer)
    result = run_diagnostics()
    assert result["alpaca"] == {
        "configured": True,
        "endpoint_is_paper_v2": True,
        "reachable": False,
        "error_type": "HTTPError",
        "http_status": 401,
    }


def test_diagnostics_requires_paper_options_readiness(monkeypatch):
    class FakeClient:
        api_key = "configured"
        secret_key = "configured"
        base_url = "https://paper-api.alpaca.markets/v2"

        def account(self):
            return {
                "status": "ACTIVE",
                "account_number": "paper",
                "options_trading_level": 3,
                "options_buying_power": "10000",
            }

    class FakeReviewer:
        api_key = "configured"

        def list_models(self):
            return {"data": []}

    monkeypatch.setenv("EXTRAPCAP_PAPER_SUBMIT_ENABLED", "true")
    monkeypatch.setattr("extrapcap.diagnostics.AlpacaPaperClient.from_env", lambda: FakeClient())
    monkeypatch.setattr("extrapcap.diagnostics.NebiusReviewer", FakeReviewer)
    result = run_diagnostics()
    assert result["alpaca"]["account_trading_ready"] is True
    assert result["ready_for_paper_submit"] is True
