interface Env {
  DB: any;
}

export const onRequestGet: PagesFunction<Env> = async ({ env }) => {
  try {
    if (!env.DB) {
      return Response.json({
        success: false,
        error: 'Database binding not available',
        server_time: new Date().toISOString(),
      });
    }

    // 1. Fetch recent runs (last 5)
    let recentRuns: any[] = [];
    try {
      const runsRes = await env.DB.prepare(
        'SELECT * FROM runs ORDER BY started_at DESC LIMIT 5'
      ).all();
      recentRuns = runsRes.results || [];
    } catch {
      // Table might be empty or missing in dev
    }

    // 2. Fetch active running workflows
    const runningRuns = recentRuns.filter((r) => r.status === 'running');
    const latestRun = recentRuns[0] || null;

    // 3. Fetch latest account snapshot
    let latestAccount: any = null;
    try {
      latestAccount = await env.DB.prepare(
        'SELECT as_of as date, equity as balance, cash, buying_power as buyingPower FROM account_snapshots ORDER BY as_of DESC LIMIT 1'
      ).first();
    } catch {
      // Ignored if missing
    }

    // 4. Fetch latest ledger event
    let latestEvent: any = null;
    try {
      latestEvent = await env.DB.prepare(
        'SELECT event_id, recorded_at, trading_day, category, kind, status FROM events ORDER BY recorded_at DESC LIMIT 1'
      ).first();
    } catch {
      // Ignored if missing
    }

    // 5. Generate version hash for client change detection
    const syncHashParts = [
      latestRun?.run_id ?? '',
      latestRun?.status ?? '',
      latestRun?.finished_at ?? latestRun?.started_at ?? '',
      latestAccount?.date ?? '',
      latestAccount?.balance ?? '',
      latestEvent?.event_id ?? '',
      latestEvent?.recorded_at ?? '',
    ];
    const syncHash = syncHashParts.join(':');

    return Response.json(
      {
        success: true,
        server_time: new Date().toISOString(),
        sync_hash: syncHash,
        latest_run: latestRun,
        running_runs: runningRuns,
        recent_runs: recentRuns,
        latest_account: latestAccount,
        latest_event: latestEvent,
      },
      {
        headers: {
          'Cache-Control': 'no-cache, no-store, must-revalidate',
          'Content-Type': 'application/json',
        },
      }
    );
  } catch (err: any) {
    return Response.json(
      { error: err.message, server_time: new Date().toISOString() },
      { status: 500 }
    );
  }
};
