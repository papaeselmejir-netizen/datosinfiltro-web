import { NextResponse } from 'next/server';
import path from 'path';
import { exec } from 'child_process';
import util from 'util';

const execPromise = util.promisify(exec);
const BASE_DIR = path.join(process.cwd(), '../');

export async function POST(req: Request) {
  try {
    const { topic } = await req.json();
    if (!topic) return NextResponse.json({ success: false, error: 'Tema requerido' }, { status: 400 });

    // Ejecutar main.py con el tema específico
    // En Windows se debe escapar las comillas si el tema tiene espacios
    const command = `python main.py --topic "${topic.replace(/"/g, '\\"')}"`;
    
    console.log(`Ejecutando: ${command}`);
    const { stdout, stderr } = await execPromise(command, { cwd: BASE_DIR });
    console.log('Generate Output:', stdout);

    return NextResponse.json({ success: true, message: 'Borrador generado correctamente' });
  } catch (error: any) {
    console.error('Generate Error:', error);
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}
