from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
from pathlib import Path

from ..events import EventDecision
from ..execution.orders import OrderEnvelope, OrderRegistry
from ..fills import FillAssumptions, credit_fill, debit_fill
from ..ledger import AuditLedger
from ..options import DebitSpread, VerticalSpread
from ..options_data import (
    SelectedVertical,
    SelectedDebitVertical,
    contracts_from_payload,
    normalize_chain,
    select_put_vertical,
    select_bearish_put_debit_vertical,
    select_highest_ev_vertical,
    selected_vertical_quote_quality,
)
from ..risk import PortfolioRiskState, RiskDecision, approve_asymmetric, approve_candidate
from ..execution.reconcile import reconcile
from ..config import RiskConfig, StrategyConfig


PAPER_ORDER_ACCEPTED_STATUSES = {
    "accepted",
    "new",
    "pending_new",
    "partially_filled",
    "filled",
    "done_for_day",
}
PAPER_ORDER_REJECTED_STATUSES = {"rejected", "canceled", "expired", "suspended"}


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
    market_data_details: dict | None = None
    strategy_variant: str = "improved"
    selection_context: dict | None = None

    @property
    def signal_id(self) -> str:
        context = self.selection_context or {}
        live_features = context.get("live_features") or {}
        identity = {
            "trading_day": self.envelope.trading_day,
            "ticker": self.envelope.symbol.upper(),
            "sleeve": self.envelope.sleeve,
            "strategy_variant": self.strategy_variant,
            "strategy_route": context.get("strategy_route"),
            "formation_as_of": context.get("formation_date") or live_features.get("as_of"),
        }
        canonical = json.dumps(identity, sort_keys=True, default=str)
        return "sig-" + hashlib.sha256(canonical.encode()).hexdigest()[:24]


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
    fill_assumptions: FillAssumptions | None = None,
    delta_min: float = 0.15,
    delta_max: float = 0.20,
    width: float = 5.0,
    strategy_variant: str = "improved",
    selection_context: dict | None = None,
    observed_at: datetime | None = None,
    max_quote_age_seconds: int = 1800,
    max_quote_spread_pct: float = 0.25,
    min_credit_pct_width: float = 0.20,
) -> PaperCandidate:
    assumptions = fill_assumptions or FillAssumptions()
    contracts = contracts_from_payload(contracts_payload)
    quotes = normalize_chain(snapshot_payload)
    selected = select_put_vertical(underlying, contracts, quotes, underlying_price, delta_min, delta_max, width)
    quote_map = {quote.symbol: quote for quote in quotes}
    fill_dollars = credit_fill(quote_map[selected.short.symbol].bid, quote_map[selected.long.symbol].ask, 1, assumptions)
    spread = VerticalSpread(underlying, selected.short.strike, selected.long.strike, fill_dollars / 100)
    sector = str((selection_context or {}).get("sector") or "").strip()
    market_data_details = {
        "data_tier": snapshot_payload.get("_data_tier"),
        "credit_pct_width": spread.credit / spread.width,
        "min_credit_pct_width": min_credit_pct_width,
    }
    quality_reason = None
    if observed_at is not None:
        quality_reason, quote_details = selected_vertical_quote_quality(
            selected,
            quotes,
            observed_at,
            max_age_seconds=max_quote_age_seconds,
            max_spread_pct=max_quote_spread_pct,
        )
        market_data_details.update(quote_details)
    if quality_reason:
        risk_decision = RiskDecision(False, quality_reason)
    elif spread.credit / spread.width < min_credit_pct_width:
        risk_decision = RiskDecision(False, "credit_below_minimum_pct_width")
    elif not sector or sector.upper() == "N/A":
        risk_decision = RiskDecision(False, "sector metadata required")
    else:
        sector_risk = (risk_state.sector_open_risk or {}).get(sector, 0.0)
        risk_decision = approve_candidate(spread, risk_state, risk_config, sector_risk)
    trap_high = StrategyConfig().trap_high
    bucket = "crash_protocol" if model_probability < 0.50 else "trap" if model_probability < trap_high else "premium_candidate"
    envelope = OrderEnvelope(str(trading_day), underlying, "sell_to_open", selected.order_legs(), "core", limit_price=spread.credit)
    return PaperCandidate(
        envelope=envelope,
        spread=spread,
        selected=selected,
        model_probability=model_probability,
        model_bucket=bucket,
        risk_decision=risk_decision,
        event_decision=event_decision,
        risk_state=risk_state,
        market_data_details=market_data_details,
        strategy_variant=strategy_variant,
        selection_context=selection_context,
    )


