interface Env {
  DB: any;
}

export const onRequestPost: PagesFunction<Env> = async ({ request, env }) => {
  try {
    const payload = await request.json();
    const events = Array.isArray(payload) ? payload : [payload];

    const stmt = env.DB.prepare(`
      INSERT OR IGNORE INTO events
      (event_id, trading_day, category, kind, ticker, status, reason, sleeve, strategy_variant, strategy_route, model_probability, payload)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);

    const batch = events.map((e: any) => {
      const j = e.journal ?? {};
      return stmt.bind(
        j.event_id || e.event_id || `evt-${Date.now()}-${Math.random().toString(36).substring(2, 8)}`,
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

    await env.DB.batch(batch);
    return Response.json({ success: true, count: batch.length });
  } catch (err: any) {
    return Response.json({ error: err.message }, { status: 500 });
  }
};

export const onRequestGet: PagesFunction<Env> = async ({ request, env }) => {
  try {
    const url = new URL(request.url);
    const day = url.searchParams.get('day');
    const ticker = url.searchParams.get('ticker');
    const category = url.searchParams.get('category');
    const limit = parseInt(url.searchParams.get('limit') || '500', 10);

    let sql = 'SELECT * FROM events WHERE 1=1';
    const params: any[] = [];

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

    const result = await env.DB.prepare(sql).bind(...params).all();
    return Response.json(result.results || []);
  } catch (err: any) {
    return Response.json({ error: err.message }, { status: 500 });
  }
};
