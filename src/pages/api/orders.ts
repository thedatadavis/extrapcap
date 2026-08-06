import type { APIRoute } from 'astro';

export const POST: APIRoute = async ({ request, locals }) => {
  try {
    const db = (locals as any).runtime?.env?.DB;
    if (!db) return new Response(JSON.stringify({ error: 'DB not available' }), { status: 500 });

    const data = await request.json();
    const stmt = db.prepare(`
      INSERT INTO order_registry
      (client_order_id, provider_order_id, trading_day, ticker, status, order_type, side, qty, limit_price, filled_qty, filled_avg_price, submitted_at, payload)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);

    await stmt.bind(
      data.client_order_id,
      data.provider_order_id || null,
      data.trading_day || new Date().toISOString().split('T')[0],
      data.ticker,
      data.status || 'submitted',
      data.order_type || 'limit',
      data.side || 'sell',
      data.qty || 1,
      data.limit_price || null,
      data.filled_qty || 0,
      data.filled_avg_price || null,
      data.submitted_at || new Date().toISOString(),
      typeof data.payload === 'string' ? data.payload : JSON.stringify(data)
    ).run();

    return new Response(JSON.stringify({ success: true, client_order_id: data.client_order_id }), {
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err: any) {
    return new Response(JSON.stringify({ error: err.message }), { status: 500 });
  }
};
