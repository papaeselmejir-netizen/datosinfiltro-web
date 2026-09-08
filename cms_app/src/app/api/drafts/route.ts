import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';

// Ruta hacia la carpeta de borradores (drafts) en el directorio padre
const DRAFTS_DIR = path.join(process.cwd(), '../drafts');

function getJsonFiles(dir: string, fileList: string[] = []) {
  if (!fs.existsSync(dir)) {
    return fileList;
  }
  
  const files = fs.readdirSync(dir);

  for (const file of files) {
    const filePath = path.join(dir, file);
    if (fs.statSync(filePath).isDirectory()) {
      getJsonFiles(filePath, fileList);
    } else if (file.endsWith('.json')) {
      fileList.push(filePath);
    }
  }

  return fileList;
}

export async function GET() {
  try {
    const jsonPaths = getJsonFiles(DRAFTS_DIR);
    
    const drafts = jsonPaths.map(filePath => {
      const content = fs.readFileSync(filePath, 'utf-8');
      const data = JSON.parse(content);
      
      // Extraemos metadatos básicos para el listado
      return {
        id: path.relative(DRAFTS_DIR, filePath).replace(/\\/g, '/'),
        titulo: data.titulo_articulo || 'Sin título',
        fecha: data.fecha || 'Sin fecha',
        categoria: data.categoria || 'Sin categoría',
        region: data.region || 'General',
        imagen_url: data.imagen_url || ''
      };
    });

    return NextResponse.json({ success: true, drafts });
  } catch (error: any) {
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}
