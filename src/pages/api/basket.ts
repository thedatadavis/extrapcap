import type { APIRoute } from 'astro';

export const POST: APIRoute = async ({ request, locals }) => {
  try {
    const db = (locals as any).runtime?.env?.DB;
    if (!db) return new Response(JSON.stringify({ error: 'DB not available' }), { status: 500 });

    const data = await request.json();
    const asOf = data.as_of || new Date().toISOString().split('T')[0];
    const rows = data.rows || [];

    const stmt = db.prepare(`
      INSERT OR REPLACE INTO tradable_baskets (as_of, symbol, relative_return, streak_length, robust_z, payload)
      VALUES (?, ?, ?, ?, ?, ?)
    `);

    const batch = rows.map((r: any) =>
      stmt.bind(
        asOf,
        r.symbol || r.ticker,
        r.relative_return || 0.0,
        r.streak_length || 0,
        r.robust_z || 0.0,
        typeof r === 'string' ? r : JSON.stringify(r)
      )
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
