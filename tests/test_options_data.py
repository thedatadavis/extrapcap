from datetime import datetime, timezone
from io import BytesIO
from urllib.error import HTTPError

from extrapcap.fills import FillAssumptions, credit_fill, early_assignment_exposure, vertical_expiration_pnl
import pytest
from extrapcap.options import VerticalSpread
from extrapcap.options_data import AlpacaOptionsData, AlpacaOptionsRequestError, DataTier, OptionContract, OptionQuote, SelectedDebitVertical, SelectedVertical, contracts_from_payload, normalize_chain, select_bearish_put_debit_vertical, select_put_vertical, selected_vertical_quote_quality


def test_options_adapter_uses_resolved_symbol_and_restores_strategy_symbol(monkeypatch):
    calls = []
    def fake_get(base, path, params):
        calls.append((path, params))
        if path == "/v2/options/contracts":
            return {"option_contracts": [{"symbol": "BF.B260821C00280000", "underlying_symbol": "BF.B", "expiration_date": "2026-08-21", "strike_price": "280", "type": "call"}]}
        return {"snapshots": {}}
    provider = AlpacaOptionsData("key", "secret")
    monkeypatch.setattr(provider, "_get", fake_get)
    contracts = provider.contracts_all("BF.B", "2026-08-12", "2026-08-31", "call", strategy_underlying="BF-B")
    provider.chain_all("BF.B", expiration_gte="2026-08-12", expiration_lte="2026-08-31")
    assert calls[0][1]["underlying_symbols"] == "BF.B"
    assert calls[1][0] == "/v1beta1/options/snapshots/BF.B"
    assert contracts["option_contracts"][0]["underlying_symbol"] == "BF-B"


def test_options_adapter_exposes_provider_error_without_credentials(monkeypatch):
    body = BytesIO(b'{"code":42210000,"message":"invalid underlying symbols: BAD"}')
    def fake_urlopen(request, timeout):
        raise HTTPError(request.full_url, 422, "Unprocessable Entity", {}, body)
    monkeypatch.setattr("extrapcap.options_data.urlopen", fake_urlopen)
    provider = AlpacaOptionsData("private-key", "private-secret")
    with pytest.raises(AlpacaOptionsRequestError) as raised:
        provider.contracts("BAD", "2026-08-12")
    message = str(raised.value)
    assert "HTTP 422" in message
    assert "invalid underlying symbols: BAD" in message
    assert "private-key" not in message
    assert "private-secret" not in message


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


def test_bearish_debit_selector_buys_higher_put_and_sells_lower_put():
    selected = select_bearish_put_debit_vertical(
        "ABC",
        [
            OptionContract("ABC-long", "ABC", "2026-08-21", 105, "put"),
            OptionContract("ABC-short", "ABC", "2026-08-21", 95, "put"),
        ],
        [
            OptionQuote("ABC-long", "now", 2.0, 2.5, 2.2, delta=-0.40),
            OptionQuote("ABC-short", "now", 0.9, 1.0, 0.95, delta=-0.20),
        ],
        100,
    )
    assert selected.debit == pytest.approx(1.6)
    assert [leg["position_intent"] for leg in selected.order_legs()] == ["buy_to_open", "sell_to_open"]


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


def test_debit_vertical_quote_quality_rejects_a_zero_bid_leg():
    long = OptionContract("ABC-long", "ABC", "2026-08-21", 50, "call")
    short = OptionContract("ABC-short", "ABC", "2026-08-21", 55, "call")
    reason, _ = selected_vertical_quote_quality(
        SelectedDebitVertical("ABC", long, short, 0.57, 0.4),
        [
            OptionQuote("ABC-long", "2026-08-12T16:07:19Z", 0.38, 0.57, 0.5),
            OptionQuote("ABC-short", "2026-08-12T16:07:19Z", 0.0, 0.03, 0.01),
        ],
        datetime(2026, 8, 12, 16, 8, tzinfo=timezone.utc),
    )
    assert reason == "option_quote_invalid"


def test_vertical_quote_quality_allows_zero_bid_on_long_wing_if_ask_valid():
    short = OptionContract("ABC-short", "ABC", "2026-08-21", 95, "put")
    long = OptionContract("ABC-long", "ABC", "2026-08-21", 90, "put")
    selected = SelectedVertical("ABC", short, long, 0.45, -0.20)
    reason, details = selected_vertical_quote_quality(
        selected,
        [
            OptionQuote("ABC-short", "2026-08-12T16:07:19Z", 0.50, 0.60, 0.55),
            OptionQuote("ABC-long", "2026-08-12T16:07:19Z", 0.0, 0.05, 0.02),
        ],
        datetime(2026, 8, 12, 16, 8, tzinfo=timezone.utc),
    )
    assert reason is None


def test_vertical_quote_quality_exempts_narrow_absolute_spreads():
    short = OptionContract("ABC-short", "ABC", "2026-08-21", 95, "put")
    long = OptionContract("ABC-long", "ABC", "2026-08-21", 90, "put")
    selected = SelectedVertical("ABC", short, long, 0.35, -0.20)
    # Short has 0.40 x 0.50 (spread 0.10, pct 22.2%)
    # Long has 0.05 x 0.15 (spread 0.10, pct 100% > 40%, but spread 0.10 <= 0.15)
    reason, details = selected_vertical_quote_quality(
        selected,
        [
            OptionQuote("ABC-short", "2026-08-12T16:07:19Z", 0.40, 0.50, 0.45),
            OptionQuote("ABC-long", "2026-08-12T16:07:19Z", 0.05, 0.15, 0.10),
        ],
        datetime(2026, 8, 12, 16, 8, tzinfo=timezone.utc),
    )
    assert reason is None

