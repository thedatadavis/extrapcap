from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from .alpaca_market import AlpacaMarketData
from .normalize import completed_daily_bars, completed_session_cutoff, normalize_stock_bars


def build_bar_metadata(
    frame,
    symbols: list[str],
    start: datetime,
    end: datetime,
    retrieved_at: datetime,
    *,
    source_row_count: int | None = None,
) -> dict:
    return {
        "source": "alpaca.market_data.stock_bars",
        "feed": "iex",
        "timeframe": "1Day",
        "adjustment": "all",
        "symbols": symbols,
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "retrieved_at": retrieved_at.isoformat(),
        "row_count": int(len(frame)),
        "source_row_count": int(source_row_count if source_row_count is not None else len(frame)),
        "excluded_incomplete_rows": int((source_row_count if source_row_count is not None else len(frame)) - len(frame)),
        "completed_session_cutoff": completed_session_cutoff(retrieved_at).isoformat(),
        "date_min": frame["date"].min().isoformat() if not frame.empty else None,
        "date_max": frame["date"].max().isoformat() if not frame.empty else None,
        "symbol_counts": {str(symbol): int(count) for symbol, count in frame["symbol"].value_counts().sort_index().items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh normalized Alpaca stock bars")
    parser.add_argument("--symbols", required=True, help="comma-separated symbols")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--output", default="data/normalized/bars.csv")
    parser.add_argument("--metadata-output", help="JSON provenance sidecar; defaults to <output>.metadata.json")
    args = parser.parse_args()
    symbols = [value.strip().upper() for value in args.symbols.split(",") if value.strip()]
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    payload = AlpacaMarketData().stock_bars(symbols, start.isoformat(), end.isoformat(), "1Day")
    raw_frame = normalize_stock_bars(payload)
    retrieved_at = datetime.now(timezone.utc)
    frame = completed_daily_bars(raw_frame, retrieved_at)
    if frame.empty:
        raise RuntimeError("Alpaca returned no completed stock bars")
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(target, index=False)
    metadata_target = Path(args.metadata_output or f"{args.output}.metadata.json")
    metadata_target.parent.mkdir(parents=True, exist_ok=True)
    metadata = build_bar_metadata(
        frame,
        symbols,
        start,
        end,
        retrieved_at,
        source_row_count=len(raw_frame),
    )
    metadata_target.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
