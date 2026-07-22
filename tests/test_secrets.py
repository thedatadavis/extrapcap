import pytest

from extrapcap.secrets import require_nebius_key, require_paper_submit_enabled


def test_secret_loader_prefers_environment(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "test-key")
    assert require_nebius_key() == "test-key"


def test_paper_submit_requires_separate_enable_switch(monkeypatch):
    monkeypatch.delenv("EXTRAPCAP_PAPER_SUBMIT_ENABLED", raising=False)
    with pytest.raises(RuntimeError, match="paper-submit is disabled"):
        require_paper_submit_enabled()
    monkeypatch.setenv("EXTRAPCAP_PAPER_SUBMIT_ENABLED", "true")
    assert require_paper_submit_enabled() is None
