from __future__ import annotations

import json
from pathlib import Path


def replay_day(root: str | Path, trading_day: str) -> list[dict]:
    """Rebuild a deterministic event timeline from the daily JSONL ledger."""
    events = []
    for path in sorted(Path(root).glob(f"*/{trading_day}.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append({"category": path.parent.name, **json.loads(line)})
    return events
