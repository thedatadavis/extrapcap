interface Env {
  DB: any;
}

export const onRequestPost: PagesFunction<Env> = async ({ request, env }) => {
  try {
    const data = await request.json();
    const stmt = env.DB.prepare(`
      INSERT OR REPLACE INTO orders
      (client_order_id, signal_id, broker_order_id, ticker, sleeve, side, strategy_variant, limit_price, quantity, legs, metadata, execution_status, submitted_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);

    await stmt.bind(
      data.client_order_id,
      data.signal_id || null,
      data.broker_order_id || null,
      data.ticker,
      data.sleeve || 'core',
      data.side || 'sell_to_open',
      data.strategy_variant || 'fast_ev',
      data.limit_price || null,
      data.quantity || 1,
      typeof data.legs === 'string' ? data.legs : JSON.stringify(data.legs || []),
      typeof data.metadata === 'string' ? data.metadata : JSON.stringify(data.metadata || {}),
      data.execution_status || 'submitted',
      data.submitted_at || new Date().toISOString()
    ).run();

    return Response.json({ success: true, client_order_id: data.client_order_id });
  } catch (err: any) {
    return Response.json({ error: err.message }, { status: 500 });
  }
};

export const onRequestPatch: PagesFunction<Env> = async ({ request, env }) => {
  try {
    const data = await request.json();
    if (!data.client_order_id) {
      return Response.json({ error: 'client_order_id required' }, { status: 400 });
    }

    let sql = 'UPDATE orders SET execution_status = ?';
    const params: any[] = [data.execution_status];

    if (data.broker_order_id) {
      sql += ', broker_order_id = ?';
      params.push(data.broker_order_id);
    }
    if (data.filled_at) {
      sql += ', filled_at = ?';
      params.push(data.filled_at);
    }

    sql += ' WHERE client_order_id = ?';
    params.push(data.client_order_id);

    await env.DB.prepare(sql).bind(...params).run();
    return Response.json({ success: true });
  } catch (err: any) {
    return Response.json({ error: err.message }, { status: 500 });
  }
};

export const onRequestGet: PagesFunction<Env> = async ({ request, env }) => {
  try {
    const url = new URL(request.url);
    const status = url.searchParams.get('status');
    const ticker = url.searchParams.get('ticker');

    let sql = 'SELECT * FROM orders WHERE 1=1';
    const params: any[] = [];

    if (status) {
      sql += ' AND execution_status = ?';
      params.push(status);
    }
    if (ticker) {
      sql += ' AND ticker = ?';
      params.push(ticker);
    }

    sql += ' ORDER BY created_at DESC LIMIT 200';
    const result = await env.DB.prepare(sql).bind(...params).all();
    return Response.json(result.results || []);
  } catch (err: any) {
    return Response.json({ error: err.message }, { status: 500 });
  }
};
