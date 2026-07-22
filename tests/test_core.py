import pandas as pd
import pytest
from extrapcap.config import AppConfig
from extrapcap.options import DebitSpread, VerticalSpread
from extrapcap.portfolio import SleeveLedger
from extrapcap.signals import robust_zscore
from extrapcap.data.alpaca_market import AlpacaMarketData
from extrapcap.execution.alpaca import PAPER_API_ROOT, AlpacaPaperClient
from extrapcap.llm.nebius import NebiusReviewer
from extrapcap.execution.orders import OrderEnvelope
from extrapcap.execution.orders import OrderRegistry
from extrapcap.models.sniper import calibration_report, time_split
from extrapcap.reporting.metrics import summarize_returns
from extrapcap.fills import debit_expiration_pnl
from extrapcap.risk import PortfolioRiskState, approve_asymmetric, asymmetric_exit_reason


def test_robust_zscore_is_neutral_for_constant_window():
    result = robust_zscore(pd.Series([1, 1, 1, 1, 1]), window=3)
    assert result.iloc[-1] == 0


def test_vertical_is_defined_risk():
    spread = VerticalSpread("ABC", 100, 95, 1.0)
    assert spread.max_loss == 400
    assert spread.max_profit == 100


def test_premium_funds_only_fraction():
    ledger = SleeveLedger()
    assert ledger.realize_premium(100, AppConfig().strategy.premium_funding_pct) == 15
    assert ledger.asymmetric_budget == 15


def test_batched_premium_funding_requires_explicit_transfer():
    ledger = SleeveLedger()
    assert ledger.realize_premium(100, 0.15, mode="batched", batch_id="2026-W30") == 0
    assert ledger.asymmetric_budget == 0
    assert ledger.flush_funding_pool() == 15
    assert ledger.asymmetric_budget == 15


def test_invalid_credit_rejected():
    with pytest.raises(ValueError):
        VerticalSpread("ABC", 100, 95, 5.0)


def test_debit_expiration_pnl_respects_direction_and_width():
    spread = DebitSpread("ABC", 100, 90, 1.0, direction="bearish")
    assert debit_expiration_pnl(spread, 85) == pytest.approx(900)
    assert debit_expiration_pnl(spread, 105) == pytest.approx(-100)


def test_asymmetric_admission_and_time_stop_are_bounded():
    spread = DebitSpread("ABC", 100, 90, 1.0, direction="bearish")
    state = PortfolioRiskState(nav=100_000)
    assert approve_asymmetric(spread, state, AppConfig().risk).allowed is True
    assert asymmetric_exit_reason(spread, 10, 1.0, AppConfig().risk) == "asymmetric_time_stop"
    assert asymmetric_exit_reason(spread, 2, 0.4, AppConfig().risk) == "asymmetric_decay_stop"


