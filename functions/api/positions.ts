interface Env {
  DB: any;
}

export const onRequestPost: PagesFunction<Env> = async ({ request, env }) => {
  try {
    const data = await request.json();
    const stmt = env.DB.prepare(`
      INSERT INTO positions
      (ticker, company_name, short_symbol, long_symbol, short_strike, long_strike, expiration, spread_width, entry_credit, entry_debit, opened_at, sleeve, strategy_variant, strategy_route, quantity, is_active, legs, selection_metrics, metadata)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);

    const res = await stmt.bind(
      data.ticker,
      data.company_name || null,
      data.short_symbol,
      data.long_symbol,
      data.short_strike,
      data.long_strike,
      data.expiration,
      data.spread_width,
      data.entry_credit ?? null,
      data.entry_debit ?? null,
      data.opened_at || new Date().toISOString().split('T')[0],
      data.sleeve || 'core',
      data.strategy_variant || 'fast_ev',
      data.strategy_route || null,
      data.quantity || 1,
      data.is_active ?? 1,
      typeof data.legs === 'string' ? data.legs : JSON.stringify(data.legs || []),
      typeof data.selection_metrics === 'string' ? data.selection_metrics : JSON.stringify(data.selection_metrics || {}),
      typeof data.metadata === 'string' ? data.metadata : JSON.stringify(data.metadata || {})
    ).run();

    return Response.json({ success: true, id: res.meta.last_row_id });
  } catch (err: any) {
    return Response.json({ error: err.message }, { status: 500 });
  }
};

export const onRequestPatch: PagesFunction<Env> = async ({ request, env }) => {
  try {
    const data = await request.json();
    if (!data.id && !data.ticker) {
      return Response.json({ error: 'id or ticker required' }, { status: 400 });
    }

    let sql = 'UPDATE positions SET ';
    const updates: string[] = [];
    const params: any[] = [];

    if (data.is_active !== undefined) {
      updates.push('is_active = ?');
      params.push(data.is_active ? 1 : 0);
    }
    if (data.closed_at) {
      updates.push('closed_at = ?');
      params.push(data.closed_at);
    }
    if (data.close_reason) {
      updates.push('close_reason = ?');
      params.push(data.close_reason);
    }
    if (data.metadata) {
      updates.push('metadata = ?');
      params.push(typeof data.metadata === 'string' ? data.metadata : JSON.stringify(data.metadata));
    }

    if (updates.length === 0) {
      return Response.json({ error: 'No fields to update' }, { status: 400 });
    }

    sql += updates.join(', ');

    if (data.id) {
      sql += ' WHERE id = ?';
      params.push(data.id);
    } else {
      sql += ' WHERE ticker = ? AND is_active = 1';
      params.push(data.ticker);
    }

    await env.DB.prepare(sql).bind(...params).run();
    return Response.json({ success: true });
  } catch (err: any) {
    return Response.json({ error: err.message }, { status: 500 });
  }
};

export const onRequestGet: PagesFunction<Env> = async ({ request, env }) => {
  try {
    const url = new URL(request.url);
    const active = url.searchParams.get('active');

    let sql = 'SELECT * FROM positions';
    const params: any[] = [];

    if (active === 'true' || active === '1') {
      sql += ' WHERE is_active = 1';
    } else if (active === 'false' || active === '0') {
      sql += ' WHERE is_active = 0';
    }

    sql += ' ORDER BY opened_at DESC';
    const result = await env.DB.prepare(sql).bind(...params).all();
    return Response.json(result.results || []);
  } catch (err: any) {
    return Response.json({ error: err.message }, { status: 500 });
  }
};
