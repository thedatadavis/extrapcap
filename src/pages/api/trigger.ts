import type { APIRoute } from 'astro';

export const POST: APIRoute = async ({ request, locals, cookies }) => {
  try {
    // Check admin authentication cookie
    const authCookie = cookies.get('xpc_admin');
    if (!authCookie?.value || authCookie.value !== 'authenticated') {
      return new Response(JSON.stringify({ error: 'Unauthorized: Admin authentication required' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    const db = (locals as any).runtime?.env?.DB;
    if (!db) {
      return new Response(JSON.stringify({ error: 'Database binding not available' }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    const body = await request.json();
    const workflow = body.workflow;
    if (!workflow) {
      return new Response(JSON.stringify({ error: 'Workflow parameter required' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    const runId = `admin-${workflow}-${Date.now()}`;
    const startedAt = new Date().toISOString();
    const summary = JSON.stringify({
      triggered_by: 'admin_console',
      parameters: body.parameters || {},
      user_agent: request.headers.get('user-agent') || 'admin_ui',
    });

    // Store run metadata in D1 runs table
    const stmt = db.prepare(`
      INSERT INTO runs (run_id, workflow, status, started_at, summary)
      VALUES (?, ?, ?, ?, ?)
    `);
    await stmt.bind(runId, workflow, 'triggered', startedAt, summary).run();

    return new Response(JSON.stringify({
      success: true,
      run_id: runId,
      workflow,
      status: 'triggered',
      started_at: startedAt,
      message: `Workflow ${workflow} triggered successfully. Metadata logged to D1.`,
    }), {
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (err: any) {
    return new Response(JSON.stringify({ error: err.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json' },
    });
  }
};
