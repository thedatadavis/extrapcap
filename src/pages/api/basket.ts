import type { APIRoute } from 'astro';

export const GET: APIRoute = async ({ request, locals }) => {
  try {
    const db = (locals as any).runtime?.env?.DB;
    if (!db) return new Response(JSON.stringify([]), { headers: { 'Content-Type': 'application/json' } });

    const url = new URL(request.url);
    const date = url.searchParams.get('as_of');

    let sql = 'SELECT * FROM basket';
    const params: any[] = [];

    if (date) {
      sql += ' WHERE as_of = ?';
      params.push(date);
    } else {
      sql += ' WHERE as_of = (SELECT MAX(as_of) FROM basket)';
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

    const data = await request.json();
    const as_of = data.as_of || new Date().toISOString().split('T')[0];
    const rows = Array.isArray(data.rows) ? data.rows : (Array.isArray(data) ? data : []);

    const stmt = db.prepare(`
      INSERT OR REPLACE INTO basket
      (as_of, symbol, sector, robust_z, signed_streak, streak_length, streak_direction, features)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `);

    const batch = rows.map((r: any) => stmt.bind(
      as_of,
      r.symbol || r.ticker,
      r.sector || null,
      r.robust_z ?? null,
      r.signed_streak ?? null,
      r.streak_length ?? null,
      r.streak_direction || null,
      typeof r.features === 'string' ? r.features : JSON.stringify(r.features || r)
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
