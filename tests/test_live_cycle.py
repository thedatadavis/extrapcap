from extrapcap.config import AppConfig


def test_live_cycle_requires_explicit_model_argument(monkeypatch):
    monkeypatch.delenv("SNIPER_MODEL_PATH", raising=False)
    assert AppConfig.from_env().paper_only is True
