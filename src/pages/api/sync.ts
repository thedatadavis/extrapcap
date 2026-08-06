import type { APIRoute } from 'astro';

export const GET: APIRoute = async ({ locals }) => {
  try {
    const db = (locals as any).runtime?.env?.DB;
    if (!db) {
      return new Response(JSON.stringify({
        success: false,
        error: 'Database binding not available',
        server_time: new Date().toISOString(),
      }), {
        headers: { 'Content-Type': 'application/json' }
      });
    }

    let recentRuns: any[] = [];
    try {
      const runsRes = await db.prepare('SELECT * FROM runs ORDER BY started_at DESC LIMIT 5').all();
      recentRuns = runsRes.results || [];
    } catch {}

    const runningRuns = recentRuns.filter((r) => r.status === 'running');
    const latestRun = recentRuns[0] || null;

    let latestAccount: any = null;
    try {
      latestAccount = await db.prepare(
        'SELECT as_of as date, equity as balance, cash, buying_power as buyingPower FROM account_snapshots ORDER BY as_of DESC LIMIT 1'
      ).first();
    } catch {}

    let latestEvent: any = null;
    try {
      latestEvent = await db.prepare(
        'SELECT event_id, recorded_at, trading_day, category, kind, status FROM events ORDER BY recorded_at DESC LIMIT 1'
      ).first();
    } catch {}

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

    return new Response(JSON.stringify({
      success: true,
      server_time: new Date().toISOString(),
      sync_hash: syncHash,
      latest_run: latestRun,
      running_runs: runningRuns,
      recent_runs: recentRuns,
      latest_account: latestAccount,
      latest_event: latestEvent,
    }), {
      headers: {
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Content-Type': 'application/json',
      },
    });
  } catch (err: any) {
    return new Response(JSON.stringify({ error: err.message, server_time: new Date().toISOString() }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
};
