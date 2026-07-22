from datetime import datetime, timezone

from extrapcap.fills import FillAssumptions, credit_fill, early_assignment_exposure, vertical_expiration_pnl
import pytest
from extrapcap.options import VerticalSpread
from extrapcap.options_data import AlpacaOptionsData, DataTier, OptionContract, OptionQuote, contracts_from_payload, normalize_chain, select_put_vertical, selected_vertical_quote_quality


def test_chain_normalization_preserves_quote_and_greeks():
    quotes = normalize_chain({"snapshots": {"ABC240119P00100000": {"latestQuote": {"t": "now", "bp": 1.0, "ap": 1.2}, "latestTrade": {"p": 1.1}, "greeks": {"delta": -0.2}, "impliedVolatility": 0.4}}})
    assert quotes[0].midpoint == 1.1
    assert quotes[0].delta == -0.2


def test_historical_trades_uses_provider_default_feed_contract(monkeypatch):
    captured = {}

    def fake_get(base, path, params):
        captured.update(params)
        return {"trades": []}

    provider = AlpacaOptionsData("key", "secret")
    monkeypatch.setattr(provider, "_get", fake_get)
    payload, tier = provider.historical_trades(["ABC240119P00100000"], "2026-07-01", "2026-07-02", "opra")
    assert "feed" not in captured
    assert payload["_requested_feed"] == "opra"
    assert tier == DataTier.PROVIDER_DEFAULT
    assert DataTier.INDICATIVE.value == "indicative"


def test_credit_fill_and_expiry_assignment_contracts():
    spread = VerticalSpread("ABC", 100, 95, 1.0)
    assert credit_fill(1.5, 0.4, 1, FillAssumptions(slippage_per_leg=0)) == pytest.approx(110)
    assert vertical_expiration_pnl(spread, 102) == 100
    assert vertical_expiration_pnl(spread, 94) == -400
    assert early_assignment_exposure(spread, 99, 5)


def test_put_selector_uses_delta_and_resolved_contract_legs():
    contracts = [
        OptionContract("ABC-short", "ABC", "2026-08-21", 95, "put"),
        OptionContract("ABC-long", "ABC", "2026-08-21", 90, "put"),
    ]
    quotes = [
        OptionQuote("ABC-short", "now", 2.0, 2.2, 2.1, delta=-0.18),
        OptionQuote("ABC-long", "now", 0.8, 1.0, 0.9, delta=-0.08),
    ]
    selected = select_put_vertical("ABC", contracts, quotes, 100)
    assert selected.credit == 1.0
    assert selected.order_legs()[0]["position_intent"] == "sell_to_open"
    assert contracts_from_payload({"option_contracts": [{"symbol": "ABC", "underlying_symbol": "ABC", "expiration_date": "2026-08-21", "strike_price": 95, "type": "put"}]})[0].strike == 95


def test_selected_vertical_quote_quality_rejects_wide_or_stale_quotes():
    contracts = [
        OptionContract("ABC-short", "ABC", "2026-08-21", 95, "put"),
        OptionContract("ABC-long", "ABC", "2026-08-21", 90, "put"),
    ]
    selected = select_put_vertical(
        "ABC",
        contracts,
        [
            OptionQuote("ABC-short", "2026-07-22T14:59:00Z", 2.0, 2.2, 2.1, delta=-0.18),
            OptionQuote("ABC-long", "2026-07-22T14:59:00Z", 0.8, 1.0, 0.9, delta=-0.08),
        ],
        100,
    )
    reason, _ = selected_vertical_quote_quality(
        selected,
        [
            OptionQuote("ABC-short", "2026-07-22T14:59:00Z", 2.0, 2.2, 2.1, delta=-0.18),
            OptionQuote("ABC-long", "2026-07-22T14:59:00Z", 0.1, 1.0, 0.5, delta=-0.08),
        ],
        datetime(2026, 7, 22, 15, tzinfo=timezone.utc),
    )
    assert reason == "option_quote_spread_too_wide"
    reason, _ = selected_vertical_quote_quality(
        selected,
        [
            OptionQuote("ABC-short", "2026-07-22T13:00:00Z", 2.0, 2.2, 2.1, delta=-0.18),
            OptionQuote("ABC-long", "2026-07-22T13:00:00Z", 0.8, 1.0, 0.9, delta=-0.08),
        ],
        datetime(2026, 7, 22, 15, tzinfo=timezone.utc),
    )
    assert reason == "option_quote_stale"
