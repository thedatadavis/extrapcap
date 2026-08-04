interface Env {
  DB: any;
}

export const onRequestPost: PagesFunction<Env> = async ({ request, env }) => {
  try {
    const data = await request.json();
    const stmt = env.DB.prepare(`
      INSERT INTO runs (run_id, workflow, status, started_at)
      VALUES (?, ?, ?, ?)
    `);

    await stmt.bind(
      data.run_id,
      data.workflow,
      data.status || 'running',
      data.started_at || new Date().toISOString()
    ).run();

    return Response.json({ success: true, run_id: data.run_id });
  } catch (err: any) {
    return Response.json({ error: err.message }, { status: 500 });
  }
};

export const onRequestPatch: PagesFunction<Env> = async ({ request, env }) => {
  try {
    const data = await request.json();
    if (!data.run_id && !data.id) {
      return Response.json({ error: 'run_id required' }, { status: 400 });
    }

    let sql = 'UPDATE runs SET status = ?, finished_at = ?';
    const params: any[] = [
      data.status || 'completed',
      data.finished_at || new Date().toISOString(),
    ];

    if (data.duration_s !== undefined) {
      sql += ', duration_s = ?';
      params.push(data.duration_s);
    }
    if (data.summary) {
      sql += ', summary = ?';
      params.push(typeof data.summary === 'string' ? data.summary : JSON.stringify(data.summary));
    }
    if (data.error) {
      sql += ', error = ?';
      params.push(data.error);
    }

    sql += data.run_id ? ' WHERE run_id = ?' : ' WHERE id = ?';
    params.push(data.run_id || data.id);

    await env.DB.prepare(sql).bind(...params).run();
    return Response.json({ success: true });
  } catch (err: any) {
    return Response.json({ error: err.message }, { status: 500 });
  }
};

export const onRequestGet: PagesFunction<Env> = async ({ request, env }) => {
  try {
    const url = new URL(request.url);
    const workflow = url.searchParams.get('workflow');
    const limit = parseInt(url.searchParams.get('limit') || '50', 10);

    let sql = 'SELECT * FROM runs';
    const params: any[] = [];

    if (workflow) {
      sql += ' WHERE workflow = ?';
      params.push(workflow);
    }

    sql += ' ORDER BY started_at DESC LIMIT ?';
    params.push(limit);

    const result = await env.DB.prepare(sql).bind(...params).all();
    return Response.json(result.results || []);
  } catch (err: any) {
    return Response.json({ error: err.message }, { status: 500 });
  }
};
