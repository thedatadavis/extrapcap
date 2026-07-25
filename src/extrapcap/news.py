from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path

from .data.alpaca_market import AlpacaMarketData
from .events import classify_headline


CSV_FIELDS = ("date", "symbol", "structural_risk", "headline")


def parse_article_rows(articles: list[dict]) -> list[dict]:
    """Convert raw Alpaca news payload articles into normalized event CSV rows."""
    rows = []
    for item in articles:
        headline = str(item.get("headline", "")).strip()
        if not headline:
            continue
        created_at_str = item.get("created_at") or item.get("updated_at")
        if created_at_str:
            try:
                dt = datetime.fromisoformat(str(created_at_str).replace("Z", "+00:00"))
                event_date = dt.date().isoformat()
            except (ValueError, TypeError):
                event_date = date.today().isoformat()
        else:
            event_date = date.today().isoformat()

        symbols = item.get("symbols") or []
        if isinstance(symbols, str):
            symbols = [symbols]

        local_decision = classify_headline(headline)
        structural_risk = not local_decision.allowed

        for sym in symbols:
            clean_sym = str(sym).strip().upper()
            if not clean_sym:
                continue
            rows.append(
                {
                    "date": event_date,
                    "symbol": clean_sym,
                    "structural_risk": "true" if structural_risk else "false",
                    "headline": headline.replace("\n", " ").replace("\r", " "),
                }
            )
    return rows


def refresh_news_events(
    output: str | Path = "data/events/news.csv",
    symbols: list[str] | None = None,
    days: int = 3,
    limit: int = 50,
    *,
    client: AlpacaMarketData | None = None,
    retrieved_at: datetime | None = None,
) -> tuple[Path, Path, dict]:
    """Fetch news from Alpaca and write a versioned data/events/news.csv file."""
    retrieved = retrieved_at or datetime.now(timezone.utc)
    market_client = client or AlpacaMarketData()

    end_dt = retrieved
    start_dt = end_dt - timedelta(days=days)
    start_str = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_str = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    payload = market_client.news(
        symbols=symbols,
        start=start_str,
        end=end_str,
        limit=limit,
    )
    articles = payload.get("news") or []
    new_rows = parse_article_rows(articles)

    target = Path(output)
    sidecar = Path(f"{target}.metadata.json")
    target.parent.mkdir(parents=True, exist_ok=True)

    # Read existing rows if target file exists to preserve cumulative news history
    existing_rows: list[dict] = []
    if target.exists():
        try:
            with target.open(newline="", encoding="utf-8") as handle:
                existing_rows = list(csv.DictReader(handle))
        except Exception:
            existing_rows = []

    combined_map: dict[tuple[str, str, str], dict] = {}
    for r in existing_rows:
        key = (r.get("date", ""), r.get("symbol", ""), r.get("headline", ""))
        if key[0] and key[1] and key[2]:
            combined_map[key] = r

    for r in new_rows:
        key = (r["date"], r["symbol"], r["headline"])
        combined_map[key] = r

    sorted_rows = sorted(
        combined_map.values(),
        key=lambda x: (x["date"], x["symbol"], x["headline"]),
    )

    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(sorted_rows)

    structural_count = sum(1 for r in sorted_rows if str(r.get("structural_risk")).lower() in {"true", "1"})
    metadata = {
        "source": "alpaca_news_feed",
        "retrieved_at": retrieved.isoformat(),
        "query_start": start_str,
        "query_end": end_str,
        "symbols_requested": symbols,
        "articles_fetched": len(articles),
        "total_event_rows": len(sorted_rows),
        "structural_risk_vetoes": structural_count,
    }
    sidecar.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return target, sidecar, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh dated structural-news events from Alpaca News feed")
    parser.add_argument("--output", default="data/events/news.csv", help="output news CSV file path")
    parser.add_argument("--symbols", help="comma-separated list of ticker symbols")
    parser.add_argument("--days", type=int, default=3, help="lookback window in days")
    parser.add_argument("--limit", type=int, default=50, help="max news items to fetch")
    args = parser.parse_args()

    symbol_list = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else None
    target, sidecar, metadata = refresh_news_events(
        output=args.output,
        symbols=symbol_list,
        days=args.days,
        limit=args.limit,
    )
    print(f"Wrote {metadata['total_event_rows']} news event rows to {target} (metadata: {sidecar})")


if __name__ == "__main__":
    main()
