from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import date, datetime

from ..config import RiskConfig
from ..events import EventDecision
from ..execution.orders import OrderEnvelope
from ..ledger import AuditLedger
from ..options import DebitSpread, VerticalSpread
from ..options_data import (
    ExpectedValueSolution,
    SelectedDebitVertical,
    SelectedVertical,
    contracts_from_payload,
    normalize_chain,
    select_candidate_verticals,
    select_highest_ev_vertical,
    selected_vertical_quote_quality,
)
from ..risk import PortfolioRiskState, RiskDecision, approve_dte_risk


@dataclass(frozen=True)
class PaperCandidate:
    envelope: OrderEnvelope
    spread: VerticalSpread | DebitSpread
    selected: SelectedVertical | SelectedDebitVertical
    model_probability: float
    model_bucket: str
    risk_decision: RiskDecision
    event_decision: EventDecision
    risk_state: PortfolioRiskState
    market_data_details: dict
    selection_context: dict

    @property
    def signal_id(self) -> str:
        identity = {
            "day": self.envelope.trading_day,
            "ticker": self.envelope.symbol.upper(),
            "legs": self.envelope.legs,
            "context": self.selection_context,
        }
        return (
            "sig-"
            + hashlib.sha256(
                json.dumps(identity, sort_keys=True, default=str).encode()
            ).hexdigest()[:24]
        )


def _midpoint_spread(selected, quotes: dict[str, object], *, debit: bool) -> float:
    first = quotes.get(selected.long.symbol)
    second = quotes.get(selected.short.symbol)
    first_mid = getattr(first, "midpoint", None) if first else None
    second_mid = getattr(second, "midpoint", None) if second else None
    if first_mid is not None and second_mid is not None:
        value = first_mid - second_mid if debit else second_mid - first_mid
        if value > 0:
            return round(value, 2)
    # Robust fallback to executable natural spread price
    fallback = getattr(selected, "debit" if debit else "credit", None)
    if fallback is not None and fallback > 0:
        return round(float(fallback), 2)
    return 0.05


