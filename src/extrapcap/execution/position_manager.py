"""Position exits for short-horizon option spreads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..config import RiskConfig
from ..options import DebitSpread
from ..execution.orders import OrderEnvelope


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
    def max_loss(self) -> float:
        return max(0.01, self.spread_width - self.entry_price)

    @property
    def days_held(self) -> int:
        return max(0, (self.as_of - self.opened_at).days)


def _hard_horizon(position: ManagedPosition, cfg: RiskConfig) -> ExitDecision | None:
    if position.expiration is not None:
        dte = (position.expiration - position.as_of).days
        if dte < 0:
            return ExitDecision("close", "expired_position")
        if dte <= cfg.forced_exit_dte:
            return ExitDecision("close", f"forced_exit_dte_{dte}")
        if dte == 0 and position.opened_at == position.as_of:
            return ExitDecision("close", "zero_dte_session_exit")
    if position.days_held >= cfg.max_holding_sessions:
        return ExitDecision("close", f"max_holding_sessions_{cfg.max_holding_sessions}")
    return None


def evaluate_credit_exit(position: ManagedPosition, config: RiskConfig | None = None) -> ExitDecision:
    cfg = config or RiskConfig()
    hard = _hard_horizon(position, cfg)
    if hard:
        return hard
    if position.return_on_capital >= cfg.early_profit_target_pct and position.days_held <= cfg.early_profit_target_days:
        return ExitDecision("close", "early_profit_target")
    if position.return_on_capital >= cfg.core_profit_target_pct:
        return ExitDecision("close", "profit_target")
    if position.current_debit - position.entry_price >= position.max_loss * cfg.core_stop_loss_multiple:
        return ExitDecision("close", "stop_loss")
    return ExitDecision("hold", "risk_rules_satisfied")


def evaluate_debit_exit(spread: DebitSpread, opened_at: date, as_of: date, current_debit: float, config: RiskConfig | None = None, *, expiration: date | None = None) -> ExitDecision:
    cfg = config or RiskConfig()
    position = ManagedPosition(OrderEnvelope(opened_at.isoformat(), spread.symbol, "buy_to_open", tuple(), spread.sleeve, spread.debit), spread.debit, current_debit, spread.width, opened_at, as_of, expiration)
    hard = _hard_horizon(position, cfg)
    if hard:
        return hard
    if current_debit >= spread.debit * (1 + cfg.core_profit_target_pct):
        return ExitDecision("close", "debit_profit_target")
    if current_debit <= spread.debit * (1 - min(cfg.core_stop_loss_multiple, 1.0)):
        return ExitDecision("close", "debit_stop_loss")
    return ExitDecision("hold", "risk_rules_satisfied")


def build_close_envelope(position: ManagedPosition, decision: ExitDecision) -> OrderEnvelope:
    legs = tuple({**leg, "side": "sell" if leg.get("side") == "buy" else "buy", "position_intent": "sell_to_close" if leg.get("position_intent") == "buy_to_open" else "buy_to_close"} for leg in position.envelope.legs)
    action = "sell_to_close" if position.envelope.side == "buy_to_open" else "buy_to_close"
    return OrderEnvelope(position.as_of.isoformat(), position.envelope.symbol, action, legs, position.envelope.sleeve, round(position.current_debit, 2), position.envelope.quantity)


def manage_live_positions(client, options, *, ledger=None, as_of: date | None = None, risk_config: RiskConfig | None = None) -> list[dict]:
    """Manage only positions with broker-linked entry metadata; never invent it."""
    day = as_of or date.today()
    positions = client.positions()
    if any(float(position.get("qty", 0) or 0) and str(position.get("asset_class", "")).lower() == "us_option" for position in positions):
        raise RuntimeError("active paper option positions require D1 entry metadata before exits can be evaluated")
    return []
