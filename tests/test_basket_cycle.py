from extrapcap.orchestration.basket_cycle_cli import basket_rows, basket_run_succeeded, run_basket


def test_basket_cycle_preserves_streak_selection_context(tmp_path):
    basket = tmp_path / "basket.csv"
    basket.write_text(
        "symbol,streak_length,streak_direction,signed_streak,relative_return,robust_z\n"
        "abc,3,negative,-3,-0.02,-2.4\n",
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
    )
    assert rows[0]["ticker"] == "ABC"
    assert rows[0]["signed_streak"] == -3
    assert calls[0][1]["selection_context"]["streak_direction"] == "negative"
    assert results == [{"ticker": "ABC", "status": "dry_run"}]
    assert basket_run_succeeded(results)


def test_basket_cycle_fails_closed_when_every_provider_call_errors():
    assert not basket_run_succeeded([])
    assert not basket_run_succeeded([{"ticker": "ABC", "status": "error"}])
