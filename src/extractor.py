import os
import re
import unicodedata
from urllib.parse import quote, unquote
import feedparser
import requests
from dotenv import load_dotenv
from src.editorial import normalized_headline, rank_news

load_dotenv()

# Configuracion de idioma y pais desde .env
NEWS_LANG = os.getenv("NEWS_LANG", "es")
NEWS_COUNTRY = os.getenv("NEWS_COUNTRY", "PE")
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY", "")
CURRENTS_API_KEY = os.getenv("CURRENTS_API_KEY", "")

# Mapeo de las 7 categorias del usuario a búsquedas estrictas por keywords en Google News RSS
CATEGORIAS = {
    "Deportes en Vivo": "search?q=deportes+OR+futbol+OR+tenis+OR+NBA",
    "Entretenimiento, Farandula y Cine": "search?q=cine+OR+musica+OR+espectaculos+OR+streamers",
    "Noticias de Ultima Hora y Politica": "search?q=politica+OR+gobierno+OR+elecciones",
    "Tecnologia, Gadgets e Inteligencia Artificial": "search?q=tecnologia+OR+gadgets+OR+inteligencia+artificial",
    "Finanzas, Negocios y Criptomonedas": "search?q=economia+OR+negocios+OR+criptomonedas",
    "Gaming y Esports": "search?q=gaming+OR+esports+OR+videojuegos",
    "Salud, Bienestar y Estilo de Vida": "search?q=salud+OR+medicina+OR+bienestar",
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
    "Noticias de Ultima Hora y Politica": "https://elcomercio.pe/arc/outboundfeeds/rss/?outputType=xml",
    "Finanzas, Negocios y Criptomonedas": "https://gestion.pe/arc/outboundfeeds/rss/?outputType=xml",
}

PERU_TERMS = (
    "peru", "peruano", "peruana", "peruanos", "peruanas", "lima", "callao",
    "arequipa", "cusco", "cuzco", "trujillo", "piura", "chiclayo", "huancayo",
    "iquitos", "puno", "tacna", "ica", "ancash", "huanuco", "cajamarca",
    "ucayali", "loreto", "junin", "ayacucho", "apurimac", "lambayeque",
    "moquegua", "tumbes", "pucallpa", "huaraz", "machu picchu",
    "alianza lima", "universitario de deportes", "sporting cristal",
    "congreso peruano", "bcrp", "reniec", "sunat", "indecopi", "essalud",
)


