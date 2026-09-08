"""Position exits for short-horizon option spreads."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from ..config import RiskConfig
from ..execution.orders import OrderEnvelope
from ..options import DebitSpread


@dataclass(frozen=True)
class ExitDecision:
    action: str
    reason: str


@dataclass(frozen=True)
class ManagedPosition:
    envelope: OrderEnvelope
    entry_price: float
    current_debit: float
    spread_width: float
    opened_at: date
    as_of: date
    expiration: date | None = None

    @property
    def return_on_capital(self) -> float:
        capital = max(0.01, self.spread_width - self.entry_price)
        return (self.entry_price - self.current_debit) / capital

    @property
    def return_on_credit(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        return (self.entry_price - self.current_debit) / self.entry_price

    @property
    def max_loss(self) -> float:
        return max(0.01, self.spread_width - self.entry_price)

    @property
    def days_held(self) -> int:
        cur = self.opened_at
        count = 0
        while cur < self.as_of:
            cur += timedelta(days=1)
            if cur.weekday() < 5:
                count += 1
        return count


def _expiration_horizon(position: ManagedPosition, cfg: RiskConfig) -> ExitDecision | None:
    if position.expiration is not None:
        dte = (position.expiration - position.as_of).days
        if dte < 0:
            return ExitDecision("close", "expired_position")
        if dte <= cfg.forced_exit_dte:
            return ExitDecision("close", f"forced_exit_dte_{dte}")
        if dte == 0 and position.opened_at == position.as_of:
            return ExitDecision("close", "zero_dte_session_exit")
    return None


def evaluate_credit_exit(
    position: ManagedPosition, config: RiskConfig | None = None
) -> ExitDecision:
    cfg = config or RiskConfig()
    expiration_exit = _expiration_horizon(position, cfg)
    if expiration_exit:
        return expiration_exit

    profit_pct = max(position.return_on_credit, position.return_on_capital)
    if (
        profit_pct >= cfg.early_profit_target_pct
        and position.days_held <= cfg.early_profit_target_days
    ):
        return ExitDecision("close", "early_profit_target")
    if profit_pct >= cfg.core_profit_target_pct:
        return ExitDecision("close", "profit_target")

    loss = position.current_debit - position.entry_price
    credit_stop = position.entry_price * cfg.core_stop_loss_multiple
    max_loss_stop = position.max_loss * 0.85
    if loss >= min(credit_stop, max_loss_stop):
        return ExitDecision("close", "stop_loss")

    if position.days_held >= cfg.max_holding_sessions:
        return ExitDecision("close", f"max_holding_sessions_{cfg.max_holding_sessions}")

    return ExitDecision("hold", "risk_rules_satisfied")


def evaluate_debit_exit(
    spread: DebitSpread,
    opened_at: date,
    as_of: date,
    current_debit: float,
    config: RiskConfig | None = None,
    *,
    expiration: date | None = None,
) -> ExitDecision:
    cfg = config or RiskConfig()
    position = ManagedPosition(
        OrderEnvelope(
            opened_at.isoformat(),
            spread.symbol,
            "buy_to_open",
            (),
            spread.sleeve,
            spread.debit,
        ),
        spread.debit,
        current_debit,
        spread.width,
        opened_at,
        as_of,
        expiration,
    )
    expiration_exit = _expiration_horizon(position, cfg)
    if expiration_exit:
        return expiration_exit

    if current_debit >= spread.debit * (1 + cfg.core_profit_target_pct):
        return ExitDecision("close", "debit_profit_target")
    if current_debit <= spread.debit * (1 - min(cfg.core_stop_loss_multiple, 1.0)):
        return ExitDecision("close", "debit_stop_loss")

    if position.days_held >= cfg.max_holding_sessions:
        return ExitDecision("close", f"max_holding_sessions_{cfg.max_holding_sessions}")

    return ExitDecision("hold", "risk_rules_satisfied")


def build_close_envelope(position: ManagedPosition, decision: ExitDecision) -> OrderEnvelope:
    legs = tuple(
        {
            **leg,
            "side": "sell" if leg.get("side") == "buy" else "buy",
            "position_intent": "sell_to_close"
            if leg.get("position_intent") == "buy_to_open"
            else "buy_to_close",
        }
        for leg in position.envelope.legs
    )
    action = "sell_to_close" if position.envelope.side == "buy_to_open" else "buy_to_close"
    return OrderEnvelope(
        position.as_of.isoformat(),
        position.envelope.symbol,
        action,
        legs,
        position.envelope.sleeve,
        round(position.current_debit, 2),
        position.envelope.quantity,
    )


def _json(value, default):
    if isinstance(value, type(default)):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return default
        return parsed if isinstance(parsed, type(default)) else default
    return default


def manage_live_positions(
    client,
    options,
    *,
    positions: list[dict] | None = None,
    ledger=None,
    as_of: date | None = None,
    risk_config: RiskConfig | None = None,
) -> list[dict]:
    """Evaluate D1-backed spreads against the matching live broker legs."""
    day = as_of or datetime.now(UTC).date()
    cfg = risk_config or RiskConfig()
    durable_positions = positions or []
    broker_positions = {
        str(position.get("symbol") or ""): position
        for position in client.positions()
        if float(position.get("qty", 0) or 0)
        and str(position.get("asset_class", "")).lower() == "us_option"
    }
    if broker_positions and not durable_positions:
        raise RuntimeError(
            "active paper option positions require D1 entry metadata before exits can be evaluated"
        )
    open_orders = client.open_orders()
    records = []
    durable_symbols = set()
    for row in durable_positions:
        legs = _json(row.get("legs"), [])
        symbols = {str(leg.get("symbol") or "") for leg in legs}
        durable_symbols.update(symbols)
        if not symbols & broker_positions.keys():
            records.append(
                {
                    "kind": "position_management",
                    "category": "positions",
                    "position_id": row.get("id"),
                    "ticker": row.get("ticker"),
                    "status": "broker_closed",
                    "reason": "broker_position_closed",
                }
            )
            continue
        missing = symbols - broker_positions.keys()
        if missing:
            raise RuntimeError(
                f"D1 position {row.get('id')} is missing broker legs: {', '.join(sorted(missing))}"
            )
        refreshed_legs = []
        for leg in legs:
            broker_leg = broker_positions[str(leg["symbol"])]
            refreshed_legs.append(
                {**leg, "current_price": float(broker_leg.get("current_price") or 0)}
            )

        matching_open = [
            order
            for order in open_orders
            if symbols
            and symbols.issubset({str(leg.get("symbol") or "") for leg in order.get("legs") or []})
        ]
        metadata = _json(row.get("metadata"), {})
        close_order_id = metadata.get("close_broker_order_id")
        if close_order_id and not matching_open:
            close_order = client.order(str(close_order_id))
            if str(close_order.get("status") or "").lower() in {
                "canceled",
                "expired",
                "rejected",
                "failed",
            }:
                metadata = {
                    key: value for key, value in metadata.items() if not key.startswith("close_")
                }
                close_order_id = None
        if matching_open or close_order_id:
            records.append(
                {
                    "kind": "position_management",
                    "category": "positions",
                    "position_id": row.get("id"),
                    "ticker": row.get("ticker"),
                    "status": "pending_close",
                    "reason": "close_order_pending",
                    "legs": refreshed_legs,
                    "metadata": metadata,
                }
            )
            continue

        entry_debit = row.get("entry_debit")
        entry_credit = row.get("entry_credit")
        bought = next(leg for leg in refreshed_legs if leg.get("side") == "buy")
        sold = next(leg for leg in refreshed_legs if leg.get("side") == "sell")
        current_debit = max(
            0.01,
            round(
                float(bought["current_price"]) - float(sold["current_price"])
                if entry_debit is not None
                else float(sold["current_price"]) - float(bought["current_price"]),
                2,
            ),
        )
        original_side = "buy_to_open" if entry_debit is not None else "sell_to_open"
        envelope = OrderEnvelope(
            str(row.get("opened_at"))[:10],
            str(row["ticker"]),
            original_side,
            tuple(legs),
            str(row.get("sleeve") or "core"),
            float(entry_debit if entry_debit is not None else entry_credit),
            int(row.get("quantity") or 1),
        )
        managed = ManagedPosition(
            envelope,
            float(entry_debit if entry_debit is not None else entry_credit),
            current_debit,
            float(row["spread_width"]),
            date.fromisoformat(str(row["opened_at"])[:10]),
            day,
            date.fromisoformat(str(row["expiration"])[:10]),
        )
        if entry_debit is not None:
            spread = DebitSpread(
                str(row["ticker"]),
                float(row["long_strike"]),
                float(row["short_strike"]),
                float(entry_debit),
                int(row.get("quantity") or 1),
                str(row.get("sleeve") or "asymmetric"),
            )
            decision = evaluate_debit_exit(
                spread, managed.opened_at, day, current_debit, cfg, expiration=managed.expiration
            )
        else:
            decision = evaluate_credit_exit(managed, cfg)
        record = {
            "kind": "position_management",
            "category": "positions",
            "position_id": row.get("id"),
            "ticker": row.get("ticker"),
            "status": decision.action,
            "reason": decision.reason,
            "current_debit": current_debit,
            "legs": refreshed_legs,
            "metadata": metadata,
        }
        if decision.action == "close":
            response = client.submit_order(build_close_envelope(managed, decision).alpaca_payload())
            record.update(
                {
                    "status": "close_submitted",
                    "order_id": response["id"],
                    "client_order_id": response.get("client_order_id"),
                    "response": response,
                    "metadata": {
                        **metadata,
                        "close_reason": decision.reason,
                        "close_broker_order_id": response["id"],
                        "close_client_order_id": response.get("client_order_id"),
                    },
                }
            )
        records.append(record)
    unknown = set(broker_positions) - durable_symbols
    if unknown:
        raise RuntimeError(
            f"broker option legs are absent from D1 metadata: {', '.join(sorted(unknown))}"
        )
    return records
