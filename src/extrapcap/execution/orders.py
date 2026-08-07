from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json


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
        return {"client_order_id": self.client_order_id, "qty": self.quantity, "order_class": "mleg", "type": "limit", "time_in_force": "day", "legs": list(self.legs), "limit_price": self.limit_price}

    def validate_for_submission(self) -> None:
        if self.quantity < 1 or self.limit_price is None or self.limit_price <= 0:
            raise ValueError("multi-leg order requires positive quantity and limit price")
        if not self.legs or any(leg.get("asset_class") != "us_option" for leg in self.legs):
            raise ValueError("multi-leg order requires resolved us_option contract symbols")
