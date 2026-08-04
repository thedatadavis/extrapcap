#!/usr/bin/env python3
"""
Migration Script: Backfill historical JSONL logs and CSV data into Cloudflare D1.

Usage:
  python scripts/migrate_to_d1.py --output-sql schema_data.sql
  # or
  python scripts/migrate_to_d1.py --cf-account <id> --cf-token <token> --db-id <id>
"""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def parse_events(logs_dir: Path) -> list[dict]:
    events = []
    if not logs_dir.exists():
        return events

    for category_dir in sorted(logs_dir.iterdir()):
        if not category_dir.is_dir():
            continue
        category = category_dir.name
        for jsonl_file in sorted(category_dir.glob("*.jsonl")):
            day = jsonl_file.stem
            for line in jsonl_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                    j = raw.get("journal", {})
                    event_id = j.get("event_id") or raw.get("event_id") or f"evt-{len(events):06d}"
                    events.append({
                        "event_id": event_id,
                        "trading_day": j.get("trading_day") or day,
                        "category": j.get("category") or category,
                        "kind": j.get("kind"),
                        "ticker": j.get("ticker"),
                        "status": j.get("status"),
                        "reason": j.get("reason"),
                        "sleeve": j.get("sleeve"),
                        "strategy_variant": j.get("strategy_variant"),
                        "strategy_route": j.get("strategy_route"),
                        "model_probability": j.get("model_probability"),
                        "payload": json.dumps(raw),
                    })
                except Exception as err:
                    print(f"Error reading line in {jsonl_file}: {err}", file=sys.stderr)
    return events


def parse_account_snapshots(reports_dir: Path) -> list[dict]:
    snapshots = []
    if not reports_dir.exists():
        return snapshots

    for jsonl_file in sorted(reports_dir.glob("*.jsonl")):
        day = jsonl_file.stem
        for line in jsonl_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                acc = raw.get("account", raw)
                snapshots.append({
                    "as_of": day,
                    "equity": acc.get("equity") or acc.get("portfolio_value", 0.0),
                    "cash": acc.get("cash", 0.0),
                    "buying_power": acc.get("buying_power", 0.0),
                    "portfolio_value": acc.get("portfolio_value", 0.0),
                    "daily_pnl": acc.get("daily_pnl", 0.0),
                    "payload": json.dumps(raw),
                })
            except Exception as err:
                print(f"Error reading snapshot in {jsonl_file}: {err}", file=sys.stderr)
    return snapshots


def generate_sql(events: list[dict], snapshots: list[dict], output_file: Path):
    lines = []
    lines.append("-- Generated D1 Data Migration")

    for e in events:
        sql = """INSERT OR IGNORE INTO events (event_id, trading_day, category, kind, ticker, status, reason, sleeve, strategy_variant, strategy_route, model_probability, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);"""
        # SQLite string formatting for SQL dump
        params = [
            e["event_id"], e["trading_day"], e["category"], e["kind"],
            e["ticker"], e["status"], e["reason"], e["sleeve"],
            e["strategy_variant"], e["strategy_route"], e["model_probability"],
            e["payload"]
        ]
        # Quote values properly
        quoted = []
        for p in params:
            if p is None:
                quoted.append("NULL")
            elif isinstance(p, (int, float)):
                quoted.append(str(p))
            else:
                s = str(p).replace("'", "''")
                quoted.append(f"'{s}'")
        lines.append(f"INSERT OR IGNORE INTO events (event_id, trading_day, category, kind, ticker, status, reason, sleeve, strategy_variant, strategy_route, model_probability, payload) VALUES ({', '.join(quoted)});")

    for s in snapshots:
        params = [s["as_of"], s["equity"], s["cash"], s["buying_power"], s["portfolio_value"], s["daily_pnl"], s["payload"]]
        quoted = []
        for p in params:
            if p is None:
                quoted.append("NULL")
            elif isinstance(p, (int, float)):
                quoted.append(str(p))
            else:
                q = str(p).replace("'", "''")
                quoted.append(f"'{q}'")
        lines.append(f"INSERT OR IGNORE INTO account_snapshots (as_of, equity, cash, buying_power, portfolio_value, daily_pnl, payload) VALUES ({', '.join(quoted)});")

    output_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {len(events)} events and {len(snapshots)} account snapshots to {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Migrate Extrapcap JSONL logs to D1 SQL")
    parser.add_argument("--output-sql", type=str, default="data_migration.sql", help="Path to output SQL file")
    args = parser.parse_args()

    logs_dir = REPO_ROOT / "logs"
    reports_dir = REPO_ROOT / "logs" / "reports"

    events = parse_events(logs_dir)
    snapshots = parse_account_snapshots(reports_dir)

    out_path = Path(args.output_sql)
    generate_sql(events, snapshots, out_path)


if __name__ == "__main__":
    main()
