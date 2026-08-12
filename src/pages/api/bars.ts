import type { APIRoute } from 'astro';

const JSON_NO_STORE = { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' };

export const GET: APIRoute = async ({ request, locals }) => {
  try {
    const db = (locals as any).runtime?.env?.DB;
    if (!db) return new Response(JSON.stringify([]), { headers: JSON_NO_STORE });

    const url = new URL(request.url);
    const symbol = url.searchParams.get('symbol');
    const limit = parseInt(url.searchParams.get('limit') || '5000', 10);

    let sql = 'SELECT * FROM bars';
    const params: any[] = [];

    if (symbol) {
      sql += ' WHERE symbol = ?';
      params.push(symbol.toUpperCase());
    }

    sql += ' ORDER BY date ASC LIMIT ?';
    params.push(limit);

    const result = await db.prepare(sql).bind(...params).all();
    return new Response(JSON.stringify(result.results || []), {
      headers: JSON_NO_STORE,
    });
  } catch (err: any) {
    return new Response(JSON.stringify({ error: err.message }), { status: 500, headers: JSON_NO_STORE });
  }
};

export const POST: APIRoute = async ({ request, locals }) => {
  try {
    const db = (locals as any).runtime?.env?.DB;
    if (!db) return new Response(JSON.stringify({ error: 'DB not available' }), { status: 500 });

    const payload = await request.json();
    const bars = Array.isArray(payload) ? payload : [payload];

    const stmt = db.prepare(`
      INSERT OR REPLACE INTO bars (date, symbol, open, high, low, close, volume, vwap)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `);

    const batch = bars.map((b: any) =>
      stmt.bind(b.date, b.symbol, b.open, b.high, b.low, b.close, b.volume || 0, b.vwap || null)
    );

    if (batch.length > 0) {
      await db.batch(batch);
    }

    return new Response(JSON.stringify({ success: true, count: batch.length }), {
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err: any) {
    return new Response(JSON.stringify({ error: err.message }), { status: 500 });
  }
};
