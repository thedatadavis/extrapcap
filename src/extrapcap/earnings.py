from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


NASDAQ_EARNINGS_URL = "https://api.nasdaq.com/api/calendar/earnings"
NASDAQ_SOURCE_PAGE = "https://www.nasdaq.com/market-activity/earnings"
CSV_FIELDS = (
    "date",
    "symbol",
    "report_time",
    "company_name",
    "fiscal_quarter_ending",
    "eps_forecast",
    "estimate_count",
)


def calendar_dates(center: date, calendar_days: int = 3) -> list[date]:
    if calendar_days < 0:
        raise ValueError("calendar_days must be non-negative")
    return [center + timedelta(days=offset) for offset in range(-calendar_days, calendar_days + 1)]


def fetch_nasdaq_day(day: date, opener=urlopen) -> list[dict]:
    """Fetch one free Nasdaq expected-earnings calendar page."""
    url = f"{NASDAQ_EARNINGS_URL}?{urlencode({'date': day.isoformat()})}"
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; Extrapcap/0.1; research paper trading)",
            "Accept": "application/json, text/plain, */*",
            "Referer": NASDAQ_SOURCE_PAGE,
        },
    )
    with opener(request, timeout=30) as response:
        payload = json.loads(response.read())
    status = payload.get("status") or {}
    if status.get("rCode") not in (None, 200):
        raise RuntimeError(f"Nasdaq earnings request failed for {day}: {status.get('rCode')}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"Nasdaq earnings response missing data for {day}")
    rows = data.get("rows") or []
    if not isinstance(rows, list):
        raise RuntimeError(f"Nasdaq earnings response has invalid rows for {day}")
    normalized = []
    for row in rows:
        symbol = str(row.get("symbol", "")).strip().upper()
        if not symbol:
            continue
        normalized.append(
            {
                "date": day.isoformat(),
                "symbol": symbol,
                "report_time": str(row.get("time", "")).removeprefix("time-"),
                "company_name": str(row.get("name", "")).strip(),
                "fiscal_quarter_ending": str(row.get("fiscalQuarterEnding", "")).strip(),
                "eps_forecast": str(row.get("epsForecast", "")).strip(),
                "estimate_count": str(row.get("noOfEsts", "")).strip(),
            }
        )
    return normalized


def refresh_earnings_calendar(
    center: date,
    output: str | Path = "data/events/earnings.csv",
    *,
    calendar_days: int = 3,
    retrieved_at: datetime | None = None,
    fetcher=fetch_nasdaq_day,
) -> tuple[Path, Path, dict]:
    """Write a complete, versioned blackout window or fail without replacing it."""
    retrieved = retrieved_at or datetime.now(timezone.utc)
    dates = calendar_dates(center, calendar_days)
    rows = []
    counts = {}
    for day in dates:
        day_rows = fetcher(day)
        counts[day.isoformat()] = len(day_rows)
        rows.extend(day_rows)
    rows = sorted(
        {(
            row["date"],
            row["symbol"],
            row["report_time"],
            row["company_name"],
            row["fiscal_quarter_ending"],
            row["eps_forecast"],
            row["estimate_count"],
        ) for row in rows}
    )
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(CSV_FIELDS)
        writer.writerows(rows)
    temporary.replace(target)

    metadata = {
        "schema_version": 1,
        "source": "nasdaq.expected_earnings_calendar",
        "source_page": NASDAQ_SOURCE_PAGE,
        "endpoint": NASDAQ_EARNINGS_URL,
        "retrieved_at": retrieved.astimezone(timezone.utc).isoformat(),
        "center_date": center.isoformat(),
        "blackout_calendar_days": calendar_days,
        "coverage_start": dates[0].isoformat(),
        "coverage_end": dates[-1].isoformat(),
        "queried_dates": [day.isoformat() for day in dates],
        "row_count": len(rows),
        "rows_by_date": counts,
        "methodology": (
            "Expected dates are derived by Nasdaq from an algorithm based on historical "
            "reporting dates; absence from a fully queried date means no expected report was returned."
        ),
    }
    metadata_target = Path(f"{target}.metadata.json")
    metadata_target.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return target, metadata_target, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh the free expected-earnings blackout calendar")
    parser.add_argument("--date", help="center trading date; defaults to today UTC")
    parser.add_argument("--calendar-days", type=int, default=3)
    parser.add_argument("--output", default="data/events/earnings.csv")
    args = parser.parse_args()
    center = date.fromisoformat(args.date) if args.date else datetime.now(timezone.utc).date()
    target, metadata_target, metadata = refresh_earnings_calendar(
        center,
        args.output,
        calendar_days=args.calendar_days,
    )
    print(json.dumps({"calendar": str(target), "metadata": str(metadata_target), **metadata}, indent=2))


if __name__ == "__main__":
    main()
