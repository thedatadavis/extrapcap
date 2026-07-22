from extrapcap.improvement import ParameterBound, SafePolicyLearner


def test_policy_proposals_are_bounded_and_need_all_gates():
    learner = SafePolicyLearner((ParameterBound("z_threshold", -3.0, -2.0, 0.25),))
    proposal = learner.propose("z_threshold", -2.0, 1, {"oos_expectancy": 0.1})
    assert proposal.proposed == -2.0
    assert learner.approve(proposal, tests_passed=True, simulation_passed=True, human_approved=False, rollback_ready=True).status == "rejected"
    assert learner.approve(proposal, tests_passed=True, simulation_passed=True, human_approved=True, rollback_ready=True).status == "approved"
