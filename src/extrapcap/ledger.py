from __future__ import annotations

import json
import hashlib
from datetime import date, datetime, timezone
from pathlib import Path
import subprocess

from .options_data import parse_occ_option_symbol


def _contract_ids(value) -> list[str]:
    found: set[str] = set()

    def visit(item) -> None:
        if isinstance(item, dict):
            is_option_leg = item.get("asset_class") == "us_option"
            for key, child in item.items():
                if key == "contract_ids" and isinstance(child, (list, tuple)):
                    found.update(str(symbol).upper() for symbol in child if symbol)
                elif key in {"contract_id", "contract_symbol"} and isinstance(child, str):
                    found.add(child.upper())
                elif key == "symbol" and is_option_leg and isinstance(child, str):
                    found.add(child.upper())
                else:
                    visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    visit(value)
    return sorted(found)


def _contract_details(contract_ids: list[str]) -> list[dict]:
    details = []
    for contract_id in contract_ids:
        try:
            parsed = parse_occ_option_symbol(contract_id)
        except ValueError:
            details.append({"contract_id": contract_id})
            continue
        details.append(
            {
                "contract_id": parsed.symbol,
                "ticker": parsed.underlying,
                "expiration": parsed.expiration.isoformat(),
                "option_type": "put" if parsed.option_type == "P" else "call",
                "strike": parsed.strike,
            }
        )
    return details


def _ticker(event: dict, contract_details: list[dict]) -> str | None:
    for key in ("ticker", "underlying", "symbol"):
        value = event.get(key)
        if isinstance(value, str) and value:
            try:
                parse_occ_option_symbol(value)
            except ValueError:
                return value.upper()
    spread = event.get("spread")
    if isinstance(spread, dict) and isinstance(spread.get("symbol"), str):
        return spread["symbol"].upper()
    for detail in contract_details:
        if detail.get("ticker"):
            return str(detail["ticker"]).upper()
    return None


def journal_metadata(category: str, event: dict, trading_day: date) -> dict:
    """Build the stable, human-readable index consumed by reports and Astro."""
    contract_ids = _contract_ids(event)
    contract_details = _contract_details(contract_ids)
    ticker = _ticker(event, contract_details)
    judgment = event.get("judgment") if isinstance(event.get("judgment"), dict) else {}
    status = event.get("status") or judgment.get("decision") or event.get("decision") or "recorded"
    reason = event.get("reason") or judgment.get("reason")
    kind = event.get("kind") or category.rstrip("s")
    identity = json.dumps(
        {"category": category, "trading_day": trading_day.isoformat(), "event": event},
        sort_keys=True,
        default=str,
    )
    title_parts = [part for part in (ticker, str(kind).replace("_", " "), str(status).replace("_", " ")) if part]
    return {
        "schema_version": 1,
        "event_id": "evt-" + hashlib.sha256(identity.encode()).hexdigest()[:20],
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "trading_day": trading_day.isoformat(),
        "category": category,
        "kind": kind,
        "title": " · ".join(title_parts),
        "ticker": ticker,
        "contract_ids": contract_ids,
        "contract_details": contract_details,
        "status": status,
        "reason": reason,
        "client_order_id": event.get("client_order_id"),
        "sleeve": event.get("sleeve") or (event.get("spread") or {}).get("sleeve"),
        "strategy_variant": event.get("strategy_variant"),
        "strategy_route": event.get("strategy_route"),
        "selection_rank": event.get("selection_rank"),
        "model_probability": event.get("model_probability"),
        "model_bucket": event.get("model_bucket"),
        "data_tier": event.get("data_tier"),
        "provider": judgment.get("provider") or event.get("provider"),
        "selection_context": event.get("selection_context") or {},
    }


class AuditLedger:
    """Append-only JSONL writer used by workflows and replay tooling."""

    def __init__(self, root: str | Path = "logs"):
        self.root = Path(root)

    def append(
        self,
        category: str,
        event: dict,
        trading_day: date | None = None,
        *,
        deduplicate: bool = False,
    ) -> Path:
        day = trading_day or date.today()
        path = self.root / category / f"{day.isoformat()}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = dict(event)
        metadata = journal_metadata(category, record, day)
        record["ticker"] = metadata["ticker"]
        record["contract_ids"] = metadata["contract_ids"]
        record["journal"] = metadata
        if deduplicate and path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    existing = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (existing.get("journal") or {}).get("event_id") == metadata["event_id"]:
                    return path
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
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
