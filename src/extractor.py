import os
import re
import feedparser
import requests
from dotenv import load_dotenv

load_dotenv()

# Configuracion de idioma y pais desde .env
NEWS_LANG = os.getenv("NEWS_LANG", "es")
NEWS_COUNTRY = os.getenv("NEWS_COUNTRY", "PE")
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY", "")
CURRENTS_API_KEY = os.getenv("CURRENTS_API_KEY", "")

# Mapeo de las 7 categorias del usuario a búsquedas estrictas por keywords en Google News RSS
CATEGORIAS = {
    "Deportes en Vivo": "search?q=deportes+futbol+tenis+nba+olimpiadas",
    "Entretenimiento, Farandula y Cine": "search?q=farandula+OR+cine+OR+espectaculos+OR+famosos+OR+streamers+OR+tiktokers+OR+ibai+OR+auronplay",
    "Noticias de Ultima Hora y Politica": "search?q=politica+gobierno+elecciones+crisis+noticias",
    "Tecnologia, Gadgets e Inteligencia Artificial": "search?q=tecnologia+gadgets+inteligencia+artificial+software",
    "Finanzas, Negocios y Criptomonedas": "search?q=finanzas+negocios+criptomonedas+economia+mercados",
    "Gaming y Esports": "search?q=gaming+esports+videojuegos+consolas",
    "Salud, Bienestar y Estilo de Vida": "search?q=salud+bienestar+medicina+vida+sana+nutricion",
    "Tendencias": "trends",
}

# Mapeo de categorias a topics de GNews API
CATEGORIAS_GNEWS = {
    "Deportes en Vivo": "sports",
    "Entretenimiento, Farandula y Cine": "entertainment",
    "Noticias de Ultima Hora y Politica": "world",
    "Tecnologia, Gadgets e Inteligencia Artificial": "technology",
    "Finanzas, Negocios y Criptomonedas": "business",
    "Gaming y Esports": "technology",
    "Salud, Bienestar y Estilo de Vida": "health",
}

# Mapeo de categorias a topics de Currents API
CATEGORIAS_CURRENTS = {
    "Deportes en Vivo": "sports",
    "Entretenimiento, Farandula y Cine": "entertainment",
    "Noticias de Ultima Hora y Politica": "world",
    "Tecnologia, Gadgets e Inteligencia Artificial": "technology",
    "Finanzas, Negocios y Criptomonedas": "business",
    "Gaming y Esports": "gaming",
    "Salud, Bienestar y Estilo de Vida": "health",
}

# RSS Directos de Periódicos Peruanos
FUENTES_LOCALES_PERU = {
    "Deportes en Vivo": "https://depor.com/arc/outboundfeeds/rss/?outputType=xml",
    "Entretenimiento, Farandula y Cine": "https://peru21.pe/arc/outboundfeeds/rss/espectaculos/?outputType=xml",
    "Noticias de Ultima Hora y Politica": "https://elcomercio.pe/arc/outboundfeeds/rss/?outputType=xml",
    "Finanzas, Negocios y Criptomonedas": "https://gestion.pe/arc/outboundfeeds/rss/?outputType=xml",
}


def extract_news_local_rss(categoria, max_items=3):
    """
    Extrae noticias directamente de los feeds RSS de periodicos peruanos.
    """
    url = FUENTES_LOCALES_PERU.get(categoria)
    if not url:
        return []

    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
    except Exception as e:
        print(f"  [Local RSS] Error de conexion: {e}")
        return []

    noticias = []
    for entry in feed.entries[:max_items]:
        # Extraer dominio de la URL para usarlo como fuente (ej. elcomercio.pe)
        fuente_match = re.search(r"https?://(?:www\.)?([^/]+)", entry.link)
        fuente = fuente_match.group(1) if fuente_match else "Periódico Local"

        noticias.append({
            "titulo": entry.title,
            "url": entry.link,
            "fecha": entry.get("published", ""),
            "fuente": fuente,
            "snippet": entry.get("description", ""),
            "origen": "local_rss",
        })

    return noticias

def extract_google_trends(geo="PE", max_items=3):
    """
    Extrae los temas de tendencia de Google Trends RSS.
    """
    url = f"https://trends.google.com/trending/rss?geo={geo}"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
    except Exception as e:
        print(f"  [Google Trends] Error de conexion: {e}")
        return []

    noticias = []
    for entry in feed.entries[:max_items]:
        # Google Trends RSS incluye el título de la tendencia, noticia relacionada y snippet
        titulo = entry.title
        news_title = getattr(entry, "ht_news_item_title", titulo)
        news_snippet = getattr(entry, "ht_news_item_snippet", "")
        
        # Obtener la URL real de la noticia si existe, de lo contrario fallback al link
        link = getattr(entry, "ht_news_item_url", entry.link)

        noticias.append({
            "titulo": f"{titulo}: {news_title}",
            "url": link,
            "fecha": entry.get("published", ""),
            "fuente": "Google Trends",
            "snippet": news_snippet,
            "origen": "google_trends",
        })

    return noticias

