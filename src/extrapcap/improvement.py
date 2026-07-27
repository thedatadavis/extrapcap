from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path


from .llm.nebius import NebiusReviewer


@dataclass(frozen=True)
class ParameterBound:
    name: str
    low: float
    high: float
    step: float


@dataclass(frozen=True)
class PolicyProposal:
    parameter: str
    current: float
    proposed: float
    evidence: dict
    status: str = "proposed"
    created_at: str = ""

    def as_dict(self) -> dict:
        return {
            "parameter": self.parameter,
            "current": self.current,
            "proposed": self.proposed,
            "evidence": self.evidence,
            "status": self.status,
            "created_at": self.created_at,
        }


class SafePolicyLearner:
    """Bounded, offline-only policy recommender; it cannot submit orders."""

    def __init__(self, bounds: tuple[ParameterBound, ...]):
        self.bounds = {bound.name: bound for bound in bounds}

    def propose(self, parameter: str, current: float, direction: int, evidence: dict) -> PolicyProposal:
        if parameter not in self.bounds:
            raise ValueError(f"parameter is not policy-controlled: {parameter}")
        bound = self.bounds[parameter]
        if direction not in {-1, 1}:
            raise ValueError("direction must be -1 or 1")
        proposed = min(bound.high, max(bound.low, current + direction * bound.step))
        return PolicyProposal(parameter, current, proposed, evidence, created_at=datetime.now(timezone.utc).isoformat())

    def approve(self, proposal: PolicyProposal, *, tests_passed: bool, simulation_passed: bool, human_approved: bool, rollback_ready: bool) -> PolicyProposal:
        if not all((tests_passed, simulation_passed, human_approved, rollback_ready)):
            return PolicyProposal(**{**proposal.as_dict(), "status": "rejected"})
        return PolicyProposal(**{**proposal.as_dict(), "status": "approved"})

    @staticmethod
    def write(path: str | Path, proposal: PolicyProposal) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(proposal.as_dict(), indent=2) + "\n", encoding="utf-8")
        return target


class NebiusPolicyLearner:
    """Uses Nebius GLM 5.2 with max thinking effort to analyze execution history and propose policy updates."""

    DEFAULT_BOUNDS = (
        ParameterBound("z_threshold", -3.0, -1.0, 0.25),
        ParameterBound("max_option_spread_pct", 0.15, 0.50, 0.05),
        ParameterBound("min_credit_pct_width", 0.02, 0.30, 0.03),
        ParameterBound("max_candidates", 5, 50, 5),
    )

    def __init__(self, reviewer: NebiusReviewer | None = None, bounds: tuple[ParameterBound, ...] | None = None):
        self.reviewer = reviewer or NebiusReviewer()
        self.learner = SafePolicyLearner(bounds or self.DEFAULT_BOUNDS)

    def analyze_and_propose(self, events: list[dict], current_config: dict) -> list[PolicyProposal]:
        """Analyze trading events and request structured policy parameter tuning proposals from Nebius GLM 5.2."""
        summary = {
            "total_events": len(events),
            "current_config": current_config,
            "parameter_bounds": {name: {"low": b.low, "high": b.high, "step": b.step} for name, b in self.learner.bounds.items()},
            "order_outcomes": [
                {
                    "ticker": e.get("ticker"),
                    "status": e.get("status"),
                    "reason": e.get("reason"),
                    "sleeve": e.get("sleeve"),
                }
                for e in events
                if e.get("category") in {"orders", "risk", "rationales"} or e.get("status") in {"submitted", "filled", "vetoed"}
            ],
        }
        prompt = """Analyze the supplied paper trading execution and veto history.
Evaluate whether policy bounds (z_threshold, max_option_spread_pct, min_credit_pct_width, max_candidates)
should be adjusted to optimize trade frequency, execution quality, and risk posture.
Return JSON with key "proposals", an array of objects with fields: "parameter" (string), "current" (number), "direction" (integer -1 or 1), and "rationale" (string)."""

        judgment = self.reviewer._request_json(system=prompt, user=summary, thinking_effort="max")
        proposals = []
        raw_proposals = judgment.get("proposals") if isinstance(judgment.get("proposals"), list) else []
        for prop in raw_proposals:
            if not isinstance(prop, dict):
                continue
            param = prop.get("parameter")
            curr = prop.get("current")
            direction = prop.get("direction")
            rationale = str(prop.get("rationale") or "LLM policy recommendation")
            if param in self.learner.bounds and isinstance(curr, (int, float)) and direction in {-1, 1}:
                try:
                    proposal = self.learner.propose(
                        parameter=param,
                        current=float(curr),
                        direction=int(direction),
                        evidence={"rationale": rationale, "llm_model": self.reviewer.model, "event_count": len(events)},
                    )
                    proposals.append(proposal)
                except ValueError:
                    continue
        return proposals

