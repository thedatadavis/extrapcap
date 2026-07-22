# Provider secrets

The repository never stores raw credentials. `.env.example` documents names only and `.gitignore` excludes `.env.*` except that example.

Required runtime variables:

```text
ALPACA_PAPER=true
ALPACA_BASE_URL=https://paper-api.alpaca.markets
ALPACA_API_KEY=<Extrapcap paper account key>
ALPACA_SECRET_KEY=<Extrapcap paper account secret>
NEBIUS_BASE_URL=https://api.tokenfactory.nebius.com/v1
NEBIUS_API_KEY=<Nebius project key>
NEBIUS_MODEL=Qwen/Qwen3-30B-A3B-Instruct-2507
EXTRAPCAP_NEWS_EVENTS=data/events/news.csv
```

For local runs, load these from the operator's secret manager or an ignored `.env.local`. For GitHub Actions, add the four credential values as repository/environment secrets and keep the `paper` environment approval gate enabled. Never paste a raw key into an issue, commit, workflow file, report, or chat message.

The attempted automated macOS Keychain write was rejected by the desktop authorization boundary, so the keys remain unpersisted. The runtime will read either environment variables or these login-Keychain service names: `extrapcap.alpaca.api_key`, `extrapcap.alpaca.secret_key`, and `extrapcap.nebius.api_key`. Add them manually to your preferred secret manager or export the variables in the shell that launches the cycle; the code will refuse `paper-submit` without them.

The Alpaca adapter rejects non-paper URLs and the Nebius reviewer escalates when its key is absent. A missing secret is a safe stop, not permission to fall back to another account.

The position-management workflow uses the same paper credentials to read held option legs and current free indicative quotes. It defaults to `dry-run`; selecting `paper-submit` is an explicit workflow input and remains subject to the GitHub `paper` environment approval gate.

When `EXTRAPCAP_NEWS_EVENTS` is set, the live cycle requires a CSV with `date,symbol,structural_risk` columns and applies matching structural-risk rows as hard vetoes. Keep the file dated and versioned; malformed event data fails closed.

Add `headline` to event rows and set `EXTRAPCAP_NEWS_LLM=true` to invoke Nebius classification for non-structural rows. A missing or malformed Nebius classification is a veto/escalation, never an approval.

Paper operation is intentionally split into one scan, one idempotent order decision, and reconciliation. The intraday workflow is a 15-minute burst scheduler that requests 1-minute bars for each scan; it is not a low-latency execution venue. A future dedicated runner can reuse the same cycle contract if fill-quality and buying-power monitoring justify it.

Run `python -m extrapcap.diagnostics` before any live-cycle invocation. It performs read-only checks and never prints keys or submits orders.