def is_peru_story(item):
    """A Peruvian outlet alone does not establish where an event occurred."""
    title = (item.get("titulo") or "").rsplit(" - ", 1)[0]
    value = unicodedata.normalize("NFKD", " ".join((title, item.get("snippet", ""))))
    value = "".join(char for char in value if not unicodedata.combining(char)).lower()
    return any(re.search(r"\b" + re.escape(term) + r"\b", value) for term in PERU_TERMS)


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

    # El país del feed localiza la interfaz, pero no limita el lugar de los hechos.
    # La consulta de Perú exige indicios de ubicación y el filtro posterior los verifica.
    if topic_path.startswith("search"):
        query = "(" + unquote(topic_path.partition("q=")[2]).replace("+", " ") + ")"
        if geo == "PE":
            query += " (Perú OR Lima OR Arequipa OR Cusco OR Trujillo)"
        query += " when:4d"
        topic_path = "search?q=" + quote(query)

    # Construir URL del feed RSS de Google News
    base_url = "https://news.google.com/rss"
    if topic_path.startswith("search"):
        url = f"{base_url}/{topic_path}&hl={lang}&gl={geo}&ceid={geo}:{lang_code}"
    else:
        url = f"{base_url}/{topic_path}?hl={lang}&gl={geo}&ceid={geo}:{lang_code}"

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    try:
        for attempt in range(2):
            try:
                response = requests.get(url, headers=headers, timeout=12)
                response.raise_for_status()
                break
            except requests.RequestException:
                if attempt:
                    raise
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
        status = e.response.status_code if isinstance(e, requests.HTTPError) and e.response is not None else type(e).__name__
        print(f"  [GNews] Error ({status})")
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
        status = e.response.status_code if isinstance(e, requests.HTTPError) and e.response is not None else type(e).__name__
        print(f"  [Currents] Error ({status})")
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
    Combina fuentes hasta llenar el cupo con titulares y medios distintos.
    Orden: RSS local (solo PE) -> Google News RSS -> GNews API -> Currents API.
    :param categoria: Nombre exacto de una de las 7 categorias.
    :param max_items: Cantidad de noticias a extraer.
    :param lang: Idioma (ej: es)
    :param geo: Pais (ej: PE, US)
    :return: Hasta max_items noticias de fuentes diversas.
    """
    geo = geo or NEWS_COUNTRY

    selected = []
    seen_titles = set()
    seen_urls = set()
    outlet_counts = {}

    def add_candidates(candidates, limit=None):
        added = 0
        for item in rank_news(candidates):
            title = normalized_headline(item.get("titulo", ""))
            url = item.get("url", "")
            outlet = (item.get("fuente") or "Desconocida").strip().lower()
            if outlet in {"facebook.com", "instagram.com", "tiktok.com", "x.com", "youtube.com", "wordpress.com"}:
                continue
            if is_peru_story(item) != (geo == "PE"):
                continue
            if not title or not url or title in seen_titles or url in seen_urls:
                continue
            if outlet_counts.get(outlet, 0) >= 1:
                continue
            selected.append(item)
            seen_titles.add(title)
            seen_urls.add(url)
            outlet_counts[outlet] = outlet_counts.get(outlet, 0) + 1
            added += 1
            if len(selected) >= max_items or (limit and added >= limit):
                break

    # Google Trends indica dónde se busca un tema, no dónde ocurrió el hecho.
    if categoria == "Tendencias":
        topic = "noticias virales Perú" if geo == "PE" else "noticias virales mundo"
        candidates = extract_custom_topic_google_rss(topic + " when:4d", lang=lang, geo=geo, max_items=max_items * 6)
        add_candidates(candidates)
        if len(selected) < max_items:
            topic = "tendencias Perú" if geo == "PE" else "tendencias internacionales"
            add_candidates(extract_custom_topic_google_rss(topic + " when:4d", lang=lang, geo=geo, max_items=max_items * 6))
        print(f"    -> {len(selected)}/{max_items} candidatas de {len(outlet_counts)} medios")
        return selected

    # Un titular local deja espacio para otros medios peruanos en Google News.
    if geo == "PE" and categoria in FUENTES_LOCALES_PERU:
        print(f"    Intentando Fuente Local Directa (Perú) para {categoria}...")
        add_candidates(extract_news_local_rss(categoria, max_items=max_items * 2), limit=1)

    if len(selected) < max_items:
        print(f"    Intentando Google News RSS (geo={geo})...")
        add_candidates(extract_news_google_rss(categoria, max_items=max_items * 6, lang=lang, geo=geo))

    if len(selected) < max_items and GNEWS_API_KEY:
        print("    Completando con GNews API...")
        add_candidates(extract_news_gnews(categoria, max_items=max_items * 2, lang=lang, country=geo))

    if len(selected) < max_items and CURRENTS_API_KEY:
        print("    Completando con Currents API...")
        add_candidates(extract_news_currents(categoria, max_items=max_items * 2, lang=lang, country=geo))

    print(f"    -> {len(selected)}/{max_items} candidatas de {len(outlet_counts)} medios")
    return selected


# Mantener compatibilidad con imports existentes
def extract_news_by_category(categoria, lang=None, geo=None, max_items=3):
    """Wrapper de compatibilidad. Usa extract_news_multi_source internamente."""
    return extract_news_multi_source(categoria, max_items=max_items, lang=lang, geo=geo)


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
