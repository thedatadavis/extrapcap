"""Position exits for short-horizon option spreads."""

from __future__ import annotations

import json
import math
import time
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
    short_strike: float | None = None
    long_strike: float | None = None
    underlying_price: float | None = None
    volatility: float | None = None
    rolling_mean: float | None = None
    option_type: str = "put"

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

    @property
    def dte(self) -> float:
        if self.expiration is None:
            return 0.0
        days = (self.expiration - self.as_of).days
        return max(0.0, float(days))

    @property
    def breakeven_price(self) -> float | None:
        if self.short_strike is None or self.entry_price <= 0:
            return None
        if str(self.option_type).lower() == "call":
            return round(self.short_strike + self.entry_price, 2)
        return round(self.short_strike - self.entry_price, 2)

    @property
    def required_move_pct(self) -> float:
        if self.underlying_price is None or self.breakeven_price is None or self.underlying_price <= 0:
            return 0.0
        if str(self.option_type).lower() == "call":
            if self.underlying_price > self.breakeven_price:
                return (self.underlying_price - self.breakeven_price) / self.underlying_price
            return 0.0
        else:
            if self.underlying_price < self.breakeven_price:
                return (self.breakeven_price - self.underlying_price) / self.underlying_price
            return 0.0

    @property
    def expected_move_pct(self) -> float:
        vol = self.volatility if self.volatility and self.volatility > 0 else 0.30
        eff_dte = max(0.5, self.dte)
        return float(vol * math.sqrt(eff_dte / 252.0))

    @property
    def feasibility_ratio(self) -> float:
        em = self.expected_move_pct
        if em <= 0:
            return 0.0
        return self.required_move_pct / em

    @property
    def distance_to_mean_pct(self) -> float | None:
        if self.underlying_price is None or self.rolling_mean is None or self.rolling_mean <= 0:
            return None
        return (self.underlying_price - self.rolling_mean) / self.rolling_mean

    @property
    def long_wing_breached(self) -> bool:
        if self.underlying_price is None or self.long_strike is None:
            return False
        if str(self.option_type).lower() == "call":
            return self.underlying_price >= self.long_strike
        return self.underlying_price <= self.long_strike


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


def _credit_expiration_horizon(position: ManagedPosition, cfg: RiskConfig) -> ExitDecision | None:
    """Evaluate expiration risk for credit spreads.

    If decay is in our favor (position is comfortably OTM and profitable),
    skip early forced liquidation and let the spread expire worthless (100% gain).
    Only force exit near expiration (0-1 DTE) if the short strike is threatened.
    """
    if position.expiration is not None:
        dte = (position.expiration - position.as_of).days
        if dte < 0:
            return ExitDecision("close", "expired_position")
        if dte == 0 and position.opened_at == position.as_of:
            return ExitDecision("close", "zero_dte_session_exit")
        # 0 or 1 DTE: if threatened (underwater or <50% credit captured), close to prevent assignment/pin risk
        if dte <= 1:
            if position.return_on_credit < 0.50:
                reason = "threatened_zero_dte" if dte == 0 else "threatened_expiration_risk"
                return ExitDecision("close", reason)
            # Comfortably OTM: let it run to expiration to capture full 100% credit without closing friction
            return None
        # 2 to forced_exit_dte (e.g. 3 DTE):
        if dte <= cfg.forced_exit_dte:
            # If decay is NOT in our favor (<25% credit captured or underwater), exit to avoid gamma
            if position.return_on_credit < 0.25:
                return ExitDecision("close", f"forced_exit_dte_{dte}")
            # If decay IS in our favor, let it run
            return None
    return None


