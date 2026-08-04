interface Env {
  DB: any;
}

export const onRequestPost: PagesFunction<Env> = async ({ request, env }) => {
  try {
    const payload = await request.json();
    const bars = Array.isArray(payload) ? payload : [payload];

    const stmt = env.DB.prepare(`
      INSERT OR REPLACE INTO bars (date, symbol, open, high, low, close, volume, vwap)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `);

    // D1 batch limit per query is 100 statements
    const chunkSize = 100;
    let total = 0;

    for (let i = 0; i < bars.length; i += chunkSize) {
      const chunk = bars.slice(i, i + chunkSize);
      const batch = chunk.map((b: any) =>
        stmt.bind(b.date, b.symbol, b.open, b.high, b.low, b.close, b.volume, b.vwap ?? null)
      );
      await env.DB.batch(batch);
      total += chunk.length;
    }

    return Response.json({ success: true, count: total });
  } catch (err: any) {
    return Response.json({ error: err.message }, { status: 500 });
  }
};

export const onRequestGet: PagesFunction<Env> = async ({ request, env }) => {
  try {
    const url = new URL(request.url);
    const symbol = url.searchParams.get('symbol');
    const limit = parseInt(url.searchParams.get('limit') || '365', 10);

    if (!symbol) {
      return Response.json({ error: 'symbol query param required' }, { status: 400 });
    }

    const result = await env.DB.prepare(
      'SELECT * FROM bars WHERE symbol = ? ORDER BY date DESC LIMIT ?'
    ).bind(symbol, limit).all();

    return Response.json(result.results || []);
  } catch (err: any) {
    return Response.json({ error: err.message }, { status: 500 });
  }
};
