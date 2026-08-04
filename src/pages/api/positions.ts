import type { APIRoute } from 'astro';
import { getActivePositions } from '../../data/positions';

export const GET: APIRoute = async ({ locals }) => {
  const db = (locals as any).runtime?.env?.DB;
  const positions = await getActivePositions(db);

  return new Response(
    JSON.stringify({
      timestamp: new Date().toISOString(),
      count: positions.length,
      positions,
    }),
    {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
      },
    }
  );
};
