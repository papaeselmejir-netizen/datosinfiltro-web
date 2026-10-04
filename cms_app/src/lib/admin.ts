import { timingSafeEqual } from 'crypto';
import { NextResponse } from 'next/server';

function equalSecret(actual: string, expected: string): boolean {
  const left = Buffer.from(actual);
  const right = Buffer.from(expected);
  return left.length === right.length && timingSafeEqual(left, right);
}

export function requireAdmin(request: Request): NextResponse | null {
  const password = process.env.CMS_ADMIN_PASSWORD;
  if (!password) {
    return NextResponse.json({ success: false, error: 'Configure CMS_ADMIN_PASSWORD' }, { status: 503 });
  }
  const header = request.headers.get('authorization') || '';
  const encoded = header.startsWith('Basic ') ? header.slice(6) : '';
  let credentials = '';
  try {
    credentials = Buffer.from(encoded, 'base64').toString('utf8');
  } catch {
    // A malformed authorization header is handled like a missing one.
  }
  if (!credentials.startsWith('editor:') || !equalSecret(credentials.slice(7), password)) {
    return NextResponse.json({ success: false, error: 'No autorizado' }, {
      status: 401,
      headers: { 'WWW-Authenticate': 'Basic realm="DatoSinFiltro CMS"' },
    });
  }
  if (request.method !== 'GET') {
    const origin = request.headers.get('origin');
    if (origin && origin !== new URL(request.url).origin) {
      return NextResponse.json({ success: false, error: 'Origen no permitido' }, { status: 403 });
    }
  }
  return null;
}
