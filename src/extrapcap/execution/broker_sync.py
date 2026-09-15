"""Synchronize broker order/fill state into the durable execution ledger."""

from __future__ import annotations

import json
import os
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
        leg_entry = float(fill.get("filled_avg_price") or broker_position.get("avg_entry_price") or 0)
        legs.append(
            {
                **configured,
                "asset_class": "us_option",
                "type": "put" if parsed.option_type == "P" else "call",
                "strike": parsed.strike,
                "expiration": parsed.expiration.isoformat(),
                "qty": int(float(configured.get("ratio_qty") or 1)),
                "entry_price": abs(leg_entry),
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
    entry_price = abs(float(broker_order.get("filled_avg_price") or order.get("limit_price") or 0))
    side = str(order.get("side") or "").lower()
    is_put = str(sold.get("type") or "").lower() == "put"
    if side in {"sell_to_open", "sell"}:
        is_credit = True
    elif side in {"buy_to_open", "buy"}:
        is_credit = False
    else:
        # Infer credit vs debit from strike geometry if side was omitted by broker
        is_credit = (is_put and float(sold["strike"]) > float(bought["strike"])) or (
            not is_put and float(sold["strike"]) < float(bought["strike"])
        )

    # If entry_price was not captured at top-level order, calculate from leg entry prices
    if entry_price <= 0:
        s_entry = float(sold.get("entry_price") or 0)
        b_entry = float(bought.get("entry_price") or 0)
        entry_price = max(0.01, abs(round(s_entry - b_entry if is_credit else b_entry - s_entry, 2)))

    phase = str(metadata.get("phase") or os.getenv("TRADING_PHASE", os.getenv("EXTRAPCAP_PHASE", "testing"))).lower()
    return {
        "ticker": str(order["ticker"]).upper(),
        "short_symbol": sold["symbol"],
        "long_symbol": bought["symbol"],
        "short_strike": sold["strike"],
        "long_strike": bought["strike"],
        "expiration": bought["expiration"],
        "spread_width": abs(float(bought["strike"]) - float(sold["strike"])),
        "entry_credit": entry_price if is_credit else None,
        "entry_debit": entry_price if not is_credit else None,
        "opened_at": str(broker_order.get("filled_at") or broker_order.get("submitted_at"))[:10],
        "sleeve": order.get("sleeve") or "core",
        "strategy_variant": order.get("strategy_variant") or "core_mean_reversion",
        "strategy_route": metadata.get("selection_context", {}).get("strategy_route"),
        "quantity": int(float(broker_order.get("filled_qty") or order.get("quantity") or 1)),
        "legs": legs,
        "selection_metrics": metadata.get("selection_context") or {},
        "metadata": {
            **metadata,
            "phase": phase,
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
    covered_symbols = set()
    closed = 0
    for position in active_positions:
        metadata = _json(position.get("metadata"), {})
        if metadata.get("entry_client_order_id"):
            active_entry_ids.add(metadata["entry_client_order_id"])
        for leg in _json(position.get("legs"), []):
            if leg.get("symbol"):
                covered_symbols.add(str(leg["symbol"]))

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
            try:
                store.create_position(position, run_id=run_id)
                active_entry_ids.add(client_order_id)
                for leg in position.get("legs") or []:
                    if leg.get("symbol"):
                        covered_symbols.add(str(leg["symbol"]))
                created += 1
            except Exception as exc:
                print(f"Warning: could not create position for order {client_order_id}: {exc}")

    # Reconcile any open broker option legs not yet covered by active positions
    # (e.g. from orders submitted during price-walk fallbacks or out-of-band fills)
    uncovered_legs = set(broker_positions.keys()) - covered_symbols
    if uncovered_legs:
        filled_broker_orders = [
            bo
            for bo in broker_orders
            if str(bo.get("status") or "").lower() == "filled" and (bo.get("legs") or [])
        ]
        all_d1_orders = store.get_orders()
        for bo in filled_broker_orders:
            bo_legs = {str(l.get("symbol") or "") for l in bo.get("legs") or []}
            if bo_legs and bo_legs.issubset(uncovered_legs):
                matching_d1_order = next(
                    (
                        d1_o
                        for d1_o in all_d1_orders
                        if {str(l.get("symbol") or "") for l in _json(d1_o.get("legs"), [])} == bo_legs
                    ),
                    None,
                )
                order_to_use = dict(matching_d1_order) if matching_d1_order else {}
                order_to_use["client_order_id"] = str(
                    bo.get("client_order_id") or order_to_use.get("client_order_id") or ""
                )
                order_to_use["broker_order_id"] = str(bo.get("id") or "")
                if not order_to_use.get("ticker") and bo_legs:
                    order_to_use["ticker"] = parse_occ_option_symbol(next(iter(bo_legs))).underlying
                if not order_to_use.get("legs"):
                    order_to_use["legs"] = [
                        {
                            "symbol": str(l.get("symbol")),
                            "asset_class": "us_option",
                            "side": str(l.get("side")),
                            "position_intent": str(
                                l.get("position_intent")
                                or ("sell_to_open" if l.get("side") == "sell" else "buy_to_open")
                            ),
                            "ratio_qty": int(float(l.get("ratio_qty") or 1)),
                        }
                        for l in bo.get("legs") or []
                    ]
                if not order_to_use.get("side"):
                    sold_leg = next((l for l in bo.get("legs") or [] if str(l.get("side")).lower() == "sell"), None)
                    bought_leg = next((l for l in bo.get("legs") or [] if str(l.get("side")).lower() == "buy"), None)
                    if sold_leg and bought_leg:
                        try:
                            s_parsed = parse_occ_option_symbol(str(sold_leg.get("symbol") or ""))
                            b_parsed = parse_occ_option_symbol(str(bought_leg.get("symbol") or ""))
                            is_put = s_parsed.option_type == "P"
                            is_credit = (is_put and s_parsed.strike > b_parsed.strike) or (not is_put and s_parsed.strike < b_parsed.strike)
                            order_to_use["side"] = "sell_to_open" if is_credit else "buy_to_open"
                        except Exception:
                            order_to_use["side"] = "sell_to_open"
                pos = _entry_position(order_to_use, bo, broker_positions)
                if pos:
                    try:
                        store.create_position(pos, run_id=run_id)
                        uncovered_legs -= bo_legs
                        created += 1
                    except Exception as exc:
                        print(f"Warning: could not create position for reconciled order {order_to_use.get('client_order_id')}: {exc}")

    # Auto-adopt remaining uncovered broker legs into synthetic spreads.
    # If the broker holds matching long and short option legs on the same underlying and expiration,
    # auto-adopt them into D1 so position management can monitor profit-targets and stop-losses.
    if uncovered_legs:
        grouped: dict[tuple[str, str, str], list[dict]] = {}
        for sym in list(uncovered_legs):
            bp = broker_positions.get(sym)
            if not bp:
                continue
            try:
                parsed = parse_occ_option_symbol(sym)
            except Exception:
                continue
            key = (parsed.underlying, parsed.expiration.isoformat(), parsed.option_type)
            raw_qty = float(bp.get("qty") or 0)
            if raw_qty == 0:
                continue
            grouped.setdefault(key, []).append(
                {
                    "symbol": sym,
                    "parsed": parsed,
                    "broker_pos": bp,
                    "qty": raw_qty,
                    "avg_entry_price": abs(float(bp.get("avg_entry_price") or 0)),
                    "current_price": float(bp.get("current_price") or 0),
                }
            )

        for (underlying, expiration, opt_type), candidate_legs in grouped.items():
            short_candidates = [l for l in candidate_legs if l["qty"] < 0]
            long_candidates = [l for l in candidate_legs if l["qty"] > 0]
            while short_candidates and long_candidates:
                s_leg = short_candidates.pop(0)
                l_leg = long_candidates.pop(0)
                qty = min(abs(s_leg["qty"]), abs(l_leg["qty"]))
                if qty <= 0:
                    continue

                short_strike = s_leg["parsed"].strike
                long_strike = l_leg["parsed"].strike
                width = abs(short_strike - long_strike)

                is_credit = (opt_type == "P" and short_strike > long_strike) or (
                    opt_type == "C" and short_strike < long_strike
                )

                net_entry = (
                    s_leg["avg_entry_price"] - l_leg["avg_entry_price"]
                    if is_credit
                    else l_leg["avg_entry_price"] - s_leg["avg_entry_price"]
                )
                net_price = max(0.01, round(abs(net_entry), 2))

                pos_legs = [
                    {
                        "symbol": s_leg["symbol"],
                        "asset_class": "us_option",
                        "side": "sell",
                        "position_intent": "sell_to_open",
                        "type": "put" if opt_type == "P" else "call",
                        "strike": short_strike,
                        "expiration": expiration,
                        "qty": int(qty),
                        "entry_price": s_leg["avg_entry_price"],
                        "current_price": s_leg["current_price"],
                    },
                    {
                        "symbol": l_leg["symbol"],
                        "asset_class": "us_option",
                        "side": "buy",
                        "position_intent": "buy_to_open",
                        "type": "put" if opt_type == "P" else "call",
                        "strike": long_strike,
                        "expiration": expiration,
                        "qty": int(qty),
                        "entry_price": l_leg["avg_entry_price"],
                        "current_price": l_leg["current_price"],
                    },
                ]

                phase = os.getenv("TRADING_PHASE", os.getenv("EXTRAPCAP_PHASE", "testing")).lower()
                synth_pos = {
                    "ticker": underlying,
                    "short_symbol": s_leg["symbol"],
                    "long_symbol": l_leg["symbol"],
                    "short_strike": short_strike,
                    "long_strike": long_strike,
                    "expiration": expiration,
                    "spread_width": width,
                    "entry_credit": net_price if is_credit else None,
                    "entry_debit": net_price if not is_credit else None,
                    "opened_at": observed_at.strftime("%Y-%m-%d"),
                    "sleeve": "core",
                    "strategy_variant": "auto_adopted",
                    "quantity": int(qty),
                    "legs": pos_legs,
                    "selection_metrics": {},
                    "metadata": {
                        "phase": phase,
                        "source": "broker_auto_adopted",
                        "entry_client_order_id": f"auto-{s_leg['symbol'][:16]}",
                    },
                }
                try:
                    store.create_position(synth_pos, run_id=run_id)
                    uncovered_legs.discard(s_leg["symbol"])
                    uncovered_legs.discard(l_leg["symbol"])
                    covered_symbols.add(s_leg["symbol"])
                    covered_symbols.add(l_leg["symbol"])
                    created += 1
                except Exception as exc:
                    print(f"Warning: could not create auto-adopted position for {underlying}: {exc}")

    return {
        "orders_observed": len(broker_orders),
        "orders_updated": updated,
        "positions_created": created,
        "positions_closed": closed,
        "broker_positions": len(broker_positions),
        "broker_open_orders": len(client.open_orders()),
    }
