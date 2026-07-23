# Provider secrets

The repository never stores raw credentials. `.env.example` documents names only and `.gitignore` excludes `.env.*` except that example.

Required runtime variables:

```text
ALPACA_PAPER=true
ALPACA_BASE_URL=https://paper-api.alpaca.markets/v2
ALPACA_API_KEY=<Extrapcap paper account key>
ALPACA_SECRET_KEY=<Extrapcap paper account secret>
NEBIUS_BASE_URL=https://api.tokenfactory.nebius.com/v1
NEBIUS_API_KEY=<Nebius project key>
NEBIUS_MODEL=Qwen/Qwen3-30B-A3B-Instruct-2507
EXTRAPCAP_NEWS_EVENTS=data/events/news.csv
EXTRAPCAP_EXECUTION_MODE=dry-run
EXTRAPCAP_PAPER_SUBMIT_ENABLED=false
```

For local runs, load these from the operator's secret manager or an ignored `.env.local`. For GitHub Actions, add the three credential values as repository/environment secrets and keep the `paper` environment approval gate enabled. Never paste a raw key into an issue, commit, workflow file, report, or chat message.

The runtime reads environment variables or these optional login-Keychain service names: `extrapcap.alpaca.api_key`, `extrapcap.alpaca.secret_key`, and `extrapcap.nebius.api_key`. GitHub Actions uses repository or environment secrets. The code refuses `paper-submit` without credentials and the separate `EXTRAPCAP_PAPER_SUBMIT_ENABLED=true` switch.

The Alpaca adapter normalizes the host-only legacy value to `https://paper-api.alpaca.markets/v2`, rejects every other origin or API version, and never falls back to Alpaca's live-trading host. The Nebius reviewer escalates when its key is absent. A missing secret is a safe stop, not permission to fall back to another account.

The position-management workflow uses the same paper credentials to read held option legs and current free indicative quotes. It defaults to `dry-run`; selecting `paper-submit` is an explicit workflow input and remains subject to the GitHub `paper` environment approval gate.

When `EXTRAPCAP_NEWS_EVENTS` is set, the live cycle requires a CSV with `date,symbol,structural_risk` columns and applies matching structural-risk rows as hard vetoes. Keep the file dated and versioned; malformed event data fails closed.

Add `headline` to event rows and set `EXTRAPCAP_NEWS_LLM=true` to invoke Nebius classification for non-structural rows. A missing or malformed Nebius classification is a veto/escalation, never an approval.

Paper operation is intentionally split into one candidate review, one idempotent order decision, position management, and reconciliation. The former SPY intraday workflow is manual-only as a diagnostic; it is not part of the live paper schedule or a low-latency execution venue.

Run `python -m extrapcap.diagnostics --require-ready` before any live-cycle invocation. It performs read-only checks, never prints keys or submits orders, and exits nonzero unless both providers are reachable.

Turning on paper submission is deliberately two-step:

1. Keep `EXTRAPCAP_EXECUTION_MODE=dry-run` and `EXTRAPCAP_PAPER_SUBMIT_ENABLED=false` while diagnostics and candidate-review dry runs are verified.
2. Set the GitHub Actions variable `EXTRAPCAP_PAPER_SUBMIT_ENABLED=true` only after reviewing the paper account, open-order registry, logs, and risk limits.
3. Scheduled candidate review and position management use `paper-submit` explicitly. Select `paper-submit` for a manual workflow run; scheduled and manual submission still require `EXTRAPCAP_PAPER_SUBMIT_ENABLED=true` in the paper environment.

Reset and position-management submissions use the same enable switch. Account reset additionally requires the exact `RESET_PAPER_ACCOUNT` confirmation token.
