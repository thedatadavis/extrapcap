import time
from datetime import datetime, timedelta, timezone
import modal
from modal_app.base import app, image, secrets
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
        from extrapcap.secrets import require_paper_credentials
        from extrapcap.data.alpaca_market import AlpacaMarketData
        from extrapcap.data.normalize import completed_daily_bars, normalize_stock_bars
        from urllib.request import urlopen
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

        # 2. Fetch and normalize enough completed daily bars for the 20-day
        # robust-Z screen. Keep the lookback configurable without sending a
        # multi-year, several-hundred-thousand-row request through Pages.
        end = datetime.now(timezone.utc)
        lookback_days = 756
        start = end - timedelta(days=lookback_days)
        payload = market_data.stock_bars(
            symbols,
            start.isoformat(),
            end.isoformat(),
            "1Day",
        )
        raw_bars = normalize_stock_bars(payload)
        bars_df = completed_daily_bars(raw_bars, end)
        if bars_df.empty:
            raise RuntimeError("Alpaca returned no completed stock bars")

        # 3. Format and send to Cloudflare D1
        bars_list = []
        for _, row in bars_df.iterrows():
            bars_list.append({
                "date": str(row["date"]),
                "symbol": str(row["symbol"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
                "vwap": float(row["vwap"]) if "vwap" in row and row["vwap"] else None,
            })

        cf.upsert_bars(bars_list)
        cf.store_universe(greenlist)

        # Screening depends on these exact completed bars, so keep both steps
        # in one scheduled workflow instead of relying on a second cron.
        from modal_app.functions.streak_screen import streak_screen

        screen_result = streak_screen.local()
        cf.complete_run(
            run_id,
            summary={
                "symbols_fetched": len(symbols),
                "bars_upserted": len(bars_list),
                "tradable_candidates": screen_result["candidates_count"],
            },
            start_time=start_time,
        )
        return {
            "status": "success",
            "bars_count": len(bars_list),
            "screen": screen_result,
        }

    except Exception as e:
        cf.fail_run(run_id, error=str(e), start_time=start_time)
        raise
