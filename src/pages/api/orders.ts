import type { APIRoute } from 'astro';

const NO_STORE = { 'Cache-Control': 'no-store' };

function database(locals: any): any {
  const db = locals.runtime?.env?.DB;
  if (!db) throw new Error('DB not available');
  return db;
}

export const POST: APIRoute = async ({ request, locals }) => {
  try {
    const data = await request.json();
    const stmt = database(locals).prepare(`
      INSERT OR REPLACE INTO orders
      (client_order_id, run_id, signal_id, broker_order_id, ticker, sleeve, side, strategy_variant, limit_price, quantity, legs, metadata, execution_status, submitted_at, filled_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);
    await stmt.bind(
      data.client_order_id,
      data.run_id || null,
      data.signal_id || null,
      data.broker_order_id || null,
      data.ticker,
      data.sleeve || 'core',
      data.side || 'sell_to_open',
      data.strategy_variant || 'core_mean_reversion',
      data.limit_price ?? null,
      data.quantity || 1,
      typeof data.legs === 'string' ? data.legs : JSON.stringify(data.legs || []),
      typeof data.metadata === 'string' ? data.metadata : JSON.stringify(data.metadata || {}),
      data.execution_status || 'submitted',
      data.submitted_at || new Date().toISOString(),
      data.filled_at || null,
    ).run();
    return Response.json({ success: true, client_order_id: data.client_order_id });
  } catch (error: any) {
    return Response.json({ error: error.message }, { status: 500 });
  }
};

export const PATCH: APIRoute = async ({ request, locals }) => {
  try {
    const data = await request.json();
    if (!data.client_order_id) return Response.json({ error: 'client_order_id required' }, { status: 400 });
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
    await database(locals).prepare(sql).bind(...params).run();
    return Response.json({ success: true });
  } catch (error: any) {
    return Response.json({ error: error.message }, { status: 500 });
  }
};

export const GET: APIRoute = async ({ request, locals }) => {
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
    const result = await database(locals).prepare(sql).bind(...params).all();
    if (!Array.isArray(result.results)) throw new Error('D1 returned an invalid orders result');
    return Response.json(result.results, { headers: NO_STORE });
  } catch (error: any) {
    return Response.json({ error: error.message }, { status: 500, headers: NO_STORE });
  }
};
