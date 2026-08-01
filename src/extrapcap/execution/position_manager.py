"""Position tracking and paper order exit execution engine."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import os

from ..config import RiskConfig
from ..execution.alpaca import AlpacaPaperClient
from ..ledger import AuditLedger
from ..options_data import AlpacaOptionsData, normalize_chain, parse_occ_option_symbol
from ..options import CreditSpread, DebitSpread
from .orders import OrderEnvelope


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

    @property
    def return_on_capital(self) -> float:
        capital = max(0.01, self.spread_width - self.entry_price)
        profit = self.entry_price - self.current_debit
        return profit / capital

    @property
    def max_loss(self) -> float:
        return max(0.01, self.spread_width - self.entry_price)

    @property
    def loss_amount(self) -> float:
        return max(0.0, self.current_debit - self.entry_price)

    @property
    def days_held(self) -> int:
        return max(0, (self.as_of - self.opened_at).days)


def evaluate_credit_exit(
    position: ManagedPosition,
    config: RiskConfig | None = None,
) -> ExitDecision:
    """Evaluate hard rules and mean-reversal heuristics for credit spread exit."""
    cfg = config or RiskConfig()
    profit_target = getattr(cfg, "profit_target_pct", getattr(cfg, "core_profit_target_pct", 0.5))
    early_profit_target = getattr(cfg, "early_profit_target_pct", 0.35)
    early_profit_days = getattr(cfg, "early_profit_target_days", 2)
    stop_loss_mult = getattr(cfg, "stop_loss_multiplier", getattr(cfg, "core_stop_loss_multiple", 2.0))
    max_days = getattr(cfg, "max_holding_days", getattr(cfg, "core_time_stop_days", 4))

    # 1. 35% Early profit capture within first 48h (capital velocity rule)
    if position.days_held <= early_profit_days and position.return_on_capital >= early_profit_target:
        return ExitDecision("close", f"early_profit_target_{int(early_profit_target * 100)}pct_{early_profit_days}d")

    # 2. Standard 50% max profit target
    if position.return_on_capital >= profit_target:
        return ExitDecision("close", f"profit_target_{int(profit_target * 100)}pct")

    # 3. Z-Score & Streak Reversal Signal Exit
    selection_context = getattr(position.envelope, "selection_context", None) or {}
    robust_z = selection_context.get("current_robust_z") or selection_context.get("robust_z")
    streak_dir = selection_context.get("current_streak_direction") or selection_context.get("streak_direction")
    entry_dir = selection_context.get("entry_streak_direction") or selection_context.get("streak_direction")
    if robust_z is not None and abs(float(robust_z)) < 0.5 and streak_dir and entry_dir and streak_dir != entry_dir:
        return ExitDecision("close", "zscore_streak_reversal_exit")

    # 4. Stop loss
    if position.loss_amount >= position.max_loss * stop_loss_mult:
        return ExitDecision("close", f"stop_loss_{stop_loss_mult}x_max_loss")

    # 5. 4-day time stop (empirical mean-reversal window)
    if position.days_held >= max_days:
        return ExitDecision("close", f"max_holding_{max_days}d")

    return ExitDecision("hold", "risk_rules_satisfied")


def evaluate_debit_exit(
    spread: DebitSpread,
    opened_at: date,
    as_of: date,
    current_debit: float,
    config: RiskConfig | None = None,
) -> ExitDecision:
    """Evaluate hard rules for debit spread exit."""
    cfg = config or RiskConfig()
    profit_target = getattr(cfg, "profit_target_pct", getattr(cfg, "core_profit_target_pct", 0.5))
    stop_loss_mult = getattr(cfg, "stop_loss_multiplier", getattr(cfg, "core_stop_loss_multiple", 2.0))
    max_days = getattr(cfg, "max_holding_days", getattr(cfg, "core_time_stop_days", 4))

    days_held = max(0, (as_of - opened_at).days)
    if days_held >= max_days:
        return ExitDecision("close", f"max_holding_{max_days}d")
    profit = current_debit - spread.debit
    if profit >= spread.debit * profit_target:
        return ExitDecision("close", f"debit_profit_target_{int(profit_target * 100)}pct")
    if current_debit <= spread.debit * (1.0 - stop_loss_mult):
        return ExitDecision("close", f"debit_stop_loss_{stop_loss_mult}x")
    return ExitDecision("hold", "risk_rules_satisfied")


def evaluate_fast_ev_exit(
    *,
    entry_cost: float,
    current_value: float,
    spread_width: float,
    is_debit: bool,
    opened_at: date,
    as_of: date,
    dte: int,
) -> ExitDecision:
    """Empirically-calibrated Fast EV Exit Heuristic."""
    days_held = max(0, (as_of - opened_at).days)
    if is_debit:
        profit = current_value - entry_cost
        max_profit = max(0.01, spread_width - entry_cost)
        if max_profit > 0 and (profit / max_profit) >= 0.50:
            return ExitDecision("close", "fast_ev_50pct_max_profit")
        if entry_cost > 0 and (current_value / entry_cost) <= 0.50:
            return ExitDecision("close", "fast_ev_50pct_stop_loss")
        if dte <= 2 or days_held >= 4:
            return ExitDecision("close", f"fast_ev_time_exit_dte{dte}_held{days_held}d")
    else:
        max_profit = max(0.01, entry_cost)
        profit = entry_cost - current_value
        # Early 35% profit capture within 48h
        if days_held <= 2 and max_profit > 0 and (profit / max_profit) >= 0.35:
            return ExitDecision("close", "fast_ev_35pct_early_profit_2d")
        if max_profit > 0 and (profit / max_profit) >= 0.50:
            return ExitDecision("close", "fast_ev_50pct_max_profit")
        max_loss = max(0.01, spread_width - entry_cost)
        if max_loss > 0 and (current_value - entry_cost) >= max_loss * 0.50:
            return ExitDecision("close", "fast_ev_50pct_max_loss_stop")
        if dte <= 2 or days_held >= 4:
            return ExitDecision("close", f"fast_ev_time_exit_dte{dte}_held{days_held}d")
    return ExitDecision("hold", "fast_ev_rules_satisfied")


def build_close_envelope(position: ManagedPosition, decision: ExitDecision) -> OrderEnvelope:
    """Construct closing envelope using opposite legs."""
    legs = []
    for leg in position.envelope.legs:
        opposite_side = "sell" if leg.get("side") == "buy" else "buy"
        opposite_intent = "sell_to_close" if leg.get("position_intent") == "buy_to_open" else "buy_to_close"
        legs.append({
            **leg,
            "side": opposite_side,
            "position_intent": opposite_intent,
        })
    side_val = getattr(position.envelope, "side", "buy_to_open")
    action = "sell_to_close" if side_val == "buy_to_open" else "buy_to_close"
    return OrderEnvelope(
        trading_day=position.as_of.isoformat(),
        symbol=position.envelope.symbol,
        side=action,
        legs=tuple(legs),
        sleeve=position.envelope.sleeve,
        limit_price=position.current_debit,
        quantity=getattr(position.envelope, "quantity", 1),
    )


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
    """Mark registry-backed held verticals and submit exit paper orders when hard rules trigger."""
    as_of = as_of or date.today()
    cfg = risk_config or RiskConfig()
    ledger = ledger or AuditLedger()
    if hasattr(client, "clock"):
        clock = client.clock()
        if isinstance(clock, dict) and isinstance(clock.get("is_open"), bool) and not clock["is_open"]:
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
        dte = max(0, (parsed[0].expiration - as_of).days)
        is_fast_ev_pos = metadata.get("strategy_variant") == "fast_ev" or os.getenv("EXTRAPCAP_FAST_EV", "false").lower() == "true"
        if entry_debit is not None:
            current_debit = long_quote.bid - short_quote.ask
            if current_debit < 0:
                result = {"client_order_id": record.get("client_order_id"), **position_metadata, "status": "skipped", "reason": "invalid_negative_mark", "data_tier": tier.value}
                results.append(result)
                ledger.append("risk", result, as_of)
                continue
            spread_width = float(metadata.get("spread_width", abs(long.strike - short.strike)))
            if is_fast_ev_pos:
                decision = evaluate_fast_ev_exit(
                    entry_cost=float(entry_debit),
                    current_value=current_debit,
                    spread_width=spread_width,
                    is_debit=True,
                    opened_at=opened_at,
                    as_of=as_of,
                    dte=dte,
                )
            else:
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
                        spread_width,
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
        spread_width = float(metadata.get("spread_width", short.strike - long.strike))
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
            spread_width,
            opened_at,
            as_of,
        )
        if is_fast_ev_pos:
            decision = evaluate_fast_ev_exit(
                entry_cost=float(metadata.get("entry_credit", payload.get("limit_price", 0))),
                current_value=current_debit,
                spread_width=spread_width,
                is_debit=False,
                opened_at=opened_at,
                as_of=as_of,
                dte=dte,
            )
        else:
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate open option positions for deterministic exits")
    parser.add_argument("--as-of", default=date.today().isoformat(), help="As-of date YYYY-MM-DD")
    args = parser.parse_args()

    client = AlpacaPaperClient.from_env()
    options = AlpacaOptionsData.from_env()
    results = manage_live_positions(client, options, as_of=date.fromisoformat(args.as_of))
    print(json.dumps({"as_of": args.as_of, "results": results}, indent=2))


if __name__ == "__main__":
    main()
