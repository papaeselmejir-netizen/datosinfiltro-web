import { NextResponse } from 'next/server';
import { execFile } from 'child_process';
import { promisify } from 'util';
import { requireAdmin } from '@/lib/admin';
import { BASE_DIR, message } from '@/lib/drafts';

const run = promisify(execFile);

export async function POST(request: Request) {
  const denied = requireAdmin(request);
  if (denied) return denied;
  try {
    const { topic } = await request.json();
    if (typeof topic !== 'string' || topic.trim().length < 3 || topic.length > 160) {
      return NextResponse.json({ success: false, error: 'Tema inválido' }, { status: 400 });
    }
    await run(process.env.PYTHON_BIN || 'python', ['main.py', '--topic', topic.trim()], {
      cwd: BASE_DIR, timeout: 240_000, maxBuffer: 4 * 1024 * 1024,
    });
    return NextResponse.json({ success: true, message: 'Búsqueda terminada; revise los borradores' });
  } catch (error: unknown) {
    return NextResponse.json({ success: false, error: message(error) }, { status: 500 });
  }
}