def extract_news_google_rss(categoria, lang=None, geo=None, max_items=3):
    """
    Extrae noticias de Google News RSS para una categoria especifica.
    :param categoria: Nombre exacto de una de las 7 categorias.
    :param lang: Idioma del feed (ej: es, en-US). Default desde .env.
    :param geo: Pais (ej: PE, MX, US). Default desde .env.
    :param max_items: Cantidad de noticias a extraer.
    :return: Lista de dicts con titulo, url, fecha, fuente y snippet.
    """
    if lang is None:
        lang = NEWS_LANG
    if geo is None:
        geo = NEWS_COUNTRY

    topic_path = CATEGORIAS.get(categoria)
    if not topic_path:
        print(f"  Categoria '{categoria}' no reconocida en Google News RSS.")
        return []

    # Determinar el codigo de idioma para ceid (ej: "es" de "es-419")
    lang_code = lang.split("-")[0] if "-" in lang else lang

    # Construir URL del feed RSS de Google News
    base_url = "https://news.google.com/rss"
    if topic_path.startswith("search"):
        url = f"{base_url}/{topic_path}&hl={lang}&gl={geo}&ceid={geo}:{lang_code}"
    else:
        url = f"{base_url}/{topic_path}?hl={lang}&gl={geo}&ceid={geo}:{lang_code}"

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"  [Google RSS] Error de conexion: {e}")
        return []

    feed = feedparser.parse(response.content)

    noticias = []
    for entry in feed.entries[:max_items]:
        titulo_completo = entry.title
        fuente = "Desconocida"
        if " - " in titulo_completo:
            partes = titulo_completo.rsplit(" - ", 1)
            fuente = partes[1].strip() if len(partes) > 1 else "Desconocida"

        noticias.append({
            "titulo": titulo_completo,
            "url": entry.link,
            "fecha": entry.get("published", ""),
            "fuente": fuente,
            "snippet": "",  # Google RSS no incluye snippet
            "origen": "google_rss",
        })

    return noticias


def extract_custom_topic_google_rss(topic, lang=None, geo=None, max_items=1):
    """
    Busca noticias sobre un tema específico usando Google News RSS.
    """
    if lang is None:
        lang = NEWS_LANG
    if geo is None:
        geo = NEWS_COUNTRY

    lang_code = lang.split("-")[0] if "-" in lang else lang
    base_url = "https://news.google.com/rss"
    import urllib.parse
    query = urllib.parse.quote(topic)
    url = f"{base_url}/search?q={query}&hl={lang}&gl={geo}&ceid={geo}:{lang_code}"

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"  [Google RSS Custom] Error de conexion: {e}")
        return []

    feed = feedparser.parse(response.content)
    noticias = []
    for entry in feed.entries[:max_items]:
        titulo_completo = entry.title
        fuente = "Desconocida"
        if " - " in titulo_completo:
            partes = titulo_completo.rsplit(" - ", 1)
            fuente = partes[1].strip() if len(partes) > 1 else "Desconocida"

        noticias.append({
            "titulo": titulo_completo,
            "url": entry.link,
            "fecha": entry.get("published", ""),
            "fuente": fuente,
            "snippet": "",
            "origen": "google_rss_custom",
        })
    return noticias


def extract_news_gnews(categoria, lang=None, country=None, max_items=3):
    """
    Extrae noticias de GNews API (gnews.io).
    Requiere GNEWS_API_KEY en .env. 100 requests/dia gratis.
    :return: Lista de dicts con titulo, url, fecha, fuente y snippet.
    """
    if not GNEWS_API_KEY:
        print("  [GNews] Sin API key configurada. Saltando.")
        return []

    if lang is None:
        lang = NEWS_LANG
    if country is None:
        country = NEWS_COUNTRY

    topic = CATEGORIAS_GNEWS.get(categoria, "general")
    lang_code = lang.split("-")[0] if "-" in lang else lang

    url = "https://gnews.io/api/v4/top-headlines"
    params = {
        "topic": topic,
        "lang": lang_code,
        "country": country.lower(),
        "max": max_items,
        "apikey": GNEWS_API_KEY,
    }

    # Para Gaming, usar busqueda en vez de top-headlines
    if categoria == "Gaming y Esports":
        url = "https://gnews.io/api/v4/search"
        params = {
            "q": "gaming esports videojuegos",
            "lang": lang_code,
            "country": country.lower(),
            "max": max_items,
            "apikey": GNEWS_API_KEY,
        }
    elif categoria == "Entretenimiento, Farandula y Cine":
        url = "https://gnews.io/api/v4/search"
        params = {
            "q": "farandula OR famosos OR streamers OR tiktokers OR ibai OR auronplay",
            "lang": lang_code,
            "country": country.lower(),
            "max": max_items,
            "apikey": GNEWS_API_KEY,
        }

    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"  [GNews] Error: {e}")
        return []

    noticias = []
    for article in data.get("articles", [])[:max_items]:
        noticias.append({
            "titulo": article.get("title", ""),
            "url": article.get("url", ""),
            "fecha": article.get("publishedAt", ""),
            "fuente": article.get("source", {}).get("name", "Desconocida"),
            "snippet": article.get("description", ""),
            "origen": "gnews",
        })

    return noticias


