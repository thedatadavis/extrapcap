import type { APIRoute } from 'astro';

export const GET: APIRoute = async ({ request, locals }) => {
  try {
    const db = (locals as any).runtime?.env?.DB;
    if (!db) return new Response(JSON.stringify([]), { headers: { 'Content-Type': 'application/json' } });

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

    const data = await request.json();
    const now = new Date().toISOString();

    // Clean up any stale running/triggered runs for this workflow
    if (data.workflow) {
      try {
        await db.prepare(`
          UPDATE runs SET status = 'completed', finished_at = ?
          WHERE workflow = ? AND status IN ('running', 'triggered') AND run_id != ?
        `).bind(now, data.workflow, data.run_id || '').run();
      } catch (e) {
        // ignore cleanup error
      }
    }

    const stmt = db.prepare(`
      INSERT INTO runs (run_id, workflow, status, started_at)
      VALUES (?, ?, ?, ?)
    `);

    await stmt.bind(
      data.run_id,
      data.workflow,
      data.status || 'running',
      data.started_at || now
    ).run();

    return new Response(JSON.stringify({ success: true, run_id: data.run_id }), {
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err: any) {
    return new Response(JSON.stringify({ error: err.message }), { status: 500 });
  }
};

export const PATCH: APIRoute = async ({ request, locals }) => {
  try {
    const db = (locals as any).runtime?.env?.DB;
    if (!db) return new Response(JSON.stringify({ error: 'DB not available' }), { status: 500 });

    const data = await request.json();
    if (!data.run_id && !data.id) {
      return new Response(JSON.stringify({ error: 'run_id required' }), { status: 400 });
    }

    const now = new Date().toISOString();
    const targetStatus = data.status || 'completed';

    let sql = 'UPDATE runs SET status = ?, finished_at = ?';
    const params: any[] = [
      targetStatus,
      data.finished_at || now,
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

    await db.prepare(sql).bind(...params).run();

    // Auto-resolve any stale hanging runs for the same workflow if finishing
    if (data.workflow) {
      try {
        await db.prepare(`
          UPDATE runs SET status = ?, finished_at = ?
          WHERE workflow = ? AND status IN ('running', 'triggered') AND run_id != ?
        `).bind(targetStatus, now, data.workflow, data.run_id || '').run();
      } catch (e) {
        // ignore
      }
    }

    return new Response(JSON.stringify({ success: true }), {
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err: any) {
    return new Response(JSON.stringify({ error: err.message }), { status: 500 });
  }
};
