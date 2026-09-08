import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import { exec } from 'child_process';
import util from 'util';

const execPromise = util.promisify(exec);

const DRAFTS_DIR = path.join(process.cwd(), '../drafts');
const OUTPUT_DIR = path.join(process.cwd(), '../output');
const BASE_DIR = path.join(process.cwd(), '../');

export async function POST(req: Request) {
  try {
    const { id, category } = await req.json();
    if (!id) return NextResponse.json({ success: false, error: 'ID requerido' }, { status: 400 });

    const sourcePath = path.join(DRAFTS_DIR, id);

    // Asegurar que el archivo de origen exista
    if (!fs.existsSync(sourcePath)) {
      return NextResponse.json({ success: false, error: 'El borrador no existe' }, { status: 404 });
    }

    // Leer y modificar la categoría en el JSON si se proporcionó una nueva
    let draftData = {};
    try {
      const fileContent = fs.readFileSync(sourcePath, 'utf8');
      draftData = JSON.parse(fileContent);
      if (category) {
        (draftData as any).categoria = category;
      }
    } catch (e) {
      console.error('Error reading JSON:', e);
    }

    // Determinar la nueva ruta de destino basada en la categoría
    let destRelativePath = id;
    if (category) {
      // id format is "YYYY-MM-DD/OldCategory/filename.json"
      const parts = id.replace(/\\/g, '/').split('/');
      if (parts.length >= 3) {
        const dateFolder = parts[0];
        const filename = parts[parts.length - 1];
        const safeCategory = category.replace(/ /g, '_').replace(/,/g, '');
        destRelativePath = path.join(dateFolder, safeCategory, filename);
      }
    }

    const destPath = path.join(OUTPUT_DIR, destRelativePath);

    // Crear el directorio de destino si no existe
    const destDir = path.dirname(destPath);
    if (!fs.existsSync(destDir)) {
      fs.mkdirSync(destDir, { recursive: true });
    }

    // Guardar el archivo modificado en el destino
    fs.writeFileSync(destPath, JSON.stringify(draftData, null, 4), 'utf8');
    
    // Eliminar el archivo original de borradores
    fs.unlinkSync(sourcePath);

    // Ejecutar builder.py para reconstruir la página estática
    const { stdout, stderr } = await execPromise('python website/builder.py', { cwd: BASE_DIR });
    console.log('Builder Output:', stdout);

    // Si el proyecto es un repositorio Git, subir los cambios automáticamente a GitHub
    try {
      // Usamos || echo para evitar que el script falle si no hay cambios que hacer commit
      const gitCmd = `git pull && git add output/ website/ && git commit -m "Publicación aprobada desde el CMS" || echo "No changes to commit" && git push`;
      const { stdout: gitOut } = await execPromise(gitCmd, { cwd: BASE_DIR });
      console.log('Git Output:', gitOut);
    } catch (gitErr: any) {
      console.error('Git Push Error (Ignorando si no hay repositorio configurado aun):', gitErr.message);
    }

    return NextResponse.json({ success: true, message: 'Borrador aprobado y sitio reconstruido (sincronizado con GitHub)' });
  } catch (error: any) {
    console.error('Approve Error:', error);
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}