def build_crash_candidate(
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
    fill_assumptions: FillAssumptions | None = None,
    delta_min: float = 0.30,
    delta_max: float = 0.50,
    width: float = 10.0,
    strategy_variant: str = "improved",
    selection_context: dict | None = None,
    observed_at: datetime | None = None,
    max_quote_age_seconds: int = 1800,
    max_quote_spread_pct: float = 0.25,
) -> PaperCandidate:
    assumptions = fill_assumptions or FillAssumptions()
    contracts = contracts_from_payload(contracts_payload)
    quotes = normalize_chain(snapshot_payload)
    selected = select_bearish_put_debit_vertical(underlying, contracts, quotes, underlying_price, delta_min, delta_max, width)
    quote_map = {quote.symbol: quote for quote in quotes}
    debit_dollars = debit_fill(quote_map[selected.long.symbol].ask, quote_map[selected.short.symbol].bid, 1, assumptions)
    spread = DebitSpread(underlying, selected.long.strike, selected.short.strike, debit_dollars / 100, sleeve="asymmetric", direction="bearish")
    sector = str((selection_context or {}).get("sector") or "").strip()
    market_data_details = {
        "data_tier": snapshot_payload.get("_data_tier"),
        "debit_pct_width": spread.debit / spread.width,
        "reward_multiple": spread.reward_multiple,
    }
    quality_reason = None
    if observed_at is not None:
        quality_reason, quote_details = selected_vertical_quote_quality(
            selected,
            quotes,
            observed_at,
            max_age_seconds=max_quote_age_seconds,
            max_spread_pct=max_quote_spread_pct,
        )
        market_data_details.update(quote_details)
    if quality_reason:
        risk_decision = RiskDecision(False, quality_reason)
    elif not sector or sector.upper() == "N/A":
        risk_decision = RiskDecision(False, "sector metadata required")
    else:
        risk_decision = approve_asymmetric(spread, risk_state, risk_config)
    envelope = OrderEnvelope(str(trading_day), underlying, "buy_to_open", selected.order_legs(), "asymmetric", limit_price=spread.debit)
    return PaperCandidate(
        envelope=envelope,
        spread=spread,
        selected=selected,
        model_probability=model_probability,
        model_bucket="crash_protocol",
        risk_decision=risk_decision,
        event_decision=event_decision,
        risk_state=risk_state,
        market_data_details=market_data_details,
        strategy_variant=strategy_variant,
        selection_context=selection_context,
    )


_bayesian_model_cache = None


def get_bayesian_model(bars_path: str = "data/normalized/bars.csv"):
    global _bayesian_model_cache
    if _bayesian_model_cache is not None:
        return _bayesian_model_cache
    p = Path(bars_path)
    if not p.exists():
        return None
    try:
        import pandas as pd
        from ..models.bayesian_reversion import BayesianReversionModel
        bars = pd.read_csv(p)
        benchmark = bars.loc[bars.symbol == "SPY"].set_index("date")["close"]
        _bayesian_model_cache = BayesianReversionModel.fit_from_bars(bars, benchmark)
        return _bayesian_model_cache
    except Exception:
        return None