def extract_news_currents(categoria, lang=None, country=None, max_items=3):
    """
    Extrae noticias de Currents API (currentsapi.services).
    Requiere CURRENTS_API_KEY en .env. 200+ requests/dia gratis.
    :return: Lista de dicts con titulo, url, fecha, fuente y snippet.
    """
    if not CURRENTS_API_KEY:
        print("  [Currents] Sin API key configurada. Saltando.")
        return []

    if lang is None:
        lang = NEWS_LANG
    if country is None:
        country = NEWS_COUNTRY

    topic = CATEGORIAS_CURRENTS.get(categoria, "general")
    lang_code = lang.split("-")[0] if "-" in lang else lang

    url = "https://api.currentsapi.services/v1/latest-news"
    params = {
        "category": topic,
        "language": lang_code,
        "country": country,
        "apiKey": CURRENTS_API_KEY,
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"  [Currents] Error: {e}")
        return []

    if data.get("status") != "ok":
        print(f"  [Currents] Respuesta invalida: {data.get('message', '')}")
        return []

    noticias = []
    for article in data.get("news", [])[:max_items]:
        noticias.append({
            "titulo": article.get("title", ""),
            "url": article.get("url", ""),
            "fecha": article.get("published", ""),
            "fuente": article.get("author", "Desconocida"),
            "snippet": article.get("description", ""),
            "origen": "currents",
        })

    return noticias


def extract_news_multi_source(categoria, max_items=3, lang=None, geo=None):
    """
    Extrae noticias usando multiples fuentes con fallback automatico.
    Orden: Local RSS (solo PE) -> Google News RSS -> GNews API -> Currents API.
    :param categoria: Nombre exacto de una de las 7 categorias.
    :param max_items: Cantidad de noticias a extraer.
    :param lang: Idioma (ej: es)
    :param geo: Pais (ej: PE, US)
    :return: Lista de dicts con noticias de la mejor fuente disponible.
    """
    # Si la categoria es Tendencias, ir directamente a Google Trends
    if categoria == "Tendencias":
        print(f"    Intentando Google Trends (geo={geo})...")
        noticias = extract_google_trends(geo=geo, max_items=max_items)
        if noticias:
            print(f"    -> {len(noticias)} tendencias extraidas")
            return noticias
        return []

    # Intento 0: RSS Locales Directos (SOLO PARA PERU)
    if geo == "PE" and categoria in FUENTES_LOCALES_PERU:
        print(f"    Intentando Fuente Local Directa (Perú) para {categoria}...")
        noticias = extract_news_local_rss(categoria, max_items=max_items)
        if noticias:
            print(f"    -> {len(noticias)} noticias via RSS Local Directo")
            return noticias

    # Intento 1: Google News RSS (sin API key)
    print(f"    Intentando Google News RSS (geo={geo})...")
    noticias = extract_news_google_rss(categoria, max_items=max_items, lang=lang, geo=geo)
    if noticias:
        print(f"    -> {len(noticias)} noticias via Google RSS")
        return noticias

    # Intento 2: GNews API
    print(f"    Google RSS sin resultados. Intentando GNews API...")
    noticias = extract_news_gnews(categoria, max_items=max_items, lang=lang, country=geo)
    if noticias:
        print(f"    -> {len(noticias)} noticias via GNews")
        return noticias

    # Intento 3: Currents API
    print(f"    GNews sin resultados. Intentando Currents API...")
    noticias = extract_news_currents(categoria, max_items=max_items, lang=lang, country=geo)
    if noticias:
        print(f"    -> {len(noticias)} noticias via Currents API")
        return noticias

    print(f"    Sin noticias de ninguna fuente para '{categoria}'.")
    return []


# Mantener compatibilidad con imports existentes
def extract_news_by_category(categoria, lang=None, geo=None, max_items=3):
    """Wrapper de compatibilidad. Usa extract_news_multi_source internamente."""
    return extract_news_multi_source(categoria, max_items=max_items)


def get_all_categories_news(categorias=None, max_per_category=3):
    """
    Extrae noticias de todas las categorias (o las especificadas).
    :param categorias: Lista de nombres de categorias. None = todas.
    :param max_per_category: Noticias por categoria.
    :return: Dict {categoria: [noticias]}
    """
    if categorias is None:
        categorias = list(CATEGORIAS.keys())

    resultado = {}
    for cat in categorias:
        print(f"  Escaneando: {cat}...")
        noticias = extract_news_multi_source(cat, max_items=max_per_category)
        resultado[cat] = noticias
        print(f"    -> {len(noticias)} noticias encontradas")

    return resultado


if __name__ == "__main__":
    # Test rapido: extraer noticias de todas las categorias
    print("=== Test de Extractor Multi-Source ===\n")
    print(f"Idioma: {NEWS_LANG} | Pais: {NEWS_COUNTRY}\n")
    todas = get_all_categories_news()
    for cat, noticias in todas.items():
        print(f"\n{cat} ({len(noticias)} noticias):")
        for i, n in enumerate(noticias, 1):
            print(f"  {i}. [{n['origen']}] {n['titulo'][:80]}")