def evaluate_credit_exit(
    position: ManagedPosition, config: RiskConfig | None = None
) -> ExitDecision:
    cfg = config or RiskConfig()
    expiration_exit = _credit_expiration_horizon(position, cfg)
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

    # 1. Structural barrier: Long protective wing breached
    if position.long_wing_breached:
        return ExitDecision("close", "long_wing_breached")

    # 2. Contextual Reversion Feasibility:
    # If required move to breakeven exceeds threshold * expected move,
    # recovery is statistically improbable given remaining DTE.
    if position.underlying_price is not None and position.feasibility_ratio > cfg.feasibility_em_threshold:
        return ExitDecision("close", f"feasibility_stop_exceeded_{position.feasibility_ratio:.2f}x")

    # 3. Catastrophic spread-width debit backstop:
    # If debit reaches 85% of spread width (nearing theoretical max loss), cut to preserve capital.
    catastrophic_cap = position.spread_width * cfg.catastrophic_debit_pct
    if position.current_debit >= catastrophic_cap:
        return ExitDecision("close", "catastrophic_debit_cap")

    # Credit spreads hold for theta decay; max_holding_sessions does not truncate winning credit spreads.
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
    market_data=None,
    stock_prices: dict[str, float] | None = None,
) -> list[dict]:
    """Evaluate D1-backed spreads against the matching live broker legs."""
    day = as_of or datetime.now(UTC).date()
    cfg = risk_config or RiskConfig()
    durable_positions = positions or []
    if stock_prices is None:
        tickers = list({str(p.get("ticker")).upper() for p in durable_positions if p.get("ticker")})
        if tickers:
            md = market_data
            if md is None:
                try:
                    from ..data.alpaca_market import AlpacaMarketData
                    md = AlpacaMarketData()
                except Exception:
                    md = None
            if md and hasattr(md, "stock_snapshots"):
                try:
                    stock_prices = md.stock_snapshots(tickers)
                except Exception:
                    stock_prices = {}
            else:
                stock_prices = {}
    else:
        stock_prices = dict(stock_prices)

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
        row_metadata = _json(row.get("metadata"), {})
        if not symbols & broker_positions.keys():
            close_order_id = row_metadata.get("close_broker_order_id")
            close_order = None
            if close_order_id and hasattr(client, "order"):
                try:
                    close_order = client.order(str(close_order_id))
                except Exception:
                    pass
            exit_price = None
            if close_order and str(close_order.get("status") or "").lower() == "filled":
                exit_price = abs(float(close_order.get("filled_avg_price") or 0))

            entry_credit = abs(float(row["entry_credit"])) if row.get("entry_credit") is not None else None
            entry_debit = abs(float(row["entry_debit"])) if row.get("entry_debit") is not None else None
            qty = int(row.get("quantity") or 1)
            realized_pnl = None
            if exit_price is not None:
                if entry_credit is not None:
                    realized_pnl = round((entry_credit - exit_price) * qty * 100, 2)
                elif entry_debit is not None:
                    realized_pnl = round((exit_price - entry_debit) * qty * 100, 2)

            reason = row_metadata.get("close_reason") or "broker_position_closed"
            records.append(
                {
                    "kind": "position_management",
                    "category": "positions",
                    "position_id": row.get("id"),
                    "ticker": row.get("ticker"),
                    "status": "broker_closed",
                    "reason": reason,
                    "metadata": row_metadata,
                    "entry_credit": entry_credit,
                    "entry_debit": entry_debit,
                    "exit_price": exit_price,
                    "realized_pnl": realized_pnl,
                    "quantity": qty,
                    "legs": legs,
                    "spread_width": row.get("spread_width"),
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

        entry_debit = abs(float(row["entry_debit"])) if row.get("entry_debit") is not None else None
        entry_credit = abs(float(row["entry_credit"])) if row.get("entry_credit") is not None else None
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
        entry_price = float(entry_debit if entry_debit is not None else entry_credit)
        selection_metrics = _json(row.get("selection_metrics"), {})
        row_ticker = str(row.get("ticker") or "").upper()
        spot_price = stock_prices.get(row_ticker) if stock_prices else None
        if spot_price is None and selection_metrics.get("underlying_price"):
            try:
                spot_price = float(selection_metrics["underlying_price"])
            except (ValueError, TypeError):
                pass

        short_strike = float(sold.get("strike") or row.get("short_strike") or 0) or None
        long_strike = float(bought.get("strike") or row.get("long_strike") or 0) or None
        opt_type = str(sold.get("type") or "put").lower()
        volatility = float(selection_metrics.get("volatility_context") or 0) or None
        rolling_mean = float(selection_metrics.get("rolling_mean") or 0) or None
        original_side = "buy_to_open" if entry_debit is not None else "sell_to_open"

        envelope = OrderEnvelope(
            str(row.get("opened_at"))[:10],
            str(row["ticker"]),
            original_side,
            tuple(legs),
            str(row.get("sleeve") or "core"),
            entry_price,
            int(row.get("quantity") or 1),
        )
        managed = ManagedPosition(
            envelope,
            entry_price,
            current_debit,
            float(row["spread_width"]),
            date.fromisoformat(str(row["opened_at"])[:10]),
            day,
            date.fromisoformat(str(row["expiration"])[:10]),
            short_strike=short_strike,
            long_strike=long_strike,
            underlying_price=spot_price,
            volatility=volatility,
            rolling_mean=rolling_mean,
            option_type=opt_type,
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

        feasibility_ctx = {
            "underlying_price": managed.underlying_price,
            "breakeven_price": managed.breakeven_price,
            "required_move_pct": round(managed.required_move_pct, 4) if managed.required_move_pct is not None else None,
            "expected_move_pct": round(managed.expected_move_pct, 4) if managed.expected_move_pct is not None else None,
            "feasibility_ratio": round(managed.feasibility_ratio, 3) if managed.feasibility_ratio is not None else None,
            "distance_to_mean_pct": round(managed.distance_to_mean_pct, 4) if managed.distance_to_mean_pct is not None else None,
            "long_wing_breached": managed.long_wing_breached,
            "dte": managed.dte,
        }
        metadata["feasibility_context"] = feasibility_ctx

        record = {
            "kind": "position_management",
            "category": "positions",
            "position_id": row.get("id"),
            "ticker": row.get("ticker"),
            "status": decision.action,
            "reason": decision.reason,
            "current_debit": current_debit,
            "underlying_price": managed.underlying_price,
            "breakeven_price": managed.breakeven_price,
            "feasibility_context": feasibility_ctx,
            "legs": refreshed_legs,
            "metadata": metadata,
        }
        if decision.action == "close":
            response = client.submit_order(build_close_envelope(managed, decision).alpaca_payload())
            close_status = "close_submitted"
            exit_price = None
            qty = int(row.get("quantity") or 1)
            realized_pnl = None

            if hasattr(client, "order") and isinstance(response, dict) and response.get("id"):
                close_order = response
                for _ in range(6):
                    time.sleep(0.5)
                    try:
                        close_order = client.order(str(response["id"]))
                        if str(close_order.get("status") or "").lower() == "filled":
                            break
                    except Exception:
                        pass
                if str(close_order.get("status") or "").lower() == "filled":
                    close_status = "broker_closed"
                    exit_price = abs(float(close_order.get("filled_avg_price") or 0))
                    if entry_credit is not None:
                        realized_pnl = round((entry_credit - exit_price) * qty * 100, 2)
                    elif entry_debit is not None:
                        realized_pnl = round((exit_price - entry_debit) * qty * 100, 2)

            record.update(
                {
                    "status": close_status,
                    "order_id": response["id"],
                    "client_order_id": response.get("client_order_id"),
                    "response": response,
                    "exit_price": exit_price,
                    "realized_pnl": realized_pnl,
                    "quantity": qty,
                    "entry_credit": entry_credit,
                    "entry_debit": entry_debit,
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