def build_fast_ev_candidate(
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
    strategy_variant: str = "fast_ev",
    selection_context: dict | None = None,
    min_ev: float = 10.0,
    bayes_model=None,
) -> PaperCandidate:
    """Build a candidate by scanning all available vertical spreads for highest EV >= $10.00."""
    ctx = selection_context or {}
    streak_direction = str(ctx.get("streak_direction") or "negative")
    streak_length = int(ctx.get("streak_length") or 2)
    sector = str(ctx.get("sector") or "Unknown").strip()
    day_of_week = trading_day.weekday()

    if bayes_model is True:
        bayes_model = get_bayesian_model()

    if bayes_model is not None and hasattr(bayes_model, "predict_reversion_probability"):
        reversion_prob = bayes_model.predict_reversion_probability(
            streak_length=streak_length,
            streak_direction=streak_direction,
            day_of_week=day_of_week,
            sector=sector,
        )
    else:
        reversion_prob = model_probability if streak_direction == "negative" else (1.0 - model_probability)

    if reversion_prob <= 0.51:
        raise ValueError(f"reversion probability {reversion_prob:.4f} <= 0.51 threshold")

    contracts = contracts_from_payload(contracts_payload)
    quotes = normalize_chain(snapshot_payload)
    sol = select_highest_ev_vertical(
        underlying,
        contracts,
        quotes,
        underlying_price,
        reversion_prob,
        min_ev=min_ev,
        streak_direction=streak_direction,
    )
    spread = sol.spread
    selected = sol.selected
    market_data_details = {
        "data_tier": snapshot_payload.get("_data_tier"),
        "expected_value": sol.expected_value,
        "max_profit": sol.max_profit,
        "max_risk": sol.max_risk,
        "reversion_probability": reversion_prob,
    }
    if not sector or sector.upper() == "N/A":
        risk_decision = RiskDecision(False, "sector metadata required")
    elif isinstance(spread, DebitSpread):
        risk_decision = approve_asymmetric(spread, risk_state, risk_config)
    else:
        sector_risk = (risk_state.sector_open_risk or {}).get(sector, 0.0)
        risk_decision = approve_candidate(spread, risk_state, risk_config, sector_risk)

    if isinstance(spread, DebitSpread):
        envelope = OrderEnvelope(
            str(trading_day), underlying, "buy_to_open", selected.order_legs(), "asymmetric", limit_price=spread.debit
        )
    else:
        envelope = OrderEnvelope(
            str(trading_day), underlying, "sell_to_open", selected.order_legs(), "core", limit_price=spread.credit
        )

    return PaperCandidate(
        envelope=envelope,
        spread=spread,
        selected=selected,
        model_probability=reversion_prob,
        model_bucket="fast_ev_candidate",
        risk_decision=risk_decision,
        event_decision=event_decision,
        risk_state=risk_state,
        market_data_details=market_data_details,
        strategy_variant=strategy_variant,
        selection_context=selection_context,
    )


