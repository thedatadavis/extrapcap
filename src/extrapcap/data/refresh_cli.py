from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from .alpaca_market import AlpacaMarketData
from .normalize import completed_daily_bars, completed_session_cutoff, normalize_stock_bars


def symbols_from_greenlist(path: str | Path, benchmark_symbol: str = "SPY") -> list[str]:
    """Return the pinned Greenlist symbols plus the benchmark, in stable order."""
    with Path(path).open(newline="", encoding="utf-8") as handle:
        rows = csv.DictReader(handle)
        if not rows.fieldnames or "ticker" not in rows.fieldnames:
            raise ValueError("Greenlist CSV must contain a ticker column")
        symbols = [str(row.get("ticker", "")).strip().upper() for row in rows]
    benchmark = benchmark_symbol.strip().upper()
    if not benchmark:
        raise ValueError("benchmark symbol must not be empty")
    return list(dict.fromkeys([benchmark, *symbols]))


def build_bar_metadata(
    frame,
    symbols: list[str],
    start: datetime,
    end: datetime,
    retrieved_at: datetime,
    *,
    source_row_count: int | None = None,
) -> dict:
    observed_symbols = sorted({str(symbol).upper() for symbol in frame["symbol"].unique()})
    missing_symbols = [symbol for symbol in symbols if symbol not in observed_symbols]
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
        "coverage": {
            "requested_symbol_count": len(symbols),
            "observed_symbol_count": len(set(symbols) & set(observed_symbols)),
            "missing_symbol_count": len(missing_symbols),
            "missing_symbols": missing_symbols,
            "complete": not missing_symbols,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh normalized Alpaca stock bars")
    symbol_group = parser.add_mutually_exclusive_group(required=True)
    symbol_group.add_argument("--symbols", help="comma-separated symbols")
    symbol_group.add_argument("--greenlist", help="pinned Greenlist CSV; refresh every accepted ticker plus the benchmark")
    parser.add_argument("--benchmark-symbol", default="SPY")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--output", default="data/normalized/bars.csv")
    parser.add_argument("--metadata-output", help="JSON provenance sidecar; defaults to <output>.metadata.json")
    args = parser.parse_args()
    symbols = (
        symbols_from_greenlist(args.greenlist, args.benchmark_symbol)
        if args.greenlist
        else list(dict.fromkeys(value.strip().upper() for value in args.symbols.split(",") if value.strip()))
    )
    if not symbols:
        raise ValueError("bar refresh requires at least one symbol")
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
