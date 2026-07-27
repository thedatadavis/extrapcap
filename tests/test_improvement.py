from extrapcap.improvement import NebiusPolicyLearner, ParameterBound, SafePolicyLearner


def test_policy_proposals_are_bounded_and_need_all_gates():
    learner = SafePolicyLearner((ParameterBound("z_threshold", -3.0, -2.0, 0.25),))
    proposal = learner.propose("z_threshold", -2.0, 1, {"oos_expectancy": 0.1})
    assert proposal.proposed == -2.0
    assert learner.approve(proposal, tests_passed=True, simulation_passed=True, human_approved=False, rollback_ready=True).status == "rejected"
    assert learner.approve(proposal, tests_passed=True, simulation_passed=True, human_approved=True, rollback_ready=True).status == "approved"


def test_nebius_policy_learner_parses_llm_proposals():
    class DummyReviewer:
        model = "glm-5.2"

        def _request_json(self, system: str, user: dict, thinking_effort: str = "max") -> dict:
            assert thinking_effort == "max"
            return {
                "proposals": [
                    {"parameter": "z_threshold", "current": -2.0, "direction": 1, "rationale": "relax z threshold"},
                    {"parameter": "max_candidates", "current": 25, "direction": 1, "rationale": "expand capacity"},
                ]
            }

    policy_learner = NebiusPolicyLearner(reviewer=DummyReviewer())
    proposals = policy_learner.analyze_and_propose([{"ticker": "AAPL", "status": "submitted", "category": "orders"}], {})
    assert len(proposals) == 2
    assert proposals[0].parameter == "z_threshold"
    assert proposals[0].proposed == -1.75
    assert proposals[1].parameter == "max_candidates"
    assert proposals[1].proposed == 30

