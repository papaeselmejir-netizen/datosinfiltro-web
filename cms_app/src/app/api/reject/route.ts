import { NextResponse } from 'next/server';
import fs from 'fs';
import { requireAdmin } from '@/lib/admin';
import { message, resolveDraft } from '@/lib/drafts';

export async function POST(request: Request) {
  const denied = requireAdmin(request);
  if (denied) return denied;
  try {
    const { id } = await request.json();
    const file = resolveDraft(id);
    if (!file) return NextResponse.json({ success: false, error: 'ID inválido' }, { status: 400 });
    if (!fs.existsSync(file)) return NextResponse.json({ success: false, error: 'Borrador no encontrado' }, { status: 404 });
    fs.unlinkSync(file);
    return NextResponse.json({ success: true });
  } catch (error: unknown) {
    return NextResponse.json({ success: false, error: message(error) }, { status: 500 });
  }
}
