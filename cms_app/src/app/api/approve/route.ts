import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import { randomUUID } from 'crypto';
import { execFile } from 'child_process';
import { promisify } from 'util';
import { requireAdmin } from '@/lib/admin';
import { CATEGORIES } from '@/lib/categories';
import { BASE_DIR, OUTPUT_DIR, message, resolveDraft } from '@/lib/drafts';
import { type ArticleDraft, validationErrors } from '@/lib/validation';

const run = promisify(execFile);
const publicDir = path.join(BASE_DIR, 'website', 'public');

function categoryFolder(category: string): string {
  return category.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^A-Za-z0-9]+/g, '_');
}

export async function POST(request: Request) {
  const denied = requireAdmin(request);
  if (denied) return denied;
  let destination = '';
  let stage = '';
  let backup = '';
  try {
    const { id, category } = await request.json();
    const source = resolveDraft(id);
    if (!source || !fs.existsSync(source)) {
      return NextResponse.json({ success: false, error: 'Borrador no encontrado' }, { status: 404 });
    }
    if (!CATEGORIES.includes(category)) {
      return NextResponse.json({ success: false, error: 'Categoría inválida' }, { status: 400 });
    }
    const article = JSON.parse(fs.readFileSync(source, 'utf8')) as ArticleDraft;
    article.categoria = category;
    const errors = validationErrors(article);
    if (errors.length) {
      return NextResponse.json({ success: false, error: errors.join('; ') }, { status: 422 });
    }
    article.fecha_publicacion = new Date().toISOString();
    article.revision_humana = true;
    const day = article.fecha_publicacion.slice(0, 10);
    destination = path.join(OUTPUT_DIR, day, categoryFolder(category), path.basename(source));
    if (fs.existsSync(/* turbopackIgnore: true */ destination)) {
      return NextResponse.json({ success: false, error: 'Ya existe un artículo con ese ID' }, { status: 409 });
    }
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.writeFileSync(destination, JSON.stringify(article, null, 2), 'utf8');

    // Build away from the live directory. A failed build leaves the draft untouched.
    stage = fs.mkdtempSync(path.join(BASE_DIR, 'website', '.publish-next-'));
    for (const asset of ['css', 'js', 'favicon.svg']) {
      const sourceAsset = path.join(publicDir, asset);
      if (fs.existsSync(/* turbopackIgnore: true */ sourceAsset)) {
        fs.cpSync(/* turbopackIgnore: true */ sourceAsset, path.join(stage, asset), { recursive: true });
      }
    }
    await run(process.env.PYTHON_BIN || 'python', ['website/builder.py'], {
      cwd: BASE_DIR,
      env: { ...process.env, PUBLIC_DIR: stage },
      timeout: 120_000,
      maxBuffer: 4 * 1024 * 1024,
    });
    if (!fs.existsSync(/* turbopackIgnore: true */ path.join(stage, 'index.html'))) throw new Error('El sitio generado no tiene portada');
    const backupRoot = path.join(BASE_DIR, 'scratch', 'site-backups');
    fs.mkdirSync(backupRoot, { recursive: true });
    backup = path.join(backupRoot, randomUUID());
    // Both paths are fixed descendants of the project and are on the same drive.
    if (path.relative(BASE_DIR, publicDir).startsWith('..') || path.relative(BASE_DIR, backup).startsWith('..')) throw new Error('Ruta de publicación fuera del proyecto');
    fs.renameSync(publicDir, backup);
    try {
      fs.renameSync(stage, publicDir);
      stage = '';
    } catch (error) {
      fs.renameSync(backup, publicDir);
      backup = '';
      throw error;
    }
    fs.unlinkSync(source);

    let syncWarning = '';
    if (process.env.AUTO_GIT_PUSH === '1') {
      try {
        await run('git', ['diff', '--cached', '--quiet'], { cwd: BASE_DIR });
        await run('git', ['add', '-A', '--', 'published', 'website/public', 'drafts'], { cwd: BASE_DIR });
        await run('git', ['commit', '-m', `Publicar noticia ${day}`], { cwd: BASE_DIR });
        await run('git', ['push'], { cwd: BASE_DIR, timeout: 60_000 });
      } catch (error: unknown) {
        syncWarning = `Publicado localmente; no se pudo sincronizar Git: ${message(error)}`;
      }
    }
    return NextResponse.json({ success: true, warning: syncWarning });
  } catch (error: unknown) {
    if (!backup && destination && fs.existsSync(/* turbopackIgnore: true */ destination)) fs.unlinkSync(destination);
    return NextResponse.json({ success: false, error: message(error) }, { status: 500 });
  } finally {
    if (stage && path.relative(path.join(BASE_DIR, 'website'), stage).startsWith('.publish-next-') && fs.existsSync(/* turbopackIgnore: true */ stage)) {
      fs.rmSync(stage, { recursive: true, force: true });
    }
  }
}
