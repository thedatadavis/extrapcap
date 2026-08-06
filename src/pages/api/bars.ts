import type { APIRoute } from 'astro';

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

    await db.batch(batch);
    return new Response(JSON.stringify({ success: true, count: batch.length }), {
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err: any) {
    return new Response(JSON.stringify({ error: err.message }), { status: 500 });
  }
};
