from extrapcap.secrets import require_nebius_key


def test_secret_loader_prefers_environment(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "test-key")
    assert require_nebius_key() == "test-key"
