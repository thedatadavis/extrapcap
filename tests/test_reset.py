import pytest

from extrapcap.execution.alpaca import AlpacaPaperClient
from extrapcap.execution.reset_cli import main


def test_paper_reset_is_dry_run_when_flagged():
    client = AlpacaPaperClient(api_key=None, secret_key=None, dry_run=True)
    result = client.reset_paper_account()
    assert result["status"] == "dry_run"
    assert result["positions"] == "credentials_not_configured"


def test_reset_cli_requires_exact_confirmation(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER", "true")
    monkeypatch.setattr("sys.argv", ["reset_cli", "--confirm", "NO"])
    with pytest.raises(SystemExit, match="exact confirmation token"):
        main()
