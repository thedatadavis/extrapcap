import type { APIRoute } from 'astro';

export const GET: APIRoute = async ({ request, locals }) => {
  try {
    const db = (locals as any).runtime?.env?.DB;
    if (!db) return new Response(JSON.stringify([]), { headers: { 'Content-Type': 'application/json' } });

    const url = new URL(request.url);
    const day = url.searchParams.get('day');
    const runId = url.searchParams.get('run_id');
    const ticker = url.searchParams.get('ticker');
    const category = url.searchParams.get('category');
    const limit = parseInt(url.searchParams.get('limit') || '500', 10);

    let sql = 'SELECT * FROM events WHERE 1=1';
    const params: any[] = [];

    if (runId) {
      sql += ' AND run_id = ?';
      params.push(runId);
    }
    if (day) {
      sql += ' AND trading_day = ?';
      params.push(day);
    }
    if (ticker) {
      sql += ' AND ticker = ?';
      params.push(ticker);
    }
    if (category) {
      sql += ' AND category = ?';
      params.push(category);
    }

    sql += ' ORDER BY recorded_at DESC LIMIT ?';
    params.push(limit);

    const result = await db.prepare(sql).bind(...params).all();
    return new Response(JSON.stringify(result.results || []), {
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err: any) {
    return new Response(JSON.stringify({ error: err.message }), { status: 500 });
  }
};

export const POST: APIRoute = async ({ request, locals }) => {
  try {
    const db = (locals as any).runtime?.env?.DB;
    if (!db) return new Response(JSON.stringify({ error: 'DB not available' }), { status: 500 });

    const payload = await request.json();
    const events = Array.isArray(payload) ? payload : [payload];

    const stmt = db.prepare(`
      INSERT OR IGNORE INTO events
      (event_id, run_id, trading_day, category, kind, ticker, status, reason, sleeve, strategy_variant, strategy_route, model_probability, payload)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);

    const batch = events.map((e: any) => {
      const j = e.journal ?? {};
      return stmt.bind(
        j.event_id || e.event_id || `evt-${Date.now()}-${Math.random().toString(36).substring(2, 8)}`,
        e.run_id || j.run_id || null,
        j.trading_day || e.trading_day || new Date().toISOString().split('T')[0],
        j.category || e.category || 'general',
        j.kind || e.kind || null,
        j.ticker || e.ticker || null,
        j.status || e.status || null,
        j.reason || e.reason || null,
        j.sleeve || e.sleeve || 'core',
        j.strategy_variant || e.strategy_variant || null,
        j.strategy_route || e.strategy_route || null,
        j.model_probability ?? e.model_probability ?? null,
        JSON.stringify(e)
      );
    });

    await db.batch(batch);
    return new Response(JSON.stringify({ success: true, count: batch.length }), {
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err: any) {
    return new Response(JSON.stringify({ error: err.message }), { status: 500 });
  }
};

export const DELETE: APIRoute = async ({ request, locals }) => {
  try {
    const db = (locals as any).runtime?.env?.DB;
    if (!db) return new Response(JSON.stringify({ error: 'DB not available' }), { status: 500 });

    const result = await db.prepare("DELETE FROM events WHERE status = 'error'").run();
    return new Response(JSON.stringify({ success: true, changes: result.meta?.changes || 0 }), {
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err: any) {
    return new Response(JSON.stringify({ error: err.message }), { status: 500 });
  }
};
