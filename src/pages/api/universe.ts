import type { APIRoute } from 'astro';

export const GET: APIRoute = async ({ request, locals }) => {
  try {
    const db = (locals as any).runtime?.env?.DB;
    if (!db) return new Response(JSON.stringify([]), { headers: { 'Content-Type': 'application/json' } });

    const url = new URL(request.url);
    const sector = url.searchParams.get('sector');
    const symbol = url.searchParams.get('symbol');

    let sql = 'SELECT * FROM universe WHERE 1=1';
    const params: any[] = [];

    if (symbol) {
      sql += ' AND symbol = ?';
      params.push(symbol.toUpperCase());
    }
    if (sector) {
      sql += ' AND sector = ?';
      params.push(sector);
    }

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
    const rows = Array.isArray(payload) ? payload : [payload];

    const stmt = db.prepare(`
      INSERT OR REPLACE INTO universe
      (symbol, sector, avg_volume, market_cap, cap_tier, exchange, weekly_options, penny_pricing, options_volume)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);

    const batch = rows.map((r: any) => stmt.bind(
      String(r.symbol || r.ticker).toUpperCase(),
      r.sector || 'Unknown',
      r.avg_volume ?? null,
      r.market_cap ?? null,
      r.cap_tier || null,
      r.exchange || null,
      r.weekly_options ? 1 : 0,
      r.penny_pricing ? 1 : 0,
      r.options_volume ?? null
    ));

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
