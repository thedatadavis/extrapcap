from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
import os
from pathlib import Path

from ..llm.nebius import NebiusReviewer
from ..playback import replay_day
from .daily_note import build_daily_note


def render_daily_report(root: str | Path, trading_day: str, output: str | Path) -> Path:
    events = replay_day(root, trading_day)
    categories = Counter(event["category"] for event in events)
    statuses = Counter(str(event.get("status", "unknown")) for event in events)
    report = {
        "kind": "daily_operations_report",
        "trading_day": trading_day,
        "event_count": len(events),
        "categories": dict(sorted(categories.items())),
        "statuses": dict(sorted(statuses.items())),
        "events": events,
        "portfolio_note": build_daily_note(
            events,
            trading_day,
            NebiusReviewer() if os.getenv("EXTRAPCAP_DAILY_LLM", "false").lower() == "true" else None,
        ),
    }
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a replayable daily operations report")
    parser.add_argument("--root", default="logs")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--output", default="reports/daily.json")
    args = parser.parse_args()
    path = render_daily_report(args.root, args.date, args.output)
    print(json.dumps({"status": "written", "output": str(path)}, indent=2))


if __name__ == "__main__":
    main()
