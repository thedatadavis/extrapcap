import json

from extrapcap.ledger import AuditLedger
from extrapcap.orchestration.basket_cycle_cli import basket_rows, basket_run_succeeded, run_basket


class FakeModel:
    def predict_probability(self, features):
        return [0.90 if value < -0.035 else 0.80 for value in features["relative_return"]]

    @staticmethod
    def bucket(probability):
        return "premium_candidate" if probability >= 0.65 else "trap"


def fake_model_loader(*_args):
    return FakeModel()


def test_basket_cycle_preserves_streak_selection_context(tmp_path):
    basket = tmp_path / "basket.csv"
    basket.write_text(
        "symbol,sector,streak_length,streak_depth,streak_direction,signed_streak,relative_return,robust_z,stock_return,benchmark_return,turn_of_month\n"
        "abc,Technology,3,3,negative,-3,-0.02,-2.4,-0.01,0.01,False\n",
        encoding="utf-8",
    )
    calls = []

    def fake_runner(*args, **kwargs):
        calls.append((args, kwargs))
        return {"ticker": args[0], "status": "dry_run"}

    rows = basket_rows(basket)
    results = run_basket(
        basket,
        "model.cbm",
        "2026-07-24",
        "2026-08-26",
        runner=fake_runner,
        ledger=AuditLedger(tmp_path / "logs"),
        model_loader=fake_model_loader,
    )
    assert rows[0]["ticker"] == "ABC"
    assert rows[0]["signed_streak"] == -3
    assert rows[0]["sector"] == "Technology"
    assert calls[0][1]["selection_context"]["streak_direction"] == "negative"
    assert results == [{"ticker": "ABC", "status": "dry_run"}]
    assert basket_run_succeeded(results)


def test_basket_cycle_scores_then_ranks_model_candidates_before_provider_calls(tmp_path):
    basket = tmp_path / "basket.csv"
    basket.write_text(
        "date,symbol,streak_length,streak_depth,streak_direction,signed_streak,relative_return,robust_z,dollar_volume,market_regime,stock_return,benchmark_return,turn_of_month\n"
        "2026-07-22,shrt,2,2,negative,-2,-0.03,-3.0,10000000,0.1,-0.02,0.01,False\n"
        "2026-07-22,long,5,5,negative,-5,-0.04,-2.2,12000000,0.1,-0.03,0.01,False\n"
        "2026-07-22,weak,4,4,negative,-4,-0.01,-0.5,9000000,0.1,-0.01,0.00,False\n"
        "2026-07-22,pos,5,5,positive,5,0.05,2.8,11000000,0.1,0.06,0.01,False\n",
        encoding="utf-8",
    )
    calls = []
    ledger = AuditLedger(tmp_path / "logs")

    def fake_runner(*args, **kwargs):
        calls.append((args, kwargs))
        return {"ticker": args[0], "status": "dry_run"}

    results = run_basket(
        basket,
        "model.cbm",
        "2026-07-24",
        max_candidates=1,
        runner=fake_runner,
        ledger=ledger,
        model_loader=fake_model_loader,
    )

    assert [row[0][0] for row in calls] == ["LONG"]
    assert calls[0][1]["selection_context"]["selection_rank"] == 1
    by_ticker = {result["ticker"]: result for result in results}
    assert by_ticker["SHRT"]["reason"] == "candidate_limit"
    assert by_ticker["WEAK"]["reason"] == "robust_z_above_entry_threshold"
    assert by_ticker["POS"]["strategy_route"] == "bearish_reversal_watch"
    signal_path = next((tmp_path / "logs" / "signals").glob("*.jsonl"))
    records = [
        json.loads(line)
        for line in signal_path.read_text().splitlines()
    ]
    assert {record["ticker"] for record in records} == {"LONG", "SHRT", "WEAK", "POS"}
    assert all(record["journal"]["selection_context"] for record in records)


def test_basket_cycle_fails_closed_when_every_provider_call_errors():
    assert not basket_run_succeeded([])
    assert not basket_run_succeeded([{"ticker": "ABC", "status": "error"}])


def test_basket_cycle_routes_crash_candidates_when_paper_switch_is_on(tmp_path, monkeypatch):
    basket = tmp_path / "basket.csv"
    basket.write_text(
        "symbol,sector,streak_length,streak_depth,streak_direction,signed_streak,relative_return,robust_z,stock_return,benchmark_return,turn_of_month\n"
        "crash,Technology,3,3,negative,-3,-0.04,-2.4,-0.05,0.01,False\n",
        encoding="utf-8",
    )

    class CrashModel:
        def predict_probability(self, _features):
            return [0.42]

        @staticmethod
        def bucket(_probability):
            return "crash_protocol"

    monkeypatch.setenv("EXTRAPCAP_CRASH_PROTOCOL_PAPER_ENABLED", "true")
    calls = []

    def fake_runner(*args, **kwargs):
        calls.append((args, kwargs))
        return {"ticker": args[0], "status": "dry_run"}

    results = run_basket(
        basket,
        "model.cbm",
        "2026-07-24",
        execution_mode="paper-submit",
        runner=fake_runner,
        ledger=AuditLedger(tmp_path / "logs"),
        model_loader=lambda *_args: CrashModel(),
    )
    assert results == [{"ticker": "CRASH", "status": "dry_run"}]
    assert calls[0][1]["selection_context"]["model_bucket"] == "crash_protocol"
