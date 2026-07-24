# ADR 0001: paper-first provider boundary

## Decision

Paper Alpaca execution remains the default and is permitted only through the paper base URL when `ALPACA_PAPER=true`. A separate manual live route is permitted only through the exact live base URL, separate live credentials, `ALPACA_PAPER=false`, and `EXTRAPCAP_LIVE_SUBMIT_ENABLED=true`; scheduled workflows never select it. Provider credentials are environment inputs, never repository data. Nebius is advisory and structured; a missing key produces `escalate`.

## Rationale

The first operational milestone is observable paper behavior. A hard URL guard and a separate advisory LLM boundary prevent configuration drift from turning research code into an accidental live-trading system.

## Consequences

Paper credentials must be provisioned through local secret management or GitHub environment secrets. The agent does not commit or echo the credentials. Live routing is intentionally unsupported until a separately reviewed ADR changes this boundary.