def test_alpaca_client_is_fail_closed(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER", "false")
    with pytest.raises(RuntimeError, match="paper-only"):
        AlpacaPaperClient.from_env()


def test_alpaca_client_normalizes_exact_paper_v2_root(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER", "true")
    monkeypatch.setenv("EXTRAPCAP_EXECUTION_MODE", "dry-run")
    monkeypatch.setenv("EXTRAPCAP_KEYCHAIN_ENABLED", "false")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets/v2")
    assert AlpacaPaperClient.from_env().base_url == PAPER_API_ROOT

    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    assert AlpacaPaperClient.from_env().base_url == PAPER_API_ROOT


def test_alpaca_client_rejects_lookalike_or_non_v2_roots(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER", "true")
    monkeypatch.setenv("EXTRAPCAP_EXECUTION_MODE", "dry-run")
    monkeypatch.setenv("EXTRAPCAP_KEYCHAIN_ENABLED", "false")
    for value in (
        "https://paper-api.alpaca.markets.example.com/v2",
        "https://paper-api.alpaca.markets/v1",
        "https://api.alpaca.markets/v2",
    ):
        monkeypatch.setenv("ALPACA_BASE_URL", value)
        with pytest.raises(RuntimeError, match="paper Alpaca v2"):
            AlpacaPaperClient.from_env()


def test_alpaca_account_request_uses_exact_paper_v2_endpoint(monkeypatch):
    requested_urls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(request, timeout):
        requested_urls.append((request.full_url, timeout))
        return Response()

    monkeypatch.setattr("extrapcap.execution.alpaca.urlopen", fake_urlopen)
    client = AlpacaPaperClient(api_key="paper-key", secret_key="paper-secret")
    client.account()
    assert requested_urls == [("https://paper-api.alpaca.markets/v2/account", 20)]


def test_market_bars_batches_symbols_and_follows_page_tokens():
    requests = []
    client = AlpacaMarketData(api_key="paper-key", secret_key="paper-secret")

    def fake_get(path, params, base_url=None):
        requests.append(params.copy())
        batch = params["symbols"]
        token = params.get("page_token")
        if batch == "A,B" and token is None:
            return {"bars": {"A": [{"t": "a1"}]}, "next_page_token": "page-2"}
        if batch == "A,B" and token == "page-2":
            return {"bars": {"B": [{"t": "b1"}]}}
        if batch == "SPY" and token is None:
            return {"bars": {"SPY": [{"t": "spy1"}]}}
        raise AssertionError(f"unexpected request: {params}")

    client._get = fake_get
    result = client.stock_bars(["a", "b", "spy"], "start", "end", symbol_batch_size=2)

    assert result == {"bars": {"A": [{"t": "a1"}], "B": [{"t": "b1"}], "SPY": [{"t": "spy1"}]}}
    assert [request["symbols"] for request in requests] == ["A,B", "A,B", "SPY"]
    assert requests[1]["page_token"] == "page-2"


def test_nebius_without_key_escalates():
    assert NebiusReviewer(api_key=None).review({})["decision"] == "escalate"


def test_order_id_is_deterministic():
    legs = ({"symbol": "ABC240119P00100000", "asset_class": "us_option", "side": "sell", "position_intent": "sell_to_open", "ratio_qty": 1},)
    a = OrderEnvelope("2026-07-22", "ABC", "sell_to_open", legs, "core", limit_price=1.0)
    b = OrderEnvelope("2026-07-22", "ABC", "sell_to_open", legs, "core", limit_price=1.0)
    assert a.client_order_id == b.client_order_id


def test_dry_run_registry_entry_does_not_block_paper_submit(tmp_path):
    legs = ({"symbol": "ABC240119P00100000", "asset_class": "us_option", "side": "sell", "position_intent": "sell_to_open", "ratio_qty": 1},)
    envelope = OrderEnvelope("2026-07-22", "ABC", "sell_to_open", legs, "core", limit_price=1.0)
    registry = OrderRegistry(tmp_path / "ids.jsonl")
    registry.record(envelope, execution_status="dry_run")
    assert registry.contains(envelope.client_order_id) is False
    registry.record(envelope, execution_status="submitted")
    assert registry.contains(envelope.client_order_id) is True


def test_registry_blocks_only_submitted_duplicate_signals(tmp_path):
    legs = ({"symbol": "ABC240119P00100000", "asset_class": "us_option", "side": "sell", "position_intent": "sell_to_open", "ratio_qty": 1},)
    envelope = OrderEnvelope("2026-07-22", "ABC", "sell_to_open", legs, "core", limit_price=1.0)
    registry = OrderRegistry(tmp_path / "ids.jsonl")
    registry.record(envelope, {"signal_id": "sig-1"}, execution_status="dry_run")
    assert not registry.contains_signal("sig-1")
    registry.record(envelope, {"signal_id": "sig-1"}, execution_status="submitted")
    assert registry.contains_signal("sig-1")


def test_sniper_calibration_report_and_time_split():
    import pandas as pd
    features = pd.DataFrame({"x": range(10)})
    labels = pd.Series([0, 1] * 5)
    splits = time_split(features, labels)
    assert set(splits) == {"train", "validation", "test"}
    report = calibration_report([0.1, 0.9], [0, 1])
    assert report["brier"] < 0.02


def test_return_metrics_include_tail_and_downside_statistics():
    result = summarize_returns([0.1, -0.05, 0.02], elapsed_years=1.0)
    assert result["win_rate"] == pytest.approx(2 / 3)
    assert result["tail_loss_p05"] < 0
    assert result["sortino_annualized"] > 0
    assert result["cagr"] is not None
    assert "skewness" in result
