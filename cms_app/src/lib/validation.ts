type Image = { url?: string; licencia?: string; licencia_url?: string; origen?: string; credito?: string; descripcion?: string };
type Source = { url?: string; titulo?: string };

export type ArticleDraft = {
  schema_version?: number;
  titulo_articulo?: string;
  articulo_web?: string;
  categoria?: string;
  imagen_url?: string;
  imagenes?: Image[];
  video_url?: string;
  video_titulo?: string;
  video_source?: string;
  video_origen?: string;
  video_licencia?: string;
  video_licencia_url?: string;
  video_canal?: string;
  fuentes?: Source[];
  fecha_publicacion?: string;
  [key: string]: unknown;
};

export function validationErrors(article: ArticleDraft): string[] {
  const errors: string[] = [];
  if (article.schema_version !== 2) errors.push('Formato de borrador anterior: requiere revisión y migración');
  if (!article.titulo_articulo || article.titulo_articulo.toLowerCase().startsWith('error')) errors.push('Título inválido');
  if (!article.articulo_web || article.articulo_web.trim().split(/\s+/).length < 250) errors.push('Texto insuficiente');
  const hosts = new Set((article.fuentes || []).map(source => {
    try { return new URL(source.url || '').hostname.replace(/^www\./, ''); } catch { return ''; }
  }).filter(Boolean));
  if (!Array.isArray(article.fuentes) || hosts.size < 2) {
    errors.push('Faltan dos fuentes verificadas');
  }
  if (!Array.isArray(article.imagenes) || article.imagenes.length < 2 || article.imagenes.slice(0, 2).some(i => !i.url?.startsWith('https://') || !i.licencia || !i.licencia_url?.startsWith('https://') || !i.origen?.startsWith('https://') || !i.credito)) {
    errors.push('Faltan dos imágenes con licencia registrada');
  }
  const youtube = /^https:\/\/(www\.)?youtube\.com\/embed\/[A-Za-z0-9_-]{11}$/.test(article.video_url || '');
  let pexels = false;
  try { const url = new URL(article.video_url || ''); pexels = article.video_source === 'pexels' && url.protocol === 'https:' && url.hostname === 'videos.pexels.com' && Boolean(article.video_origen?.startsWith('https://') && article.video_licencia && article.video_licencia_url?.startsWith('https://') && article.video_canal); } catch { /* invalid URL */ }
  if ((!youtube && !pexels) || !article.video_titulo) {
    errors.push('Falta un video relacionado y embebible');
  }
  return errors;
}
