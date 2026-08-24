from datetime import date

from extrapcap.ledger import AuditLedger
from extrapcap.options_data import AlpacaOptionsRequestError
from extrapcap.orchestration.basket_cycle import run_basket


def _basket(size: int) -> list[dict]:
    return [{"ticker": f"T{index:02d}", "sector": "Test", "formation_date": "2026-08-12", "streak_length": 3, "streak_direction": "negative", "robust_z": -2.0, "relative_return": -0.03, "reversion_probability": 0.7, "underlying_price": 100} for index in range(size)]


def test_run_basket_evaluates_every_viable_candidate(tmp_path):
    calls = []
    def runner(**kwargs):
        calls.append(kwargs["symbol"])
        return {"ticker": kwargs["symbol"], "status": "vetoed", "reason": "test"}
    results = run_basket(_basket(30), audit=AuditLedger(tmp_path), runner=runner, trading_day=date(2026, 8, 12))
    assert len(calls) == 30
    assert len(results) == 30


def test_run_basket_contains_provider_error_and_continues(tmp_path):
    calls = []
    def runner(**kwargs):
        calls.append(kwargs["symbol"])
        if len(calls) == 1:
            raise AlpacaOptionsRequestError("Alpaca option data request failed: invalid symbol")
        return {"ticker": kwargs["symbol"], "status": "vetoed", "reason": "no_spread"}
    results = run_basket(_basket(2), audit=AuditLedger(tmp_path), runner=runner, trading_day=date(2026, 8, 12))
    assert calls == ["T00", "T01"]
    assert results[0]["status"] == "error"
    assert "invalid symbol" in results[0]["reason"]
    assert results[1]["reason"] == "no_spread"


def test_run_basket_stops_after_submission_limit(tmp_path):
    calls = []

    def runner(**kwargs):
        calls.append(kwargs["symbol"])
        return {"ticker": kwargs["symbol"], "status": "pending_new"}

    results = run_basket(
        _basket(4),
        audit=AuditLedger(tmp_path),
        runner=runner,
        trading_day=date(2026, 8, 12),
        max_submissions=1,
    )
    assert calls == ["T00"]
    assert results[0]["status"] == "pending_new"
    assert results[-1] == {
        "category": "signals",
        "kind": "basket_selection_summary",
        "status": "deferred",
        "reason": "submission_limit",
        "eligible": 4,
        "evaluated": 1,
        "deferred": 3,
    }


def test_run_basket_treats_no_spread_as_veto(tmp_path):
    def runner(**_kwargs):
        raise ValueError("no bullish vertical spread meets expected value threshold")

    [result] = run_basket(
        _basket(1),
        audit=AuditLedger(tmp_path),
        runner=runner,
        trading_day=date(2026, 8, 12),
    )
    assert result["status"] == "vetoed"
