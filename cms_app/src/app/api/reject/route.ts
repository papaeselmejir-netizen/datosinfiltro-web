import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

const DRAFTS_DIR = path.join(process.cwd(), '../drafts');

export async function POST(req: Request) {
  try {
    const { id } = await req.json();
    if (!id) return NextResponse.json({ success: false, error: 'ID requerido' }, { status: 400 });

    const targetPath = path.join(DRAFTS_DIR, id);

    // Asegurar que el archivo exista
    if (!fs.existsSync(targetPath)) {
      return NextResponse.json({ success: false, error: 'El borrador no existe' }, { status: 404 });
    }

    // Eliminar el archivo (Rechazar)
    fs.unlinkSync(targetPath);

    return NextResponse.json({ success: true, message: 'Borrador eliminado correctamente' });
  } catch (error: any) {
    console.error('Reject Error:', error);
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}
