interface Env {
  DB: any;
}

export const onRequestPost: PagesFunction<Env> = async ({ request, env }) => {
  try {
    const data = await request.json();
    const stmt = env.DB.prepare(`
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

    return Response.json({ success: true });
  } catch (err: any) {
    return Response.json({ error: err.message }, { status: 500 });
  }
};

export const onRequestGet: PagesFunction<Env> = async ({ request, env }) => {
  try {
    const result = await env.DB.prepare(
      'SELECT as_of as date, equity as balance, cash, buying_power as buyingPower, portfolio_value, daily_pnl FROM account_snapshots ORDER BY as_of ASC'
    ).all();

    return Response.json(result.results || []);
  } catch (err: any) {
    return Response.json({ error: err.message }, { status: 500 });
  }
};
