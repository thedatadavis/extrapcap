interface Env {
  DB: any;
}

const NO_STORE = { 'Cache-Control': 'no-store' };

export const onRequestGet: PagesFunction<Env> = async ({ request, env }) => {
  try {
    const url = new URL(request.url);
    const unresolved = url.searchParams.get('unresolved');
    const workflow = url.searchParams.get('workflow');
    const runId = url.searchParams.get('run_id');
    const limit = parseInt(url.searchParams.get('limit') || '50', 10);

    let sql = 'SELECT * FROM error_logs';
    const conditions: string[] = [];
    const params: any[] = [];

    if (unresolved === 'true' || unresolved === '1') {
      conditions.push('is_resolved = 0');
    }
    if (workflow) {
      conditions.push('workflow = ?');
      params.push(workflow);
    }
    if (runId) {
      conditions.push('run_id = ?');
      params.push(runId);
    }

    if (conditions.length > 0) {
      sql += ' WHERE ' + conditions.join(' AND ');
    }

    sql += ' ORDER BY created_at DESC LIMIT ?';
    params.push(limit);

    const result = await env.DB.prepare(sql).bind(...params).all();
    return Response.json(result.results || [], { headers: NO_STORE });
  } catch (err: any) {
    return Response.json({ error: err.message }, { status: 500, headers: NO_STORE });
  }
};

export const onRequestPost: PagesFunction<Env> = async ({ request, env }) => {
  try {
    const data = await request.json();
    if (!data.workflow || !data.error_message) {
      return Response.json({ error: 'workflow and error_message are required' }, { status: 400 });
    }

    const now = data.created_at || new Date().toISOString();
    const contextStr = data.context
      ? (typeof data.context === 'string' ? data.context : JSON.stringify(data.context))
      : null;

    const stmt = env.DB.prepare(`
      INSERT INTO error_logs (
        workflow, run_id, error_type, error_message,
        stack_trace, context, severity, is_resolved, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
    `);

    const result = await stmt.bind(
      data.workflow,
      data.run_id || null,
      data.error_type || null,
      data.error_message,
      data.stack_trace || null,
      contextStr,
      data.severity || 'error',
      now
    ).run();

    return Response.json({
      success: true,
      id: result.meta?.last_row_id || null,
    });
  } catch (err: any) {
    return Response.json({ error: err.message }, { status: 500 });
  }
};

export const onRequestPatch: PagesFunction<Env> = async ({ request, env }) => {
  try {
    const data = await request.json();
    if (!data.id) {
      return Response.json({ error: 'id required' }, { status: 400 });
    }

    const now = new Date().toISOString();
    const isResolved = data.is_resolved !== undefined ? (data.is_resolved ? 1 : 0) : 1;
    const resolvedAt = isResolved ? (data.resolved_at || now) : null;

    let sql = 'UPDATE error_logs SET is_resolved = ?, resolved_at = ?';
    const params: any[] = [isResolved, resolvedAt];

    if (data.resolution_notes !== undefined) {
      sql += ', resolution_notes = ?';
      params.push(data.resolution_notes);
    }
    if (data.resolved_by !== undefined) {
      sql += ', resolved_by = ?';
      params.push(data.resolved_by);
    }

    sql += ' WHERE id = ?';
    params.push(data.id);

    await env.DB.prepare(sql).bind(...params).run();
    return Response.json({ success: true });
  } catch (err: any) {
    return Response.json({ error: err.message }, { status: 500 });
  }
};
