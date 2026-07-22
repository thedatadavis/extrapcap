# Generated state branch

`main` contains source code, workflow definitions, tests, and documentation.
The `ops` branch contains generated runtime state: logs, reports, market-data
snapshots, features, scored data, universe snapshots, and model artifacts.

Scheduled and manual operational workflows check out `ops`, merge the latest
`main`, run their job, and commit generated outputs back to `ops`. The shared
`extrapcap-ops-writer` concurrency group serializes these writers. The Pages
workflow deploys the checked-out `ops` branch, so the public journal and the
runtime inputs are from one consistent snapshot.

The synchronization helper preserves the existing generated tree while
merging source changes. This allows `main` to omit generated files without
deleting the operational state on every sync.

Generated paths are owned by `ops`. Code changes that alter their schemas or
consumers belong on `main`; the next synchronization run makes those changes
available to `ops`. Do not force-push `ops` or hand-edit generated files there.
