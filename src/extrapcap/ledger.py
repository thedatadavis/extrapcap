from __future__ import annotations

import json
from datetime import date
from pathlib import Path
import subprocess


class AuditLedger:
    """Append-only JSONL writer used by workflows and replay tooling."""

    def __init__(self, root: str | Path = "logs"):
        self.root = Path(root)

    def append(self, category: str, event: dict, trading_day: date | None = None) -> Path:
        day = trading_day or date.today()
        path = self.root / category / f"{day.isoformat()}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
        return path

    def commit_day(self, trading_day: str, message_prefix: str = "ledger") -> bool:
        """Commit only this day's ledger files with a deterministic message."""
        files = sorted(str(path) for path in self.root.glob(f"*/{trading_day}.jsonl"))
        if not files:
            return False
        subprocess.run(["git", "add", *files], check=True)
        result = subprocess.run(["git", "diff", "--cached", "--quiet"], check=False)
        if result.returncode == 0:
            return False
        subprocess.run(["git", "commit", "-m", f"{message_prefix}: {trading_day}"], check=True)
        return True
