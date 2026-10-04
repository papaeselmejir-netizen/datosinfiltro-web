import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import { requireAdmin } from '@/lib/admin';
import { DRAFTS_DIR, listDraftFiles, message } from '@/lib/drafts';
import { type ArticleDraft, validationErrors } from '@/lib/validation';

export async function GET(request: Request) {
  const denied = requireAdmin(request);
  if (denied) return denied;
  try {
    const drafts = listDraftFiles().map(file => {
      const data = JSON.parse(fs.readFileSync(file, 'utf8')) as ArticleDraft;
      return {
        id: path.relative(DRAFTS_DIR, file).replace(/\\/g, '/'),
        titulo: data.titulo_articulo || 'Sin título',
        fecha: data.fecha_creacion || '',
        categoria: data.categoria || '',
        region: data.region || '',
        imagen_url: data.imagen_url || '',
        fuentes: data.fuentes?.length || 0,
        imagenes: data.imagenes?.length || 0,
        video: Boolean(data.video_url),
        errores: validationErrors(data),
      };
    });
    return NextResponse.json({ success: true, drafts });
  } catch (error: unknown) {
    return NextResponse.json({ success: false, error: message(error) }, { status: 500 });
  }
}
