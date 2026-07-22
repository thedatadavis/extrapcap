from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..events import EventDecision
from ..execution.orders import OrderEnvelope, OrderRegistry
from ..fills import FillAssumptions, credit_fill
from ..ledger import AuditLedger
from ..options import VerticalSpread
from ..options_data import SelectedVertical, contracts_from_payload, normalize_chain, select_put_vertical
from ..risk import PortfolioRiskState, RiskDecision, approve_candidate
from ..execution.reconcile import reconcile
from ..config import RiskConfig


@dataclass(frozen=True)
class PaperCandidate:
    envelope: OrderEnvelope
    spread: VerticalSpread
    selected: SelectedVertical
    model_probability: float
    model_bucket: str
    risk_decision: RiskDecision
    event_decision: EventDecision
    strategy_variant: str = "improved"
    selection_context: dict | None = None


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
) -> PaperCandidate:
    assumptions = fill_assumptions or FillAssumptions()
    contracts = contracts_from_payload(contracts_payload)
    quotes = normalize_chain(snapshot_payload)
    selected = select_put_vertical(underlying, contracts, quotes, underlying_price, delta_min, delta_max, width)
    quote_map = {quote.symbol: quote for quote in quotes}
    fill_dollars = credit_fill(quote_map[selected.short.symbol].bid, quote_map[selected.long.symbol].ask, 1, assumptions)
    spread = VerticalSpread(underlying, selected.short.strike, selected.long.strike, fill_dollars / 100)
    risk_decision = approve_candidate(spread, risk_state, risk_config)
    bucket = "crash_protocol" if model_probability < 0.50 else "trap" if model_probability < 0.65 else "premium_candidate"
    envelope = OrderEnvelope(str(trading_day), underlying, "sell_to_open", selected.order_legs(), "core", limit_price=spread.credit)
    return PaperCandidate(
        envelope,
        spread,
        selected,
        model_probability,
        bucket,
        risk_decision,
        event_decision,
        strategy_variant,
        selection_context,
    )


class PaperRunCoordinator:
    """Runs qualitative review after hard gates; only approved candidates reach execution."""

    def __init__(self, client, reviewer, ledger: AuditLedger | None = None, registry: OrderRegistry | None = None):
        self.client = client
        self.reviewer = reviewer
        self.ledger = ledger or AuditLedger()
        self.registry = registry or OrderRegistry()

    def execute(self, candidate: PaperCandidate) -> dict:
        cid = candidate.envelope.client_order_id
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
            "ticker": candidate.envelope.symbol.upper(),
            "underlying": candidate.envelope.symbol.upper(),
            "contract_ids": contract_ids,
            "contracts": contracts,
            "sleeve": candidate.envelope.sleeve,
            "strategy_variant": candidate.strategy_variant,
            "selection_context": candidate.selection_context or {},
        }
        if self.registry.contains(cid):
            return {"client_order_id": cid, "status": "duplicate_skipped", **common}
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
        if candidate.model_bucket != "premium_candidate":
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
        try:
            judgment = self.reviewer.review(review_input)
        except Exception as exc:
            judgment = {"decision": "escalate", "reason": f"reviewer failure: {type(exc).__name__}", "provider": "nebius"}
        self.ledger.append(
            "rationales",
            {"client_order_id": cid, **common, "input": review_input, "judgment": judgment},
            trading_day,
        )
        if judgment.get("decision") != "go":
            return {"client_order_id": cid, "status": "vetoed", "reason": judgment.get("decision", "missing_decision")}
        response = self.client.submit_order(candidate.envelope.alpaca_payload())
        self.registry.record(
            candidate.envelope,
            {
                "entry_credit": candidate.spread.credit,
                "spread_width": candidate.spread.width,
                "opened_at": candidate.envelope.trading_day,
                "strategy_variant": candidate.strategy_variant,
                "contracts": contracts,
            },
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
