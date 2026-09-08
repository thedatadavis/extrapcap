"""Synchronize broker order/fill state into the durable execution ledger."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from ..options_data import parse_occ_option_symbol

TERMINAL_ORDER_STATUSES = {"filled", "canceled", "expired", "rejected", "failed", "replaced"}


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


def _entry_position(
    order: dict, broker_order: dict, broker_positions: dict[str, dict]
) -> dict | None:
    if str(broker_order.get("status") or "").lower() != "filled":
        return None
    configured_legs = _json(order.get("legs"), [])
    filled_legs = {str(leg.get("symbol") or ""): leg for leg in broker_order.get("legs") or []}
    symbols = [str(leg.get("symbol") or "") for leg in configured_legs]
    if len(symbols) < 2 or any(symbol not in broker_positions for symbol in symbols):
        return None

    legs = []
    for configured in configured_legs:
        symbol = str(configured["symbol"])
        parsed = parse_occ_option_symbol(symbol)
        fill = filled_legs.get(symbol, {})
        broker_position = broker_positions[symbol]
        legs.append(
            {
                **configured,
                "type": parsed.option_type,
                "strike": parsed.strike,
                "expiration": parsed.expiration.isoformat(),
                "qty": int(float(configured.get("ratio_qty") or 1)),
                "entry_price": float(fill.get("filled_avg_price") or 0),
                "current_price": float(broker_position.get("current_price") or 0),
            }
        )

    bought = next((leg for leg in legs if leg.get("side") == "buy"), None)
    sold = next((leg for leg in legs if leg.get("side") == "sell"), None)
    if not bought or not sold:
        raise RuntimeError(
            f"filled order {order.get('client_order_id')} does not contain a vertical spread"
        )
    metadata = _json(order.get("metadata"), {})
    entry_price = float(broker_order.get("filled_avg_price") or order.get("limit_price") or 0)
    side = str(order.get("side") or "")
    return {
        "ticker": str(order["ticker"]).upper(),
        "short_symbol": sold["symbol"],
        "long_symbol": bought["symbol"],
        "short_strike": sold["strike"],
        "long_strike": bought["strike"],
        "expiration": bought["expiration"],
        "spread_width": abs(float(bought["strike"]) - float(sold["strike"])),
        "entry_credit": entry_price if side == "sell_to_open" else None,
        "entry_debit": entry_price if side == "buy_to_open" else None,
        "opened_at": str(broker_order.get("filled_at") or broker_order.get("submitted_at"))[:10],
        "sleeve": order.get("sleeve") or "core",
        "strategy_variant": order.get("strategy_variant") or "core_mean_reversion",
        "strategy_route": metadata.get("selection_context", {}).get("strategy_route"),
        "quantity": int(float(broker_order.get("filled_qty") or order.get("quantity") or 1)),
        "legs": legs,
        "selection_metrics": metadata.get("selection_context") or {},
        "metadata": {
            **metadata,
            "entry_client_order_id": order["client_order_id"],
            "entry_broker_order_id": broker_order.get("id"),
        },
    }


def synchronize_broker_state(
    client, store, *, run_id: str | None = None, now: datetime | None = None
) -> dict:
    """Update known D1 orders and materialize filled spreads as active positions."""
    observed_at = now or datetime.now(UTC)
    broker_orders = client.orders_after(observed_at - timedelta(days=30))
    by_client_id = {str(order.get("client_order_id") or ""): order for order in broker_orders}
    broker_positions = {
        str(position.get("symbol") or ""): position for position in client.positions()
    }
    active_positions = store.get_active_positions()
    active_entry_ids = set()
    closed = 0
    for position in active_positions:
        metadata = _json(position.get("metadata"), {})
        if metadata.get("entry_client_order_id"):
            active_entry_ids.add(metadata["entry_client_order_id"])
        legs = _json(position.get("legs"), [])
        symbols = {str(leg.get("symbol") or "") for leg in legs}
        if symbols and not symbols.intersection(broker_positions):
            store.close_position(
                int(position["id"]),
                str(metadata.get("close_reason") or "broker_position_closed"),
                run_id=run_id,
            )
            closed += 1

    updated = 0
    created = 0
    for order in store.get_orders():
        client_order_id = str(order.get("client_order_id") or "")
        broker_order = by_client_id.get(client_order_id)
        if not broker_order:
            continue
        status = str(broker_order.get("status") or "unknown").lower()
        store.update_order(
            client_order_id,
            status,
            broker_order_id=str(broker_order.get("id") or "") or None,
            filled_at=broker_order.get("filled_at"),
        )
        updated += 1
        if client_order_id in active_entry_ids:
            continue
        position = _entry_position(order, broker_order, broker_positions)
        if position:
            store.create_position(position, run_id=run_id)
            active_entry_ids.add(client_order_id)
            created += 1

    return {
        "orders_observed": len(broker_orders),
        "orders_updated": updated,
        "positions_created": created,
        "positions_closed": closed,
        "broker_positions": len(broker_positions),
        "broker_open_orders": len(client.open_orders()),
    }
