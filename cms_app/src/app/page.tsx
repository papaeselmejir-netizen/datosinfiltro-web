'use client';
/* eslint-disable @next/next/no-img-element */

import { useCallback, useEffect, useState } from 'react';

type DraftSummary = {
  id: string; titulo: string; fecha: string; categoria: string; region: string;
  imagen_url: string; fuentes: number; imagenes: number; video: boolean; errores: string[];
};
type Draft = {
  titulo_articulo: string; articulo_web: string; categoria: string; resumen?: string;
  fuentes?: { titulo: string; url: string; medio?: string }[];
  imagenes?: { url: string; descripcion: string; credito: string; licencia: string; origen: string; tipo: string }[];
  video_url?: string; video_titulo?: string; video_canal?: string; video_source?: string; video_origen?: string; video_licencia?: string; video_poster?: string;
};

export default function Home() {
  const [drafts, setDrafts] = useState<DraftSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [topic, setTopic] = useState('');
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<{ id: string; article: Draft } | null>(null);
  const [category, setCategory] = useState('');
  const [notice, setNotice] = useState('');
  const [categories, setCategories] = useState<string[]>([]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/drafts', { cache: 'no-store' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'No se pudo cargar');
      setDrafts(data.drafts);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Error de conexión');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => { void refresh(); }, 0);
    return () => window.clearTimeout(timer);
  }, [refresh]);

  useEffect(() => {
    void fetch('/api/categories').then(response => response.json()).then(data => {
      if (data.success) setCategories(data.categories);
    });
  }, []);

  async function generate(event: React.FormEvent) {
    event.preventDefault();
    if (!topic.trim()) return;
    setBusy(true); setNotice('');
    try {
      const response = await fetch('/api/generate', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: topic.trim() }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Generación fallida');
      setTopic(''); setNotice(data.message); await refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Error de conexión');
    } finally { setBusy(false); }
  }

  async function preview(item: DraftSummary) {
    setBusy(true); setNotice('');
    try {
      const response = await fetch(`/api/draft?id=${encodeURIComponent(item.id)}`, { cache: 'no-store' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'No se pudo abrir');
      setSelected({ id: item.id, article: data.draft });
      setCategory(categories.includes(item.categoria) ? item.categoria : categories[0] || item.categoria);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Error de conexión');
    } finally { setBusy(false); }
  }

  async function decide(action: 'approve' | 'reject') {
    if (!selected) return;
    if (action === 'reject' && !window.confirm('¿Eliminar este borrador?')) return;
    setBusy(true); setNotice('');
    try {
      const response = await fetch(`/api/${action}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: selected.id, category }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Operación fallida');
      setNotice(data.warning || (action === 'approve' ? 'Publicado correctamente' : 'Borrador eliminado'));
      setSelected(null); await refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Error de conexión');
    } finally { setBusy(false); }
  }

  async function sync() {
    setBusy(true); setNotice('');
    try {
      const response = await fetch('/api/sync', { method: 'POST' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Sincronización fallida');
      setNotice('Sincronización terminada'); await refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Error de conexión');
    } finally { setBusy(false); }
  }

  const selectedSummary = drafts.find(item => item.id === selected?.id);
  return (
    <div className="mx-auto max-w-7xl p-5 md:p-10">
      <header className="mb-8 flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="mb-2 text-xs font-bold uppercase tracking-[0.25em] text-cyan-300">Mesa editorial</p>
          <h1 className="text-4xl font-black tracking-tight">DatoSinFiltro <span className="text-gradient">CMS</span></h1>
          <p className="mt-2 text-gray-400">Noticias investigadas, multimedia con licencia y revisión antes de publicar.</p>
        </div>
        <form onSubmit={generate} className="flex w-full gap-2 md:w-auto">
          <input aria-label="Tema de la noticia" value={topic} onChange={event => setTopic(event.target.value)}
            placeholder="Investigar un tema…" maxLength={160} disabled={busy}
            className="glass-panel min-w-0 flex-1 rounded-lg px-4 py-3 md:w-72" />
          <button disabled={busy || !topic.trim()} className="rounded-lg bg-cyan-400 px-4 py-3 font-bold text-slate-950 disabled:opacity-50">Investigar</button>
        </form>
      </header>

      <div className="mb-6 flex items-center justify-between gap-3">
        <h2 className="text-2xl font-bold">Borradores ({drafts.length})</h2>
        <div className="flex gap-2">
          <button onClick={sync} disabled={busy} className="rounded-lg border border-white/20 px-3 py-2 text-sm disabled:opacity-50">Sincronizar</button>
          <button onClick={() => void refresh()} disabled={busy} className="rounded-lg border border-white/20 px-3 py-2 text-sm disabled:opacity-50">Actualizar</button>
        </div>
      </div>
      {notice && <p role="status" className="mb-5 rounded-lg border border-cyan-500/30 bg-cyan-500/10 p-3 text-cyan-100">{notice}</p>}
      {loading ? <p>Actualizando borradores…</p> : drafts.length === 0 ?
        <p className="glass-card p-10 text-gray-300">No hay borradores pendientes. El recolector seguirá buscando en sus horarios programados.</p> :
        <div className="grid gap-5 md:grid-cols-2 lg:grid-cols-3">
          {drafts.map(item => <article key={item.id} className="glass-card overflow-hidden">
            {item.imagen_url ? <img src={item.imagen_url} alt={item.titulo} className="h-44 w-full object-cover" /> : <div className="flex h-44 items-center justify-center bg-slate-800 text-gray-400">Sin imagen</div>}
            <div className="p-5">
              <p className="text-xs uppercase tracking-widest text-cyan-300">{item.categoria} · {item.region}</p>
              <h3 className="mt-2 min-h-20 text-xl font-bold leading-snug">{item.titulo}</h3>
              <p className="mt-3 text-sm text-gray-300">{item.fuentes} fuentes · {item.imagenes} imágenes · {item.video ? 'Video' : 'Sin video'}</p>
              {item.errores.length > 0 && <p className="mt-3 text-sm text-amber-300">Pendiente: {item.errores.join('; ')}</p>}
              <button onClick={() => void preview(item)} disabled={busy} className="mt-5 w-full rounded-lg bg-white/10 px-4 py-2 font-semibold hover:bg-white/20 disabled:opacity-50">Revisar noticia</button>
            </div>
          </article>)}
        </div>}

      {selected && <div className="fixed inset-0 z-50 overflow-y-auto bg-black/80 p-3 md:p-10" role="dialog" aria-modal="true" aria-label="Revisión de noticia">
        <div className="mx-auto max-w-4xl rounded-xl bg-slate-900 p-5 md:p-8">
          <div className="flex justify-between gap-4">
            <div><p className="text-xs uppercase tracking-widest text-cyan-300">Revisión editorial</p><h2 className="mt-2 text-3xl font-bold">{selected.article.titulo_articulo}</h2></div>
            <button onClick={() => setSelected(null)} aria-label="Cerrar revisión" className="h-10 rounded border border-white/20 px-3">Cerrar</button>
          </div>
          <p className="my-4 text-gray-300">{selected.article.resumen}</p>
          <label className="text-sm font-semibold">Categoría <select value={category} onChange={event => setCategory(event.target.value)} className="ml-2 rounded bg-slate-800 p-2">{categories.map(value => <option key={value} value={value}>{value}</option>)}</select></label>
          <h3 className="mt-8 text-xl font-bold">Fuentes</h3>
          <ul className="mt-2 list-disc pl-5">{selected.article.fuentes?.map(source => <li key={source.url}><a href={source.url} target="_blank" rel="noopener noreferrer" className="text-cyan-300 underline">{source.medio || source.titulo}</a></li>)}</ul>
          <h3 className="mt-8 text-xl font-bold">Imágenes y derechos</h3>
          <div className="mt-3 grid gap-4 md:grid-cols-2">{selected.article.imagenes?.map(image => <figure key={image.url}><img src={image.url} alt={image.descripcion} className="h-52 w-full rounded object-cover" /><figcaption className="mt-1 text-sm text-gray-300">{image.tipo}. {image.credito} · {image.licencia} · <a href={image.origen} target="_blank" rel="noopener noreferrer" className="underline">Origen</a></figcaption></figure>)}</div>
          {selected.article.video_url && <section className="mt-8"><h3 className="text-xl font-bold">Video: {selected.article.video_titulo}</h3><p className="text-sm text-gray-300">Autor o canal: {selected.article.video_canal}{selected.article.video_origen && <> · <a href={selected.article.video_origen} target="_blank" rel="noopener noreferrer" className="underline">Origen y licencia: {selected.article.video_licencia}</a></>}</p>{selected.article.video_source === 'pexels' ? <video src={selected.article.video_url} poster={selected.article.video_poster} controls preload="none" className="mt-3 aspect-video w-full" /> : <iframe src={selected.article.video_url} title={selected.article.video_titulo || 'Video relacionado'} className="mt-3 aspect-video w-full" loading="lazy" allowFullScreen />}</section>}
          <h3 className="mt-8 text-xl font-bold">Artículo</h3>
          <div className="mt-3 max-h-96 overflow-y-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-5 leading-7 text-gray-200">{selected.article.articulo_web}</div>
          {selectedSummary?.errores.length ? <p className="mt-5 text-amber-300">No publicable: {selectedSummary.errores.join('; ')}</p> : null}
          <div className="mt-6 flex gap-3">
            <button onClick={() => void decide('reject')} disabled={busy} className="rounded-lg border border-red-400 px-5 py-3 text-red-300 disabled:opacity-50">Rechazar</button>
            <button onClick={() => void decide('approve')} disabled={busy || Boolean(selectedSummary?.errores.length)} className="rounded-lg bg-emerald-400 px-5 py-3 font-bold text-slate-950 disabled:opacity-50">Aprobar y publicar</button>
          </div>
        </div>
      </div>}
    </div>
  );
}
