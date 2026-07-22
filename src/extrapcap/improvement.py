from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path


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
