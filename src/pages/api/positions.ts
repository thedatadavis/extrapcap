import type { APIRoute } from 'astro';
import { ACTIVE_POSITIONS } from '../../data/positions';

export const GET: APIRoute = async () => {
  return new Response(
    JSON.stringify({
      timestamp: new Date().toISOString(),
      count: ACTIVE_POSITIONS.length,
      positions: ACTIVE_POSITIONS,
    }),
    {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
      },
    }
  );
};
