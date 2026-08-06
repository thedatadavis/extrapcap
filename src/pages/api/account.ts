import type { APIRoute } from 'astro';

export const GET: APIRoute = async ({ locals }) => {
  try {
    const db = (locals as any).runtime?.env?.DB;
    if (!db) return new Response(JSON.stringify([]), { headers: { 'Content-Type': 'application/json' } });

    const result = await db.prepare(
      'SELECT as_of as date, equity as balance, cash, buying_power as buyingPower, portfolio_value, daily_pnl FROM account_snapshots ORDER BY as_of ASC'
    ).all();

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
    const stmt = db.prepare(`
      INSERT INTO account_snapshots
      (as_of, equity, cash, buying_power, portfolio_value, daily_pnl, payload)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `);

    await stmt.bind(
      data.as_of || new Date().toISOString().split('T')[0],
      data.equity ?? data.portfolio_value ?? 0.0,
      data.cash ?? 0.0,
      data.buying_power ?? 0.0,
      data.portfolio_value ?? data.equity ?? 0.0,
      data.daily_pnl ?? 0.0,
      typeof data.payload === 'string' ? data.payload : JSON.stringify(data)
    ).run();

    return new Response(JSON.stringify({ success: true }), {
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err: any) {
    return new Response(JSON.stringify({ error: err.message }), { status: 500 });
  }
};
