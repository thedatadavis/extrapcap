from __future__ import annotations

from datetime import date
import json
from pathlib import Path

from ..config import RiskConfig
from ..ledger import AuditLedger
from ..options_data import AlpacaOptionsData, normalize_chain, parse_occ_option_symbol
from ..options import DebitSpread
from .orders import OrderEnvelope
from .position_manager import ManagedPosition, build_close_envelope, evaluate_credit_exit, evaluate_debit_exit


def _read_registry(path: str | Path) -> list[dict]:
    target = Path(path)
    if not target.exists():
        return []
    rows = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def manage_live_positions(
    client,
    options: AlpacaOptionsData,
    *,
    registry_path: str | Path = "logs/orders/ids.jsonl",
    ledger: AuditLedger | None = None,
    as_of: date | None = None,
    risk_config: RiskConfig | None = None,
) -> list[dict]:
    """Mark registry-backed held verticals and submit only hard-rule exits."""
    as_of = as_of or date.today()
    cfg = risk_config or RiskConfig()
    ledger = ledger or AuditLedger()
    if hasattr(client, "clock"):
        clock = client.clock()
        if not isinstance(clock, dict) or not isinstance(clock.get("is_open"), bool):
            raise RuntimeError("broker market clock returned an invalid response")
        if not clock["is_open"]:
            result = {"status": "skipped", "reason": "broker market clock closed"}
            ledger.append("risk", result, as_of)
            return [result]
    held = {
        str(position.get("symbol", "")).upper()
        for position in client.positions()
        if float(position.get("qty", 0) or 0) != 0
    }
    records = _read_registry(registry_path)
    results = []
    for record in records:
        payload = record.get("payload", {})
        legs = tuple(payload.get("legs", []))
        if len(legs) != 2 or not all(str(leg.get("symbol", "")).upper() in held for leg in legs):
            continue
        if {leg.get("side") for leg in legs} != {"buy", "sell"}:
            continue
        try:
            parsed = [parse_occ_option_symbol(leg["symbol"]) for leg in legs]
            if parsed[0].underlying != parsed[1].underlying or parsed[0].option_type != "P" or parsed[1].option_type != "P":
                continue
            if parsed[0].expiration != parsed[1].expiration:
                continue
            short = next(item for item, leg in zip(parsed, legs) if leg.get("side") == "sell")
            long = next(item for item, leg in zip(parsed, legs) if leg.get("side") == "buy")
            if long.strike >= short.strike:
                continue
        except (KeyError, StopIteration, ValueError):
            continue
        metadata = record.get("metadata", {})
        position_metadata = {
            "ticker": parsed[0].underlying,
            "underlying": parsed[0].underlying,
            "contract_ids": [short.symbol, long.symbol],
            "contracts": [
                {
                    "contract_id": short.symbol,
                    "ticker": short.underlying,
                    "expiration": short.expiration.isoformat(),
                    "strike": short.strike,
                    "option_type": "put",
                    "role": "short",
                },
                {
                    "contract_id": long.symbol,
                    "ticker": long.underlying,
                    "expiration": long.expiration.isoformat(),
                    "strike": long.strike,
                    "option_type": "put",
                    "role": "long",
                },
            ],
            "sleeve": payload.get("sleeve", "core"),
            "strategy_variant": metadata.get("strategy_variant"),
        }
        snapshot_payload, tier = options.chain_all(
            parsed[0].underlying,
            expiration_gte=parsed[0].expiration.isoformat(),
            expiration_lte=parsed[0].expiration.isoformat(),
            option_type="put",
            feed="indicative",
        )
        quotes = {quote.symbol: quote for quote in normalize_chain(snapshot_payload)}
        short_quote, long_quote = quotes.get(short.symbol), quotes.get(long.symbol)
        if not short_quote or not long_quote or short_quote.ask is None or long_quote.bid is None:
            result = {
                "client_order_id": record.get("client_order_id"),
                **position_metadata,
                "status": "skipped",
                "reason": "incomplete_indicative_quote",
                "data_tier": tier.value,
            }
            results.append(result)
            ledger.append("risk", result, as_of)
            continue
        opened_at_value = metadata.get("opened_at")
        if not opened_at_value:
            result = {
                "client_order_id": record.get("client_order_id"),
                **position_metadata,
                "status": "skipped",
                "reason": "missing_entry_metadata",
                "data_tier": tier.value,
            }
            results.append(result)
            ledger.append("risk", result, as_of)
            continue
        opened_at = date.fromisoformat(opened_at_value)
        entry_debit = metadata.get("entry_debit")
        if entry_debit is not None:
            current_debit = long_quote.bid - short_quote.ask
            if current_debit < 0:
                result = {"client_order_id": record.get("client_order_id"), **position_metadata, "status": "skipped", "reason": "invalid_negative_mark", "data_tier": tier.value}
                results.append(result)
                ledger.append("risk", result, as_of)
                continue
            spread = DebitSpread(parsed[0].underlying, long.strike, short.strike, float(entry_debit), sleeve="asymmetric", direction="bearish")
            decision = evaluate_debit_exit(spread, opened_at, as_of, current_debit, cfg)
            result = {
                "client_order_id": record.get("client_order_id"),
                **position_metadata,
                "status": decision.action,
                "reason": decision.reason,
                "current_debit": current_debit,
                "data_tier": tier.value,
            }
            if decision.action == "close":
                close_order = build_close_envelope(
                    ManagedPosition(
                        OrderEnvelope(opened_at.isoformat(), parsed[0].underlying, "buy_to_open", legs, "asymmetric", payload.get("limit_price"), int(payload.get("qty", 1))),
                        float(entry_debit),
                        current_debit,
                        float(metadata.get("spread_width", abs(long.strike - short.strike))),
                        opened_at,
                        as_of,
                    ),
                    decision,
                )
                result["order"] = close_order.alpaca_payload()
                result["provider_response"] = client.submit_order(result["order"])
                ledger.append("orders", result, as_of)
            else:
                ledger.append("signals", result, as_of)
            results.append(result)
            continue
        current_debit = short_quote.ask - long_quote.bid
        if metadata.get("entry_credit") is None:
            result = {
                "client_order_id": record.get("client_order_id"),
                **position_metadata,
                "status": "skipped",
                "reason": "missing_entry_metadata",
                "data_tier": tier.value,
            }
            results.append(result)
            ledger.append("risk", result, as_of)
            continue
        position = ManagedPosition(
            OrderEnvelope(
                opened_at.isoformat(),
                parsed[0].underlying,
                "sell_to_open",
                legs,
                payload.get("sleeve", "core"),
                payload.get("limit_price"),
                int(payload.get("qty", 1)),
            ),
            float(metadata.get("entry_credit", payload.get("limit_price", 0))),
            current_debit,
            float(metadata.get("spread_width", short.strike - long.strike)),
            opened_at,
            as_of,
        )
        decision = evaluate_credit_exit(position, cfg)
        result = {
            "client_order_id": record.get("client_order_id"),
            **position_metadata,
            "status": decision.action,
            "reason": decision.reason,
            "current_debit": current_debit,
            "data_tier": tier.value,
        }
        if decision.action == "close":
            close_order = build_close_envelope(position, decision)
            result["order"] = close_order.alpaca_payload()
            result["provider_response"] = client.submit_order(result["order"])
            ledger.append("orders", result, as_of)
        else:
            ledger.append("signals", result, as_of)
        results.append(result)
    return results
