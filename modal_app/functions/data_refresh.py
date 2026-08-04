import time
from datetime import datetime, timezone
import modal
from modal_app.app import app, image, secrets
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
        from extrapcap.data.market_data import AlpacaMarketData
        from extrapcap.universe.greenlist import build_greenlist_snapshot

        key, secret = require_paper_credentials()
        market_data = AlpacaMarketData(api_key=key, secret_key=secret)

        # 1. Build Greenlist
        greenlist = build_greenlist_snapshot()
        symbols = list(greenlist["symbol"])
        if "SPY" not in symbols:
            symbols.insert(0, "SPY")

        # 2. Fetch bars for 730 days
        bars_df = market_data.stock_bars(symbols=symbols, days=730)

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
        cf.complete_run(run_id, summary={"symbols_fetched": len(symbols), "bars_upserted": len(bars_list)}, start_time=start_time)
        return {"status": "success", "bars_count": len(bars_list)}

    except Exception as e:
        cf.fail_run(run_id, error=str(e), start_time=start_time)
        raise
