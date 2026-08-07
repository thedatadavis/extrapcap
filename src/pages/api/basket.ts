import type { APIRoute } from 'astro';

export const GET: APIRoute = async ({ request, locals }) => {
  try {
    const db = (locals as any).runtime?.env?.DB;
    if (!db) return new Response(JSON.stringify({ error: 'DB not available' }), { status: 500, headers: { 'Content-Type': 'application/json' } });

    const url = new URL(request.url);
    const date = url.searchParams.get('as_of');
    const runId = url.searchParams.get('run_id');

    let sql = 'SELECT * FROM basket';
    const params: any[] = [];

    if (runId) {
      sql += ' WHERE run_id = ?';
      params.push(runId);
    } else if (date) {
      sql += ' WHERE as_of = ?';
      params.push(date);
    } else return new Response(JSON.stringify({ error: 'as_of or run_id is required' }), { status: 400 });

    const result = await db.prepare(sql).bind(...params).all();
    return new Response(JSON.stringify(result.results || []), {
      headers: {
        'Content-Type': 'application/json',
        'Cache-Control': 'no-store',
      },
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
    if (!data.as_of || !data.run_id || !Array.isArray(data.rows) || data.rows.length === 0) return new Response(JSON.stringify({ error: 'as_of, run_id, and non-empty rows are required' }), { status: 400 });
    const as_of = data.as_of;
    const run_id = data.run_id;
    const rows = data.rows;

    const stmt = db.prepare(`
      INSERT OR REPLACE INTO basket
      (as_of, run_id, symbol, sector, robust_z, signed_streak, streak_length, streak_direction, features)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);

    const batch = rows.map((r: any) => stmt.bind(
      as_of,
      run_id,
      r.symbol || r.ticker,
      r.sector || null,
      r.robust_z ?? null,
      r.signed_streak ?? null,
      r.streak_length ?? null,
      r.streak_direction || null,
      JSON.stringify(r)
    ));

    if (batch.length > 0) {
      await db.batch(batch);
    }

    return new Response(JSON.stringify({ success: true, count: batch.length, run_id }), {
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err: any) {
    return new Response(JSON.stringify({ error: err.message }), { status: 500 });
  }
};
