import { NextResponse } from 'next/server';
import { exec } from 'child_process';
import util from 'util';
import path from 'path';

const execPromise = util.promisify(exec);
const BASE_DIR = path.resolve(process.cwd(), '..'); // Raíz del proyecto content_pipeline

export async function POST(request: Request) {
  try {
    // Sincronizar (git pull)
    const { stdout, stderr } = await execPromise('git pull', { cwd: BASE_DIR });
    console.log('Git Pull Output:', stdout);

    return NextResponse.json({ success: true, message: 'Nube sincronizada', output: stdout });
  } catch (error: any) {
    console.error('Sync Error:', error);
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}
