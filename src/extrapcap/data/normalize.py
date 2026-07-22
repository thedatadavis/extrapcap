from __future__ import annotations

import pandas as pd


def normalize_stock_bars(payload: dict) -> pd.DataFrame:
    rows = []
    for symbol, bars in payload.get("bars", {}).items():
        for bar in bars:
            rows.append({"date": pd.to_datetime(bar["t"], utc=True), "symbol": symbol, "open": bar["o"], "high": bar["h"], "low": bar["l"], "close": bar["c"], "volume": bar["v"], "vwap": bar.get("vw")})
    if not rows:
        return pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close", "volume", "vwap"])
    return pd.DataFrame(rows).sort_values(["symbol", "date"]).reset_index(drop=True)
