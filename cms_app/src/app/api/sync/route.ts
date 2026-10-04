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
    const { stdout } = await run('git', ['pull', '--ff-only'], { cwd: BASE_DIR, timeout: 30_000 });
    return NextResponse.json({ success: true, output: stdout });
  } catch (error: unknown) {
    return NextResponse.json({ success: false, error: message(error) }, { status: 500 });
  }
}
