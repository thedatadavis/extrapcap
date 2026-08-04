export const POST: APIRoute = async ({ cookies, redirect }) => {
  cookies.delete('xpc_admin', { path: '/' });
  return redirect('/admin/login');
};
