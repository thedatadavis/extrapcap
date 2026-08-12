import pytest

from extrapcap.data.alpaca_market import AlpacaMarketData


def test_asset_master_resolves_source_punctuation_without_aliases(monkeypatch):
    provider = AlpacaMarketData("key", "secret")
    monkeypatch.setattr(provider, "_get", lambda *args, **kwargs: [{"id": "asset-bf-b", "symbol": "BF.B"}, {"id": "asset-aapl", "symbol": "AAPL"}])
    identities = provider.resolve_assets(["BF-B", "AAPL"])
    assert identities["BF-B"]["symbol"] == "BF.B"
    assert identities["BF-B"]["id"] == "asset-bf-b"
    assert identities["AAPL"]["id"] == "asset-aapl"


def test_asset_master_fails_closed_on_ambiguous_identity(monkeypatch):
    provider = AlpacaMarketData("key", "secret")
    monkeypatch.setattr(provider, "_get", lambda *args, **kwargs: [{"id": "one", "symbol": "AB.C"}, {"id": "two", "symbol": "A.BC"}])
    with pytest.raises(RuntimeError, match="could not resolve symbols: AB-C"):
        provider.resolve_assets(["AB-C"])
