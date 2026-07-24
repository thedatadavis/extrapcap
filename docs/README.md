# Workflow Reference

This folder collects the operational story for how Extrapcap decides when to open and close its core paper-traded premium positions.

The short version is:

- the system looks for stretched or weak relative-streak setups, scores them with a model, and only then considers opening premium
- the system closes open premium positions only when profit, loss, or time-based exit rules say to do so

The model does not predict a dollar outcome directly. It estimates how likely the next completed observation is to be non-negative on a relative-return basis. That probability is then bucketed:

- below `0.50` means the setup is too weak and goes to `crash_protocol`
- from `0.50` up to the premium cutoff means the setup is interesting but not strong enough to sell premium on
- at or above the premium cutoff means the setup can be treated as a `premium_candidate`, subject to the rest of the gates

So when this docs folder talks about a “premium” decision, it is describing a probability-driven filter, not a guarantee of profit.

## Trade Types

The core sleeve trades defined-risk verticals, usually put spreads.

- `sell_to_open`: opens a new credit spread and collects premium up front
- `buy_to_close`: closes an existing credit spread and releases the remaining risk

The intention is not to buy directional upside. The intent is to harvest premium when the setup looks favorable, then manage the open spread until profit target, stop loss, or time stop says to exit.

In plain language:

- `sell_to_open` means “take the other side of the premium trade and start the position”
- `buy_to_close` means “take the trade off and flatten the exposure”

That means “buy” in the exit workflow is not a bullish new bet. It is just the mechanical close-out of an existing credit position.

## Sell Workflow

This is the entry workflow that decides whether a ticker is worth selling premium on.

1. Start from the completed relative-return streak screen.
2. Require a negative streak, a valid completed streak length, and a strong enough robust Z-score.
3. Score the surviving rows with the versioned Sniper model.
4. Keep only rows that land in the `premium_candidate` bucket.
5. Limit the ranked set to the configured top N candidates.
6. Recompute provider-backed bars, streak context, and fresh option-chain data for the selected name.
7. Apply event checks, quote-quality checks, spread-width checks, and portfolio-risk checks.
8. If the candidate still passes, submit a `sell_to_open` order for the vertical spread.

The intention behind the sell side is to open a bounded-risk credit position only when the model and the surrounding gates both support it.

The important detail is that the model is not the whole decision. It is one stage in a chain:

- the streak screen says whether the setup belongs in the basket at all
- the Sniper model says whether the setup looks strong enough to deserve premium treatment
- the provider-backed checks say whether the live market, quote quality, and risk context still support it

Only after all of those agree does the system open the spread.

## Buy Workflow

This is the exit workflow for already-open credit spreads.

1. Read the current open position and its opening credit.
2. Pull the current mark for the spread.
3. Compare the current debit against the configured profit target.
4. Compare the current debit against the configured stop loss.
5. Compare the holding period against the time-stop threshold.
6. If any exit rule is hit, build a `buy_to_close` envelope and submit the close order.

The intention behind the buy side is defensive and mechanical: take profit when the spread has decayed enough, cut it when risk is too high, or exit on time if the position has overstayed its window.

The exit workflow is deliberately simpler than entry. It does not try to re-run the whole opportunity search. It only asks:

- has the position made enough money to close?
- has the position moved against us enough to stop out?
- has it been held long enough that the time stop should take over?

## Why the workflows are separate

Entry and exit are intentionally different decisions.

- entry asks whether a fresh spread should be sold at all
- exit asks whether an existing spread should be closed now

That separation keeps the model score, the risk checks, and the exit rules from being conflated into one decision.

## What To Read Next

- [`docs/strategy/streaks.md`](strategy/streaks.md) for the streak screen and why the 2-to-7 run matters
- [`docs/strategy/variants.md`](strategy/variants.md) for how the basket and Sniper model fit together
- [`docs/architecture.md`](architecture.md) for the broader system flow
