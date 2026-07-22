from extrapcap.diagnostics import run_diagnostics


def test_diagnostics_is_redacted_and_safe_without_keys(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    result = run_diagnostics()
    assert "api_key" not in str(result).lower()
    assert result["paper_only"] is True
