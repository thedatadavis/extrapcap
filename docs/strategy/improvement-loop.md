# Safe improvement loop

The live paper stream may produce bounded parameter proposals for the Z threshold, delta band, spread width, holding period, sizing caps, scan frequency, and asymmetric funding percentage. `SafePolicyLearner` only emits recommendations. Each proposal must pass tests, simulation, explicit approval, and rollback readiness before a configuration artifact can change. The learner has no execution-provider dependency and cannot submit orders.

## Sleeve-budget controls

`SleeveLedger.realize_premium` supports continuous and explicit batched realized-premium transfers. Batched allocations remain in `pending_asymmetric_funding` until `flush_funding_pool()` is called, so accounting events cannot accidentally create deployable principal before the configured transfer point. Funding is hard-limited to 10%-20% of realized core premium.

Asymmetric candidates must pass a minimum reward-to-risk multiple, independent open-risk and trade-count caps, and the core-drawdown pause. Long-premium positions have deterministic decay and calendar time-stop reasons through `asymmetric_exit_reason`; these are exit controls, not discretionary LLM overrides.
