from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..config import RiskConfig
from ..options import DebitSpread
from ..risk import asymmetric_exit_reason
from .orders import OrderEnvelope


@dataclass(frozen=True)
class ManagedPosition:
    envelope: OrderEnvelope
    entry_credit: float
    current_debit: float
    spread_width: float
    opened_at: date
    as_of: date


@dataclass(frozen=True)
class ExitDecision:
    action: str
    reason: str
    target_debit: float | None = None
    held_days: int = 0


def evaluate_credit_exit(position: ManagedPosition, cfg: RiskConfig) -> ExitDecision:
    """Evaluate a defined-risk credit vertical using only current mark data."""
    if position.entry_credit <= 0 or position.spread_width <= 0:
        return ExitDecision("veto", "invalid_position_terms")
    if position.current_debit < 0:
        return ExitDecision("veto", "invalid_negative_mark")
    held_days = max(0, (position.as_of - position.opened_at).days)
    target_debit = position.entry_credit * (1 - cfg.core_profit_target_pct)
    stop_debit = min(position.spread_width * 0.99, position.entry_credit * cfg.core_stop_loss_multiple)
    if position.current_debit <= target_debit:
        return ExitDecision("close", "profit_target", target_debit, held_days)
    if position.current_debit >= stop_debit:
        return ExitDecision("close", "stop_loss", target_debit, held_days)
    if held_days >= cfg.core_time_stop_days:
        return ExitDecision("close", "time_stop", target_debit, held_days)
    return ExitDecision("hold", "within_exit_envelope", target_debit, held_days)


def build_close_envelope(position: ManagedPosition, decision: ExitDecision) -> OrderEnvelope:
    if decision.action != "close":
        raise ValueError("a close envelope requires a close decision")
    legs = []
    for leg in position.envelope.legs:
        opened_side = leg.get("side")
        if opened_side not in {"buy", "sell"}:
            raise ValueError("open order leg has no valid side")
        legs.append(
            {
                **leg,
                "side": "buy" if opened_side == "sell" else "sell",
                "position_intent": "buy_to_close" if opened_side == "sell" else "sell_to_close",
            }
        )
    return OrderEnvelope(
        trading_day=position.as_of.isoformat(),
        symbol=position.envelope.symbol,
        side="buy_to_close",
        legs=tuple(legs),
        sleeve=position.envelope.sleeve,
        limit_price=position.current_debit,
        quantity=position.envelope.quantity,
    )


def evaluate_debit_exit(
    spread: DebitSpread,
    opened_at: date,
    as_of: date,
    current_debit: float,
    cfg: RiskConfig,
) -> ExitDecision:
    held_days = max(0, (as_of - opened_at).days)
    reason = asymmetric_exit_reason(spread, held_days, current_debit, cfg)
    if reason:
        return ExitDecision("close", reason, current_debit, held_days)
    return ExitDecision("hold", "within_asymmetric_exit_envelope", current_debit, held_days)