class PaperRunCoordinator:
    """Runs qualitative review after hard gates; only approved candidates reach execution."""

    def __init__(
        self,
        client,
        reviewer,
        ledger: AuditLedger | None = None,
        registry: OrderRegistry | None = None,
        fast_ev: bool = False,
    ):
        self.client = client
        self.reviewer = reviewer
        self.ledger = ledger or AuditLedger()
        self.registry = registry or OrderRegistry()
        self.fast_ev = fast_ev

    def execute(self, candidate: PaperCandidate) -> dict:
        cid = candidate.envelope.client_order_id
        signal_id = candidate.signal_id
        trading_day = date.fromisoformat(candidate.envelope.trading_day)
        contracts = [
            {
                "contract_id": contract.symbol,
                "ticker": contract.underlying,
                "expiration": contract.expiration,
                "strike": contract.strike,
                "option_type": contract.option_type,
                "role": role,
            }
            for role, contract in (("short", candidate.selected.short), ("long", candidate.selected.long))
        ]
        contract_ids = [contract["contract_id"] for contract in contracts]
        common = {
            "signal_id": signal_id,
            "ticker": candidate.envelope.symbol.upper(),
            "underlying": candidate.envelope.symbol.upper(),
            "contract_ids": contract_ids,
            "contracts": contracts,
            "sleeve": candidate.envelope.sleeve,
            "strategy_variant": candidate.strategy_variant,
            "selection_context": candidate.selection_context or {},
            "data_tier": (candidate.selection_context or {}).get("data_tier"),
            "market_data": candidate.market_data_details or {},
            "risk_snapshot": {
                "nav": candidate.risk_state.nav,
                "core_open_risk": candidate.risk_state.core_open_risk,
                "asymmetric_open_risk": candidate.risk_state.asymmetric_open_risk,
                "daily_pnl": candidate.risk_state.daily_pnl,
                "drawdown": candidate.risk_state.drawdown,
                "open_asymmetric_trades": candidate.risk_state.open_asymmetric_trades,
                "ticker_open_risk": candidate.risk_state.ticker_open_risk or {},
                "sector_open_risk": candidate.risk_state.sector_open_risk or {},
                "options_buying_power": candidate.risk_state.options_buying_power,
                "options_trading_level": candidate.risk_state.options_trading_level,
                "trading_blocked": candidate.risk_state.trading_blocked,
            },
        }
        if self.registry.contains(cid):
            return {"client_order_id": cid, "status": "duplicate_skipped", **common}
        if self.registry.contains_signal(signal_id):
            result = {
                "client_order_id": cid,
                "status": "duplicate_signal_skipped",
                "reason": "signal already submitted",
                **common,
            }
            self.ledger.append("risk", result, trading_day, deduplicate=True)
            return result
        self.ledger.append(
            "signals",
            {
                "kind": "candidate",
                "client_order_id": cid,
                **common,
                "model_probability": candidate.model_probability,
                "model_bucket": candidate.model_bucket,
                "spread": candidate.spread.__dict__,
                "event_decision": candidate.event_decision.__dict__,
                "risk_decision": candidate.risk_decision.__dict__,
            },
            trading_day,
        )
        if not candidate.event_decision.allowed:
            result = {"client_order_id": cid, "status": "vetoed", "reason": candidate.event_decision.reason, **common}
            self.ledger.append("signals", result, trading_day)
            return result
        if not candidate.risk_decision.allowed:
            result = {"client_order_id": cid, "status": "vetoed", "reason": candidate.risk_decision.reason, **common}
            self.ledger.append("risk", result, trading_day)
            return result
        crash_candidate = candidate.model_bucket == "crash_protocol" and isinstance(candidate.spread, DebitSpread)
        is_fast_ev = self.fast_ev or candidate.model_bucket == "fast_ev_candidate"
        if not is_fast_ev and candidate.model_bucket not in {"premium_candidate", "watch_list"} and not crash_candidate:
            result = {"client_order_id": cid, "status": "vetoed", "reason": candidate.model_bucket, **common}
            self.ledger.append("signals", result, trading_day)
            return result
        review_input = {
            "candidate": cid,
            **common,
            "spread": candidate.spread.__dict__,
            "model_probability": candidate.model_probability,
            "model_bucket": candidate.model_bucket,
        }
        if is_fast_ev:
            judgment = {"decision": "go", "reason": "fast_ev_approved", "provider": "system"}
        else:
            try:
                judgment = self.reviewer.review(review_input)
            except Exception as exc:
                judgment = {"decision": "escalate", "reason": f"reviewer failure: {type(exc).__name__}", "provider": "nebius"}
        self.ledger.append(
            "rationales",
            {"client_order_id": cid, **common, "input": review_input, "judgment": judgment},
            trading_day,
        )
        if hasattr(self.client, "execute_order_with_backoff") and not getattr(self.client, "dry_run", True):
            response = self.client.execute_order_with_backoff(
                candidate.envelope.alpaca_payload(),
                candidate_info={
                    "expected_value": candidate.market_data_details.get("expected_value"),
                    "min_ev": 10.0,
                },
                max_attempts=5,
                price_step=0.02,
            )
        else:
            response = self.client.submit_order(candidate.envelope.alpaca_payload())
        if not getattr(self.client, "dry_run", True):
            if not isinstance(response, dict):
                raise RuntimeError("paper order response was not an object")
            provider_status = str(response.get("status", "")).lower()
            if provider_status in PAPER_ORDER_REJECTED_STATUSES:
                result = {
                    "client_order_id": cid,
                    "status": "provider_rejected",
                    "reason": provider_status,
                    "provider_response": response,
                    **common,
                }
                self.ledger.append("risk", result, trading_day)
                return result
            if provider_status not in PAPER_ORDER_ACCEPTED_STATUSES:
                raise RuntimeError(f"unrecognized paper order response status: {provider_status or 'missing'}")
        entry_metadata = {
            "spread_width": candidate.spread.width,
            "opened_at": candidate.envelope.trading_day,
            "strategy_variant": candidate.strategy_variant,
            "signal_id": signal_id,
            "contracts": contracts,
        }
        if isinstance(candidate.spread, DebitSpread):
            entry_metadata.update({"entry_debit": candidate.spread.debit, "direction": candidate.spread.direction})
        else:
            entry_metadata["entry_credit"] = candidate.spread.credit
        self.registry.record(
            candidate.envelope,
            entry_metadata,
            execution_status="dry_run" if getattr(self.client, "dry_run", True) else "submitted",
        )
        result = {
            "client_order_id": cid,
            "status": response.get("status", "submitted"),
            "response": response,
            **common,
        }
        self.ledger.append("orders", result, trading_day)
        if not getattr(self.client, "dry_run", True):
            snapshot = reconcile(self.client, self.ledger, date.fromisoformat(candidate.envelope.trading_day))
            result["reconciled"] = True
            result["open_order_count"] = len(snapshot.open_orders)
            result["position_count"] = len(snapshot.positions)
        return result
