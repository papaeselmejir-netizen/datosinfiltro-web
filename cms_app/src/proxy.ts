import { NextResponse, type NextRequest } from 'next/server';

export function proxy(request: NextRequest) {
  const password = process.env.CMS_ADMIN_PASSWORD;
  if (!password) return new NextResponse('Configure CMS_ADMIN_PASSWORD', { status: 503 });
  const auth = request.headers.get('authorization') || '';
  let credentials = '';
  try {
    credentials = atob(auth.startsWith('Basic ') ? auth.slice(6) : '');
  } catch {
    // Browser will prompt again.
  }
  if (credentials !== `editor:${password}`) {
    return new NextResponse('Acceso restringido', {
      status: 401,
      headers: { 'WWW-Authenticate': 'Basic realm="DatoSinFiltro CMS"' },
    });
  }
  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
