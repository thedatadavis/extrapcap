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

        # 2. Fetch completed daily bars for full greenlist in-memory
        end = datetime.now(timezone.utc)
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

        # 3. Run streak screening in-memory over full universe bars
        from modal_app.functions.streak_screen import run_streak_screening

        screen_result = run_streak_screening(cf, available_greenlist, bars_df, run_id=run_id)

        # 4. Limit bar inserts to Cloudflare D1 to ONLY SPY + the handful of candidate stocks
        candidate_symbols = set(screen_result.get("candidate_symbols", [])) | {"SPY"}
        candidate_bars_df = bars_df[bars_df["symbol"].astype(str).str.upper().isin(candidate_symbols)]

        bars_list = []
        for _, row in candidate_bars_df.iterrows():
            bars_list.append({
                "date": str(row["date"]),
                "symbol": str(row["symbol"]).upper(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": int(row["volume"]),
                "vwap": float(row["vwap"]) if "vwap" in row and row["vwap"] else None,
            })

        cf.upsert_bars(bars_list)
        cf.complete_run(
            run_id,
            summary={
                "symbols_requested": len(symbols),
                "symbols_fetched": len(observed_symbols),
                "unavailable_symbols": unavailable_symbols,
                "provider_bar_errors": provider_bar_errors,
                "candidates_saved": len(candidate_symbols - {"SPY"}),
                "bars_upserted": len(bars_list),
                "tradable_candidates": screen_result["candidates_count"],
            },
            start_time=start_time,
        )
        return {
            "status": "success",
            "bars_count": len(bars_list),
            "symbols_requested": len(symbols),
            "symbols_fetched": len(observed_symbols),
            "unavailable_symbols": unavailable_symbols,
            "candidate_stocks": list(candidate_symbols),
            "screen": screen_result,
        }

    except Exception as e:
        cf.fail_run(run_id, error=str(e), start_time=start_time)
        raise
