import type { APIRoute } from 'astro';

export const GET: APIRoute = async ({ request, locals }) => {
  try {
    const db = (locals as any).runtime?.env?.DB;
    if (!db) return new Response(JSON.stringify([]), { headers: { 'Content-Type': 'application/json' } });

    const url = new URL(request.url);
    const symbol = url.searchParams.get('symbol');
    const type = url.searchParams.get('type');
    const date = url.searchParams.get('date');

    let sql = 'SELECT * FROM risk_events WHERE 1=1';
    const params: any[] = [];

    if (symbol) {
      sql += ' AND symbol = ?';
      params.push(symbol.toUpperCase());
    }
    if (type) {
      sql += ' AND event_type = ?';
      params.push(type);
    }
    if (date) {
      sql += ' AND event_date = ?';
      params.push(date);
    }

    sql += ' ORDER BY event_date DESC LIMIT 500';

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
    const events = Array.isArray(payload) ? payload : [payload];

    const stmt = db.prepare(`
      INSERT INTO risk_events (symbol, event_type, event_date, headline, veto_reason)
      VALUES (?, ?, ?, ?, ?)
    `);

    const batch = events.map((e: any) => stmt.bind(
      String(e.symbol || e.ticker).toUpperCase(),
      e.event_type || e.type || 'news',
      e.event_date || e.date || new Date().toISOString().split('T')[0],
      e.headline || null,
      e.veto_reason || e.reason || null
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
