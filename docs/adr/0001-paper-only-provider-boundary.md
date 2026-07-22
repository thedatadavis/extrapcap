# ADR 0001: paper-only provider boundary

## Decision

Alpaca execution is permitted only through the paper base URL and only when `ALPACA_PAPER=true`. Provider credentials are environment inputs, never repository data. Nebius is advisory and structured; a missing key produces `escalate`.

## Rationale

The first operational milestone is observable paper behavior. A hard URL guard and a separate advisory LLM boundary prevent configuration drift from turning research code into an accidental live-trading system.

## Consequences

Paper credentials must be provisioned through local secret management or GitHub environment secrets. The agent does not commit or echo the credentials. Live routing is intentionally unsupported until a separately reviewed ADR changes this boundary.
