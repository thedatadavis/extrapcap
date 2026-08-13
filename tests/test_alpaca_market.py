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


def test_stock_bars_can_skip_unresolved_universe_constituents(monkeypatch):
    provider = AlpacaMarketData("key", "secret")

    def fake_get(path, params, base_url=None):
        if path == "/v2/assets":
            return [{"id": "asset-spy", "symbol": "SPY"}]
        assert path == "/v2/stocks/bars"
        assert params["symbols"] == "SPY"
        return {
            "bars": {
                "SPY": [
                    {"t": "2026-08-12T04:00:00Z", "o": 1, "h": 2, "l": 1, "c": 2, "v": 10}
                ]
            },
            "next_page_token": None,
        }

    monkeypatch.setattr(provider, "_get", fake_get)
    payload = provider.stock_bars(
        ["SPY", "EA"],
        "2026-01-01T00:00:00Z",
        "2026-08-13T00:00:00Z",
        allow_partial=True,
    )

    assert list(payload["bars"]) == ["SPY"]
    assert payload["unresolved_symbols"] == ["EA"]
    assert payload["errors"] == {}