def candidate_from_solution(
    solution: ExpectedValueSolution,
    *,
    underlying: str,
    trading_day: date,
    model_probability: float,
    quotes: list[OptionQuote],
    quote_map: dict[str, OptionQuote],
    risk_state: PortfolioRiskState,
    risk_config: RiskConfig,
    event_decision: EventDecision,
    selection_context: dict | None = None,
    snapshot_payload: dict,
    observed_at: datetime | None = None,
    max_quote_age_seconds: int = 1800,
    max_quote_spread_pct: float = 0.40,
    max_absolute_spread: float = 0.15,
    preferred_dte: int = 10,
) -> PaperCandidate:
    context = dict(selection_context or {})
    selected = solution.selected
    is_debit = isinstance(solution.spread, DebitSpread)
    price = _midpoint_spread(selected, quote_map, debit=is_debit)

    # Calculate single-contract risk (unit loss)
    if is_debit:
        unit_loss = max(1.0, price * 100.0)
    else:
        spread_width = abs(selected.short.strike - selected.long.strike)
        unit_loss = max(1.0, (spread_width - price) * 100.0)

    # Dynamic sizing by confidence level up to 70% available daily cash
    sleeve_cap = (
        risk_config.max_asymmetric_open_risk_pct
        if is_debit
        else risk_config.max_core_open_risk_pct
    )
    sleeve_open = risk_state.asymmetric_open_risk if is_debit else risk_state.core_open_risk
    available_budget = max(0.0, risk_state.nav * sleeve_cap - sleeve_open)
    if risk_state.options_buying_power is not None:
        available_budget = min(available_budget, max(0.0, risk_state.options_buying_power))

    current_ticker_risk = (risk_state.ticker_open_risk or {}).get(underlying, 0.0)
    ticker_remaining = max(
        0.0, risk_state.nav * risk_config.max_ticker_concentration_pct - current_ticker_risk
    )

    confidence_factor = max(0.0, model_probability - 0.50)
    target_pct = min(risk_config.max_ticker_concentration_pct, 0.03 + confidence_factor * 0.35)
    target_dollar_risk = risk_state.nav * target_pct

    allocated_risk = min(target_dollar_risk, available_budget, ticker_remaining)
    target_quantity = max(1, int(allocated_risk // unit_loss))
    max_contracts = getattr(risk_config, "max_contracts_per_order", 25)
    target_quantity = min(target_quantity, max_contracts)

    while target_quantity > 1 and (
        (sleeve_open + target_quantity * unit_loss > risk_state.nav * sleeve_cap)
        or (
            current_ticker_risk + target_quantity * unit_loss
            > risk_state.nav * risk_config.max_ticker_concentration_pct
        )
        or (
            risk_state.options_buying_power is not None
            and target_quantity * unit_loss > risk_state.options_buying_power
        )
    ):
        target_quantity -= 1

    spread = (
        DebitSpread(
            underlying,
            selected.long.strike,
            selected.short.strike,
            price,
            contracts=target_quantity,
            direction=solution.spread.direction,
        )
        if is_debit
        else VerticalSpread(
            underlying,
            selected.short.strike,
            selected.long.strike,
            price,
            contracts=target_quantity,
            direction=getattr(solution.spread, "direction", "bullish"),
        )
    )
    sector = str(context.get("sector") or "").strip()
    if not sector or sector.upper() in {"N/A", "UNKNOWN"}:
        risk_decision = RiskDecision(False, "sector metadata required")
    else:
        risk_decision = approve_dte_risk(
            spread,
            risk_state,
            risk_config,
            solution.dte,
            (risk_state.sector_open_risk or {}).get(sector, 0.0),
        )
    quality_reason = None
    details = {
        "data_tier": snapshot_payload.get("_data_tier"),
        "expected_value": solution.expected_value,
        "max_profit": spread.max_profit,
        "max_risk": spread.max_loss,
        "quantity": target_quantity,
        "expiration": solution.expiration,
        "dte": solution.dte,
        "reversion_probability": model_probability,
        "entry_price": price,
        "pricing": "midpoint",
    }
    if observed_at is not None:
        quality_reason, quality = selected_vertical_quote_quality(
            selected,
            quotes,
            observed_at,
            max_age_seconds=max_quote_age_seconds,
            max_spread_pct=max_quote_spread_pct,
            max_absolute_spread=max_absolute_spread,
        )
        details.update(quality)
    if quality_reason:
        risk_decision = RiskDecision(False, quality_reason)
    context.update(
        {"dte": solution.dte, "expiration": solution.expiration, "preferred_dte": preferred_dte}
    )
    envelope = OrderEnvelope(
        str(trading_day),
        underlying,
        "buy_to_open" if is_debit else "sell_to_open",
        selected.order_legs(),
        spread.sleeve,
        limit_price=price,
        quantity=target_quantity,
    )
    return PaperCandidate(
        envelope,
        spread,
        selected,
        model_probability,
        "qualified",
        risk_decision,
        event_decision,
        risk_state,
        details,
        context,
    )


def build_candidates(
    *,
    underlying: str,
    trading_day: date,
    underlying_price: float,
    contracts_payload: dict,
    snapshot_payload: dict,
    model_probability: float,
    risk_state: PortfolioRiskState,
    risk_config: RiskConfig,
    event_decision: EventDecision,
    selection_context: dict | None = None,
    observed_at: datetime | None = None,
    max_quote_age_seconds: int = 1800,
    max_quote_spread_pct: float = 0.40,
    max_absolute_spread: float = 0.15,
    min_ev: float = 0.0,
    dte_min: int = 0,
    dte_max: int = 21,
    preferred_dte: int = 10,
    widths: tuple[float, ...] | None = None,
    min_width_pct: float = 0.005,
    max_width_pct: float = 0.05,
    limit: int = 5,
) -> list[PaperCandidate]:
    if not 0 < model_probability < 1:
        raise ValueError("model probability must be strictly between zero and one")
    context = dict(selection_context or {})
    direction = str(context.get("streak_direction") or "").lower()
    if direction not in {"negative", "positive"}:
        raise ValueError("selection context requires streak direction")
    sleeve = str(context.get("sleeve") or "core").lower()
    spread_types = context.get("spread_types") or (
        ("credit",) if sleeve == "core" else ("debit", "credit")
    )
    contracts = contracts_from_payload(contracts_payload)
    quotes = normalize_chain(snapshot_payload)
    solutions = select_candidate_verticals(
        underlying,
        contracts,
        quotes,
        underlying_price,
        model_probability,
        min_ev=min_ev,
        widths=widths,
        streak_direction=direction,
        trading_day=trading_day,
        dte_min=dte_min,
        dte_max=dte_max,
        preferred_dte=preferred_dte,
        min_width_pct=min_width_pct,
        max_width_pct=max_width_pct,
        spread_types=spread_types,
        limit=limit,
    )
    quote_map = {quote.symbol: quote for quote in quotes}
    candidates = []
    for sol in solutions:
        candidates.append(
            candidate_from_solution(
                sol,
                underlying=underlying,
                trading_day=trading_day,
                model_probability=model_probability,
                quotes=quotes,
                quote_map=quote_map,
                risk_state=risk_state,
                risk_config=risk_config,
                event_decision=event_decision,
                selection_context=context,
                snapshot_payload=snapshot_payload,
                observed_at=observed_at,
                max_quote_age_seconds=max_quote_age_seconds,
                max_quote_spread_pct=max_quote_spread_pct,
                max_absolute_spread=max_absolute_spread,
                preferred_dte=preferred_dte,
            )
        )
    return candidates


def build_candidate(
    *,
    underlying: str,
    trading_day: date,
    underlying_price: float,
    contracts_payload: dict,
    snapshot_payload: dict,
    model_probability: float,
    risk_state: PortfolioRiskState,
    risk_config: RiskConfig,
    event_decision: EventDecision,
    selection_context: dict | None = None,
    observed_at: datetime | None = None,
    max_quote_age_seconds: int = 1800,
    max_quote_spread_pct: float = 0.40,
    max_absolute_spread: float = 0.15,
    min_ev: float = 0.0,
    dte_min: int = 0,
    dte_max: int = 21,
    preferred_dte: int = 10,
    widths: tuple[float, ...] | None = None,
    min_width_pct: float = 0.005,
    max_width_pct: float = 0.05,
) -> PaperCandidate:
    candidates = build_candidates(
        underlying=underlying,
        trading_day=trading_day,
        underlying_price=underlying_price,
        contracts_payload=contracts_payload,
        snapshot_payload=snapshot_payload,
        model_probability=model_probability,
        risk_state=risk_state,
        risk_config=risk_config,
        event_decision=event_decision,
        selection_context=selection_context,
        observed_at=observed_at,
        max_quote_age_seconds=max_quote_age_seconds,
        max_quote_spread_pct=max_quote_spread_pct,
        max_absolute_spread=max_absolute_spread,
        min_ev=min_ev,
        dte_min=dte_min,
        dte_max=dte_max,
        preferred_dte=preferred_dte,
        widths=widths,
        min_width_pct=min_width_pct,
        max_width_pct=max_width_pct,
        limit=1,
    )
    if not candidates:
        direction = str((selection_context or {}).get("streak_direction") or "").lower()
        target_direction = "bullish" if direction == "negative" else "bearish"
        raise ValueError(
            f"no {target_direction} vertical spread meets expected value threshold of ${min_ev:.2f}"
        )
    return candidates[0]


class PaperRunCoordinator:
    """Apply event/risk gates and submit every approved candidate to Alpaca paper."""

    def __init__(self, client, reviewer=None, ledger: AuditLedger | None = None):
        self.client = client
        self.reviewer = reviewer
        self.ledger = ledger or AuditLedger()

    def execute(self, candidate: PaperCandidate) -> dict:
        day = date.fromisoformat(candidate.envelope.trading_day)
        common = {
            "signal_id": candidate.signal_id,
            "ticker": candidate.envelope.symbol.upper(),
            "contract_ids": [leg["symbol"] for leg in candidate.envelope.legs],
            "sleeve": candidate.envelope.sleeve,
            "selection_context": candidate.selection_context,
            "market_data": candidate.market_data_details,
            "client_order_id": candidate.envelope.client_order_id,
            "side": candidate.envelope.side,
            "quantity": candidate.envelope.quantity,
            "limit_price": candidate.envelope.limit_price,
            "legs": list(candidate.envelope.legs),
            "strategy_variant": str(
                candidate.selection_context.get("strategy_route") or candidate.envelope.sleeve
            ),
        }
        self.ledger.append(
            "signals",
            {
                "kind": "candidate",
                **common,
                "model_probability": candidate.model_probability,
                "risk_decision": candidate.risk_decision.__dict__,
                "event_decision": candidate.event_decision.__dict__,
            },
            day,
        )
        if not candidate.event_decision.allowed:
            return {**common, "status": "vetoed", "reason": candidate.event_decision.reason}
        if not candidate.risk_decision.allowed:
            return {**common, "status": "vetoed", "reason": candidate.risk_decision.reason}
        if self.reviewer is not None:
            # Nebius is advisory; an unavailable or negative opinion never becomes a data fallback or entry veto.
            try:
                judgment = self.reviewer.review({**common, "spread": candidate.spread.__dict__})
            except Exception as exc:  # noqa: BLE001 - advisory provider failures never gate execution
                judgment = {
                    "provider": "nebius",
                    "decision": "unavailable",
                    "reason": type(exc).__name__,
                }
            self.ledger.append("rationales", {**common, "judgment": judgment}, day)
        response = self.client.submit_order(candidate.envelope.alpaca_payload())
        if not isinstance(response, dict) or not response.get("id"):
            raise RuntimeError("paper order response omitted broker order id")
        result = {
            **common,
            "status": str(response.get("status") or "submitted"),
            "order_id": response["id"],
            "response": response,
        }
        self.ledger.append("orders", result, day)
        return result

    def execute_with_fill_loop(
        self,
        candidate: PaperCandidate,
        *,
        poll_timeout: float = 15.0,
        poll_interval: float = 2.0,
        natural_poll_timeout: float = 10.0,
        natural_fallback: bool = True,
    ) -> dict:
        """Submit midpoint order, poll for fill, optionally walk price to natural, or cancel."""
        if (
            not hasattr(self.client, "order")
            or not callable(getattr(self.client, "order", None))
            or poll_timeout <= 0
        ):
            return self.execute(candidate)

        day = date.fromisoformat(candidate.envelope.trading_day)
        common = {
            "signal_id": candidate.signal_id,
            "ticker": candidate.envelope.symbol.upper(),
            "contract_ids": [leg["symbol"] for leg in candidate.envelope.legs],
            "sleeve": candidate.envelope.sleeve,
            "selection_context": candidate.selection_context,
            "market_data": candidate.market_data_details,
            "client_order_id": candidate.envelope.client_order_id,
            "side": candidate.envelope.side,
            "quantity": candidate.envelope.quantity,
            "limit_price": candidate.envelope.limit_price,
            "legs": list(candidate.envelope.legs),
            "strategy_variant": str(
                candidate.selection_context.get("strategy_route") or candidate.envelope.sleeve
            ),
        }
        self.ledger.append(
            "signals",
            {
                "kind": "candidate",
                **common,
                "model_probability": candidate.model_probability,
                "risk_decision": candidate.risk_decision.__dict__,
                "event_decision": candidate.event_decision.__dict__,
            },
            day,
        )
        if not candidate.event_decision.allowed:
            return {**common, "status": "vetoed", "reason": candidate.event_decision.reason}
        if not candidate.risk_decision.allowed:
            return {**common, "status": "vetoed", "reason": candidate.risk_decision.reason}
        if self.reviewer is not None:
            try:
                judgment = self.reviewer.review({**common, "spread": candidate.spread.__dict__})
            except Exception as exc:  # noqa: BLE001
                judgment = {
                    "provider": "nebius",
                    "decision": "unavailable",
                    "reason": type(exc).__name__,
                }
            self.ledger.append("rationales", {**common, "judgment": judgment}, day)

        response = self.client.submit_order(candidate.envelope.alpaca_payload())
        if not isinstance(response, dict) or not response.get("id"):
            raise RuntimeError("paper order response omitted broker order id")
        order_id = response["id"]
        order = response

        # Poll midpoint order
        start_time = time.time()
        while time.time() - start_time < poll_timeout:
            time.sleep(poll_interval)
            try:
                order = self.client.order(order_id)
            except Exception:
                continue
            status = str(order.get("status") or "").lower()
            if status in {"filled", "partially_filled"}:
                result = {
                    **common,
                    "status": "filled",
                    "order_id": order_id,
                    "filled_qty": order.get("filled_qty"),
                    "filled_avg_price": order.get("filled_avg_price"),
                    "response": order,
                }
                self.ledger.append("orders", result, day)
                return result
            if status in {"rejected", "canceled", "expired"}:
                return {
                    **common,
                    "status": status,
                    "order_id": order_id,
                    "reason": f"broker_{status}",
                    "response": order,
                }

        # Unfilled at midpoint -> cancel order cleanly
        try:
            self.client.cancel_order(order_id)
        except Exception:
            pass
        time.sleep(0.5)
        try:
            final_mid = self.client.order(order_id)
            if str(final_mid.get("status") or "").lower() in {"filled", "partially_filled"}:
                result = {
                    **common,
                    "status": "filled",
                    "order_id": order_id,
                    "filled_qty": final_mid.get("filled_qty"),
                    "filled_avg_price": final_mid.get("filled_avg_price"),
                    "response": final_mid,
                }
                self.ledger.append("orders", result, day)
                return result
        except Exception:
            pass

        # If natural fallback enabled, try natural executable price
        if natural_fallback:
            is_debit = isinstance(candidate.spread, DebitSpread)
            natural_price = round(
                float(
                    getattr(candidate.selected, "debit" if is_debit else "credit", 0.0)
                    or getattr(candidate.spread, "debit" if is_debit else "credit", 0.0)
                    or 0.0
                ),
                2,
            )
            if natural_price > 0 and abs(natural_price - candidate.envelope.limit_price) >= 0.01:
                natural_envelope = OrderEnvelope(
                    str(candidate.envelope.trading_day),
                    candidate.envelope.symbol,
                    candidate.envelope.side,
                    candidate.envelope.legs,
                    candidate.envelope.sleeve,
                    limit_price=natural_price,
                    quantity=candidate.envelope.quantity,
                )
                try:
                    nat_resp = self.client.submit_order(natural_envelope.alpaca_payload())
                    nat_order_id = nat_resp.get("id")
                    nat_start = time.time()
                    nat_order = nat_resp
                    while time.time() - nat_start < natural_poll_timeout:
                        time.sleep(poll_interval)
                        try:
                            nat_order = self.client.order(nat_order_id)
                        except Exception:
                            continue
                        nat_status = str(nat_order.get("status") or "").lower()
                        if nat_status in {"filled", "partially_filled"}:
                            result = {
                                **common,
                                "status": "filled",
                                "order_id": nat_order_id,
                                "limit_price": natural_price,
                                "filled_qty": nat_order.get("filled_qty"),
                                "filled_avg_price": nat_order.get("filled_avg_price"),
                                "response": nat_order,
                            }
                            self.ledger.append("orders", result, day)
                            return result
                        if nat_status in {"rejected", "canceled", "expired"}:
                            break
                    # Unfilled after natural timeout: cancel cleanly
                    try:
                        self.client.cancel_order(nat_order_id)
                    except Exception:
                        pass
                    time.sleep(0.5)
                    try:
                        final_nat = self.client.order(nat_order_id)
                        if str(final_nat.get("status") or "").lower() in {
                            "filled",
                            "partially_filled",
                        }:
                            result = {
                                **common,
                                "status": "filled",
                                "order_id": nat_order_id,
                                "limit_price": natural_price,
                                "filled_qty": final_nat.get("filled_qty"),
                                "filled_avg_price": final_nat.get("filled_avg_price"),
                                "response": final_nat,
                            }
                            self.ledger.append("orders", result, day)
                            return result
                    except Exception:
                        pass
                except Exception:
                    pass

        result = {
            **common,
            "status": "unfilled",
            "reason": "fill_timeout",
            "order_id": order_id,
            "response": order,
        }
        self.ledger.append("orders", result, day)
        return result

