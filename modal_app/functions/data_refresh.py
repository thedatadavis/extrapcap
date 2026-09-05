import time
from datetime import UTC, datetime, timedelta

import modal

from modal_app.bar_store import write_bar_partitions
from modal_app.base import app, image, secrets, state_volume
from modal_app.cf_client import CloudflareAPIClient


@app.function(
    image=image,
    secrets=secrets,
    schedule=modal.Cron("0 4 * * 1-5"),
    timeout=600,
)
def data_refresh():
    """Daily market data refresh (4:00 AM UTC Mon-Fri)."""
    cf = CloudflareAPIClient()
    start_time = time.time()
    run_id = cf.register_run("data_refresh")

    try:
        from urllib.request import urlopen

        from extrapcap.data.alpaca_market import AlpacaMarketData
        from extrapcap.data.normalize import completed_daily_bars, normalize_stock_bars
        from extrapcap.secrets import require_paper_credentials
        from extrapcap.universe.greenlist import (
            SOURCE_URL,
            GreenlistFilter,
            _read_csv,
            filter_greenlist,
        )

        key, secret = require_paper_credentials()
        market_data = AlpacaMarketData(api_key=key, secret_key=secret)

        # 1. Build Greenlist
        with urlopen(SOURCE_URL, timeout=30) as response:
            raw_text = response.read().decode("utf-8")
        greenlist, _ = filter_greenlist(_read_csv(raw_text), GreenlistFilter())
        symbols = [str(row["ticker"]).strip().upper() for row in greenlist]
        if "SPY" not in symbols:
            symbols.insert(0, "SPY")

        # 2. Fetch completed daily bars for full greenlist in-memory
        end = datetime.now(UTC)
        lookback_days = 90
        start = end - timedelta(days=lookback_days)
        payload = market_data.stock_bars(
            symbols,
            start.isoformat(),
            end.isoformat(),
            "1Day",
            allow_partial=True,
        )
        unresolved_symbols = sorted(payload.get("unresolved_symbols") or [])
        provider_bar_errors = payload.get("errors") or {}
        if "SPY" in unresolved_symbols or "SPY" in provider_bar_errors:
            raise RuntimeError("Alpaca could not provide the required SPY benchmark")
        raw_bars = normalize_stock_bars(payload)
        bars_df = completed_daily_bars(raw_bars, end)
        if bars_df.empty:
            raise RuntimeError("Alpaca returned no completed stock bars")
        observed_symbols = set(bars_df["symbol"].astype(str).str.upper())
        if "SPY" not in observed_symbols:
            raise RuntimeError("Alpaca returned no completed SPY benchmark bars")
        unavailable_symbols = sorted(
            set(unresolved_symbols) | set(provider_bar_errors) | (set(symbols) - observed_symbols)
        )
        available_greenlist = [
            row
            for row in greenlist
            if str(row["ticker"]).strip().upper() in observed_symbols
        ]

        if unavailable_symbols:
            cf.append_events(
                [
                    {
                        "category": "data",
                        "kind": "asset_unavailable",
                        "ticker": symbol,
                        "status": "deferred",
                        "reason": "not_available_in_completed_alpaca_bars",
                    }
                    for symbol in unavailable_symbols
                ],
                run_id=run_id,
            )

        # 3. Persist analytical bars outside D1 as immutable daily partitions.
        # The screen still runs over the complete in-memory provider response.
        bar_storage = write_bar_partitions(bars_df, state_volume)

        # 4. Run streak screening in-memory over full universe bars
        from modal_app.functions.streak_screen import run_streak_screening

        screen_result = run_streak_screening(cf, available_greenlist, bars_df, run_id=run_id)

        cf.complete_run(
            run_id,
            summary={
                "symbols_requested": len(symbols),
                "symbols_fetched": len(observed_symbols),
                "unavailable_symbols": unavailable_symbols,
                "provider_bar_errors": provider_bar_errors,
                "candidates_saved": len(screen_result.get("candidate_symbols", [])),
                "bars_rows_seen": bar_storage["input_rows"],
                "bar_partitions_written": bar_storage["partitions_written"],
                "bar_partitions_skipped": bar_storage["partitions_skipped"],
                "bar_partitions_purged": bar_storage["partitions_purged"],
                "tradable_candidates": screen_result["candidates_count"],
            },
            start_time=start_time,
        )
        return {
            "status": "success",
            "bars_count": bar_storage["input_rows"],
            "bar_partitions_written": bar_storage["partitions_written"],
            "symbols_requested": len(symbols),
            "symbols_fetched": len(observed_symbols),
            "unavailable_symbols": unavailable_symbols,
            "candidate_stocks": screen_result.get("candidate_symbols", []),
            "screen": screen_result,
        }

    except Exception as e:
        cf.fail_run(run_id, error=str(e), start_time=start_time)
        raise
