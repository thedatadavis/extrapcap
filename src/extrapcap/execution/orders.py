from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path


@dataclass(frozen=True)
class OrderEnvelope:
    trading_day: str
    symbol: str
    side: str
    legs: tuple[dict, ...]
    sleeve: str
    limit_price: float | None = None
    quantity: int = 1

    @property
    def client_order_id(self) -> str:
        canonical = json.dumps({"day": self.trading_day, "symbol": self.symbol, "side": self.side, "legs": self.legs, "sleeve": self.sleeve, "limit_price": self.limit_price, "quantity": self.quantity}, sort_keys=True)
        return "xpc-" + hashlib.sha256(canonical.encode()).hexdigest()[:24]

    def alpaca_payload(self) -> dict:
        self.validate_for_submission()
        payload = {"client_order_id": self.client_order_id, "qty": self.quantity, "order_class": "mleg", "type": "limit", "time_in_force": "day", "legs": list(self.legs)}
        if self.limit_price is not None:
            payload["limit_price"] = self.limit_price
        return payload

    def validate_for_submission(self) -> None:
        if self.quantity < 1 or self.limit_price is None or self.limit_price <= 0:
            raise ValueError("multi-leg order requires positive quantity and limit price")
        if not self.legs or any(leg.get("asset_class") != "us_option" for leg in self.legs):
            raise ValueError("multi-leg order requires resolved us_option contract symbols")


class OrderRegistry:
    def __init__(self, path: str | Path = "logs/orders/ids.jsonl"):
        self.path = Path(path)

    def contains(self, client_order_id: str) -> bool:
        if not self.path.exists():
            return False
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("client_order_id") == client_order_id:
                if record.get("execution_status", "submitted") == "submitted":
                    return True
        return False

    def record(self, envelope: OrderEnvelope, metadata: dict | None = None, *, execution_status: str = "submitted") -> None:
        if execution_status not in {"dry_run", "submitted"}:
            raise ValueError("execution status must be dry_run or submitted")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            record = {
                "client_order_id": envelope.client_order_id,
                "execution_status": execution_status,
                "trading_day": envelope.trading_day,
                "ticker": envelope.symbol.upper(),
                "underlying": envelope.symbol.upper(),
                "sleeve": envelope.sleeve,
                "side": envelope.side,
                "quantity": envelope.quantity,
                "limit_price": envelope.limit_price,
                "contract_ids": [
                    str(leg.get("symbol")).upper()
                    for leg in envelope.legs
                    if leg.get("symbol")
                ],
                "payload": envelope.alpaca_payload(),
            }
            if metadata:
                record["metadata"] = metadata
            handle.write(json.dumps(record, sort_keys=True) + "\n")
