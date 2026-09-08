'use client';

import { useEffect, useState } from 'react';

type Draft = {
  id: string;
  titulo: string;
  fecha: string;
  categoria: string;
  region: string;
  imagen_url: string;
};

export default function Home() {
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [loading, setLoading] = useState(true);
  const [topic, setTopic] = useState('');
  const [searching, setSearching] = useState(false);
  const [processingId, setProcessingId] = useState<string | null>(null);
  const [selectedCategories, setSelectedCategories] = useState<Record<string, string>>({});

  const CATEGORIES = [
    "Noticias de Ultima Hora y Politica",
    "Deportes en Vivo",
    "Economia Negocios y Criptomonedas",
    "Tecnologia Gadgets e Inteligencia Artificial",
    "Salud Bienestar y Estilo de Vida",
    "Cultura Entretenimiento Farandula y Cine",
    "Gaming y Esports",
    "Tendencias"
  ];

  useEffect(() => {
    fetchDrafts();
  }, []);

  const fetchDrafts = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/drafts');
      const data = await res.json();
      if (data.success) {
        setDrafts(data.drafts);
        // Initialize selected categories
        const initialCats: Record<string, string> = {};
        data.drafts.forEach((d: Draft) => {
          initialCats[d.id] = d.categoria;
        });
        setSelectedCategories(initialCats);
      }
    } catch (error) {
      console.error('Error fetching drafts:', error);
    }
    setLoading(false);
  };

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!topic.trim()) return;
    
    setSearching(true);
    try {
      const res = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic })
      });
      const data = await res.json();
      if (data.success) {
        setTopic('');
        fetchDrafts();
      } else {
        alert('Error al generar: ' + data.error);
      }
    } catch (error) {
      alert('Error de conexión');
    } finally {
      setSearching(false);
    }
  };

  const handleCategoryChange = (id: string, newCat: string) => {
    setSelectedCategories(prev => ({ ...prev, [id]: newCat }));
  };

  const handleApprove = async (id: string) => {
    setProcessingId(id);
    try {
      const finalCategory = selectedCategories[id];
      const res = await fetch('/api/approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, category: finalCategory })
      });
      const data = await res.json();
      if (data.success) {
        setDrafts(drafts.filter(d => d.id !== id));
      } else {
        alert('Error al aprobar: ' + data.error);
      }
    } catch (error) {
      alert('Error de conexión');
    } finally {
      setProcessingId(null);
    }
  };

  const handleReject = async (id: string) => {
    if (!confirm('¿Estás seguro de que quieres rechazar y eliminar esta noticia permanentemente?')) return;
    
    setProcessingId(id);
    try {
      const res = await fetch('/api/reject', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id })
      });
      const data = await res.json();
      if (data.success) {
        setDrafts(drafts.filter(d => d.id !== id));
      } else {
        alert('Error al rechazar: ' + data.error);
      }
    } catch (error) {
      alert('Error de conexión');
    } finally {
      setProcessingId(null);
    }
  };

  const handleSyncCloud = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/sync', { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        // Después de sincronizar, refrescar los borradores
        await fetchDrafts();
        alert('Sincronizado con éxito con la nube.');
      } else {
        alert('Error al sincronizar: ' + data.error);
        setLoading(false);
      }
    } catch (error) {
      alert('Error de conexión');
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen p-8 max-w-7xl mx-auto">
      <header className="mb-12 flex justify-between items-center">
        <div>
          <h1 className="text-4xl font-black tracking-tight mb-2">
            DatoSinFiltro <span className="text-gradient">CMS</span>
          </h1>
          <p className="text-gray-400">Panel de Control Editorial y Aprobación de IA</p>
        </div>
        
        <form onSubmit={handleSearch} className="flex gap-3">
          <input 
            type="text" 
            placeholder="Buscar tema en la web..." 
            className="glass-panel rounded-full px-6 py-3 w-80 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            disabled={searching}
          />
          <button 
            type="submit" 
            disabled={searching}
            className="bg-blue-600 hover:bg-blue-500 text-white px-6 py-3 rounded-full font-medium transition-colors disabled:opacity-50"
          >
            {searching ? 'Buscando...' : 'Generar Noticia'}
          </button>
        </form>
      </header>

      <main>
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold">Borradores Pendientes ({drafts.length})</h2>
          <div className="flex gap-4">
            <button onClick={handleSyncCloud} className="text-sm bg-[#00E5FF]/20 text-[#00E5FF] px-4 py-2 rounded-full hover:bg-[#00E5FF]/30 font-bold transition-colors">
              ☁️ Sincronizar Nube
            </button>
            <button onClick={fetchDrafts} className="text-sm text-blue-400 hover:text-blue-300 px-4 py-2">
              Actualizar Lista
            </button>
          </div>
        </div>

        {loading ? (
          <div className="flex justify-center py-20">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
          </div>
        ) : drafts.length === 0 ? (
          <div className="glass-card p-12 text-center text-gray-400">
            <p className="text-xl">No hay borradores pendientes de revisión.</p>
            <p className="text-sm mt-2">Usa el buscador superior para generar una noticia nueva.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {drafts.map((draft) => (
              <div key={draft.id} className="glass-card overflow-hidden flex flex-col">
                <div className="h-48 overflow-hidden relative bg-black/20">
                  {draft.imagen_url ? (
                    <img 
                      src={draft.imagen_url} 
                      alt="Thumbnail" 
                      className="w-full h-full object-cover opacity-80 hover:opacity-100 transition-opacity"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-gray-500">
                      Sin imagen
                    </div>
                  )}
                  <div className="absolute top-3 left-3 flex gap-2">
                    <span className="bg-blue-900/60 backdrop-blur-sm text-xs px-3 py-1 rounded-full font-medium border border-blue-500/30 text-blue-200">
                      {draft.region}
                    </span>
                  </div>
                </div>
                
                <div className="p-4 flex flex-col flex-grow">
                  <div className="flex gap-2 mb-3 items-center">
                    <span className="bg-[#00E5FF]/20 text-[#00E5FF] px-2 py-1 rounded text-xs font-bold uppercase tracking-wider">
                      Borrador
                    </span>
                    <select
                      value={selectedCategories[draft.id] || draft.categoria}
                      onChange={(e) => handleCategoryChange(draft.id, e.target.value)}
                      className="bg-black/50 text-white border border-white/10 rounded px-2 py-1 text-xs outline-none focus:border-[#00E5FF] transition-colors max-w-[150px] truncate"
                      title="Cambiar Categoría"
                    >
                      {CATEGORIES.map(cat => (
                        <option key={cat} value={cat}>{cat}</option>
                      ))}
                    </select>
                  </div>
                  <p className="text-xs text-gray-400 mb-2 font-mono">{new Date(draft.fecha).toLocaleString()}</p>
                  <h3 className="text-lg font-bold leading-tight mb-4 flex-1">{draft.titulo}</h3>
                  
                  <div className="flex gap-3 mt-auto pt-4 border-t border-white/5">
                    <button 
                      onClick={() => handleReject(draft.id)}
                      disabled={processingId === draft.id}
                      className="flex-1 bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
                    >
                      {processingId === draft.id ? '...' : 'Rechazar'}
                    </button>
                    <button 
                      onClick={() => handleApprove(draft.id)}
                      disabled={processingId === draft.id}
                      className="flex-1 bg-emerald-500 hover:bg-emerald-400 text-black py-2 rounded-lg text-sm font-bold shadow-[0_0_15px_rgba(16,185,129,0.3)] transition-all disabled:opacity-50 disabled:shadow-none"
                    >
                      {processingId === draft.id ? 'Aprobando...' : 'Aprobar'}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
