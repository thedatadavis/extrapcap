interface Env {
  DB: any;
  API_TOKEN: string;
}

export const onRequest: PagesFunction<Env> = async (context) => {
  // Allow GET requests on public endpoints without token if requested, or require Bearer token for API mutations
  const auth = context.request.headers.get('Authorization');
  const path = new URL(context.request.url).pathname;

  // Protect all API POST/PATCH/DELETE calls with Bearer API_TOKEN
  if (['POST', 'PATCH', 'PUT', 'DELETE'].includes(context.request.method)) {
    if (!auth || auth !== `Bearer ${context.env.API_TOKEN}`) {
      return new Response(JSON.stringify({ error: 'Unauthorized' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      });
    }
  }

  return context.next();
};
