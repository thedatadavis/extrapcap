from __future__ import annotations

import argparse
import json
from .playback import replay_day


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay one Extrapcap trading day")
    parser.add_argument("--root", default="logs")
    parser.add_argument("--date", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    events = replay_day(args.root, args.date)
    encoded = json.dumps({"trading_day": args.date, "events": events, "event_count": len(events)}, indent=2) + "\n"
    if args.output:
        from pathlib import Path
        Path(args.output).write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
