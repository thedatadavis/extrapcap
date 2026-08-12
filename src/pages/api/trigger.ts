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
    const allowedWorkflows = new Set([
      'candidate_review',
      'position_management',
      'reconciliation',
      'daily_report',
      'data_refresh',
      'streak_screen',
    ]);
    if (!workflow || !allowedWorkflows.has(workflow)) {
      return new Response(JSON.stringify({ error: 'Supported workflow parameter required' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    const env = (locals as any).runtime?.env;
    const modalUrl = env?.MODAL_TRIGGER_URL;
    const modalToken = env?.MODAL_TRIGGER_TOKEN;
    if (!modalUrl || !modalToken) {
      return new Response(JSON.stringify({ error: 'Modal admin trigger is not configured' }), {
        status: 503,
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

    const modalResponse = await fetch(modalUrl, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${modalToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ workflow }),
    });
    const modalText = await modalResponse.text();
    let dispatch: any = {};
    try {
      dispatch = modalText ? JSON.parse(modalText) : {};
    } catch {
      dispatch = { detail: modalText };
    }
    if (!modalResponse.ok || !dispatch.accepted) {
      const error = dispatch.detail || dispatch.error || `Modal dispatch failed with HTTP ${modalResponse.status}`;
      await db.prepare(`
        UPDATE runs SET status = 'failed', finished_at = ?, error = ? WHERE run_id = ?
      `).bind(new Date().toISOString(), String(error), runId).run();
      return new Response(JSON.stringify({ error }), {
        status: 502,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    const dispatchedSummary = JSON.stringify({
      ...JSON.parse(summary),
      modal_function_call_id: dispatch.function_call_id,
    });
    await db.prepare('UPDATE runs SET summary = ? WHERE run_id = ?').bind(dispatchedSummary, runId).run();

    return new Response(JSON.stringify({
      success: true,
      run_id: runId,
      workflow,
      status: 'triggered',
      modal_function_call_id: dispatch.function_call_id,
      started_at: startedAt,
      message: `Workflow ${workflow} was accepted by Modal.`,
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
