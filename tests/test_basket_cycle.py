import json

from extrapcap.ledger import AuditLedger
from extrapcap.orchestration.basket_cycle_cli import basket_rows, basket_run_succeeded, run_basket


def test_basket_cycle_preserves_streak_selection_context(tmp_path):
    basket = tmp_path / "basket.csv"
    basket.write_text(
        "symbol,sector,streak_length,streak_direction,signed_streak,relative_return,robust_z\n"
        "abc,Technology,3,negative,-3,-0.02,-2.4\n",
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
    )
    assert rows[0]["ticker"] == "ABC"
    assert rows[0]["signed_streak"] == -3
    assert rows[0]["sector"] == "Technology"
    assert calls[0][1]["selection_context"]["streak_direction"] == "negative"
    assert results == [{"ticker": "ABC", "status": "dry_run"}]
    assert basket_run_succeeded(results)


def test_basket_cycle_routes_and_ranks_streaks_before_provider_calls(tmp_path):
    basket = tmp_path / "basket.csv"
    basket.write_text(
        "date,symbol,streak_length,streak_direction,signed_streak,relative_return,robust_z,dollar_volume,market_regime\n"
        "2026-07-22,shrt,2,negative,-2,-0.03,-3.0,10000000,0.1\n"
        "2026-07-22,long,5,negative,-5,-0.04,-2.2,12000000,0.1\n"
        "2026-07-22,weak,4,negative,-4,-0.01,-0.5,9000000,0.1\n"
        "2026-07-22,pos,5,positive,5,0.05,2.8,11000000,0.1\n",
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
