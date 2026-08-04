interface Env {
  DB: any;
}

export const onRequestPost: PagesFunction<Env> = async ({ request, env }) => {
  try {
    const data = await request.json();
    const as_of = data.as_of || new Date().toISOString().split('T')[0];
    const rows = Array.isArray(data.rows) ? data.rows : (Array.isArray(data) ? data : []);

    const stmt = env.DB.prepare(`
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
      typeof r.features === 'string' ? r.features : JSON.stringify(r.features || {})
    ));

    await env.DB.batch(batch);
    return Response.json({ success: true, count: batch.length });
  } catch (err: any) {
    return Response.json({ error: err.message }, { status: 500 });
  }
};

export const onRequestGet: PagesFunction<Env> = async ({ request, env }) => {
  try {
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

    const result = await env.DB.prepare(sql).bind(...params).all();
    return Response.json(result.results || []);
  } catch (err: any) {
    return Response.json({ error: err.message }, { status: 500 });
  }
};
