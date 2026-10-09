import os
import re
import unicodedata
from html import unescape
from urllib.parse import quote, unquote, parse_qs, urlparse
import feedparser
import requests
from dotenv import load_dotenv
from src.editorial import keywords, normalized_headline, rank_news, social_source, source_host

load_dotenv()

# Configuracion de idioma y pais desde .env
NEWS_LANG = os.getenv("NEWS_LANG", "es")
NEWS_COUNTRY = os.getenv("NEWS_COUNTRY", "PE")
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY", "")
CURRENTS_API_KEY = os.getenv("CURRENTS_API_KEY", "")

# Mapeo de las 8 categorias del usuario a búsquedas estrictas por keywords en Google News RSS
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

# Feeds de secciones comprobados; un feed general mezcla demasiados temas.
FUENTES_LOCALES_PERU = {
    "Deportes en Vivo": [
        "https://depor.com/arc/outboundfeeds/rss/?outputType=xml",
        "https://elcomercio.pe/arc/outboundfeeds/rss/category/deporte-total/?outputType=xml",
    ],
    "Entretenimiento, Farandula y Cine": [
        "https://elcomercio.pe/arc/outboundfeeds/rss/category/luces/?outputType=xml",
        "https://elcomercio.pe/arc/outboundfeeds/rss/category/tvmas/?outputType=xml",
    ],
    "Noticias de Ultima Hora y Politica": [
        "https://elcomercio.pe/arc/outboundfeeds/rss/category/politica/?outputType=xml",
    ],
    "Tecnologia, Gadgets e Inteligencia Artificial": [
        "https://elcomercio.pe/arc/outboundfeeds/rss/category/tecnologia/?outputType=xml",
    ],
    "Finanzas, Negocios y Criptomonedas": [
        "https://gestion.pe/arc/outboundfeeds/rss/category/economia/?outputType=xml",
        "https://elcomercio.pe/arc/outboundfeeds/rss/category/economia/?outputType=xml",
    ],
    "Tendencias": [
        "https://elcomercio.pe/arc/outboundfeeds/rss/category/somos/?outputType=xml",
    ],
}

FUENTES_INTERNACIONALES = {
    "Tecnologia, Gadgets e Inteligencia Artificial": ["https://www.xataka.com/feedburner.xml"],
    "Gaming y Esports": ["https://www.vidaextra.com/feedburner.xml"],
    "Salud, Bienestar y Estilo de Vida": ["https://www.sciencedaily.com/rss/health_medicine.xml"],
}

# Medios con cobertura de la sección indicada. La búsqueda acotada por dominio
# complementa los RSS directos y los índices generales sin requerir otra API.
FUENTES_ESPECIALIZADAS = {
    "Deportes en Vivo": {
        "PE": ("depor.com", "rpp.pe", "andina.pe", "larepublica.pe"),
        "WORLD": ("marca.com", "as.com", "espn.com", "apnews.com"),
    },
    "Entretenimiento, Farandula y Cine": {
        "PE": ("rpp.pe", "andina.pe", "elcomercio.pe", "larepublica.pe"),
        "WORLD": ("variety.com", "hollywoodreporter.com", "elpais.com", "apnews.com"),
    },
    "Noticias de Ultima Hora y Politica": {
        "PE": ("rpp.pe", "andina.pe", "elcomercio.pe", "larepublica.pe"),
        "WORLD": ("reuters.com", "apnews.com", "dw.com", "elpais.com"),
    },
    "Tecnologia, Gadgets e Inteligencia Artificial": {
        "PE": ("rpp.pe", "andina.pe", "elcomercio.pe", "larepublica.pe"),
        "WORLD": ("xataka.com", "theverge.com", "techcrunch.com", "wired.com"),
    },
    "Finanzas, Negocios y Criptomonedas": {
        "PE": ("gestion.pe", "andina.pe", "rpp.pe", "larepublica.pe"),
        "WORLD": ("reuters.com", "cnbc.com", "expansion.com", "apnews.com"),
    },
    "Gaming y Esports": {
        "PE": ("rpp.pe", "elcomercio.pe", "infobae.com", "larepublica.pe"),
        "WORLD": ("vidaextra.com", "ign.com", "3djuegos.com", "gamespot.com"),
    },
    "Salud, Bienestar y Estilo de Vida": {
        "PE": ("rpp.pe", "andina.pe", "elcomercio.pe", "larepublica.pe"),
        "WORLD": ("sciencedaily.com", "medicalxpress.com", "statnews.com", "apnews.com"),
    },
    "Tendencias": {
        "PE": ("rpp.pe", "andina.pe", "elcomercio.pe", "larepublica.pe"),
        "WORLD": ("elpais.com", "wired.com", "bbc.com", "apnews.com"),
    },
}

BUSQUEDAS_ESPECIALIZADAS = {
    "Deportes en Vivo": ("(fútbol OR tenis OR vóley OR baloncesto)", "(football OR soccer OR tennis OR basketball OR fútbol)"),
    "Entretenimiento, Farandula y Cine": ("(cine OR música OR concierto OR artistas)", "(film OR movie OR music OR concert OR cine)"),
    "Noticias de Ultima Hora y Politica": ("(gobierno OR elecciones OR congreso OR parlamento)", "(government OR election OR congress OR parliament)"),
    "Tecnologia, Gadgets e Inteligencia Artificial": ("(tecnología OR inteligencia artificial OR gadgets)", "(technology OR artificial intelligence OR gadgets OR tecnología)"),
    "Finanzas, Negocios y Criptomonedas": ("(economía OR empresas OR mercados OR bitcoin)", "(economy OR business OR markets OR bitcoin OR economía)"),
    "Gaming y Esports": ("(videojuegos OR esports OR Nintendo OR PlayStation)", "(videogames OR esports OR Nintendo OR PlayStation OR videojuegos)"),
    "Salud, Bienestar y Estilo de Vida": ("(salud OR medicina OR investigación OR hospital)", "(health OR medicine OR clinical OR research)"),
    "Tendencias": ("(viral OR cultura OR sociedad OR tendencias)", "(viral OR culture OR society OR trends OR cultura)"),
}

CATEGORY_CUES = {
    "Deportes en Vivo": {"deporte", "deportes", "futbol", "tenis", "voley", "voleibol", "baloncesto", "basket", "basquet", "nba", "liga", "copa", "seleccion", "gol", "partido", "atleta", "deportista", "sporting", "alianza", "universitario", "entrenador", "fichaje", "football", "soccer", "tennis", "basketball", "volleyball"},
    "Entretenimiento, Farandula y Cine": {"cine", "pelicula", "peliculas", "serie", "series", "musica", "concierto", "conciertos", "artista", "actor", "actriz", "festival", "estreno", "television", "streaming", "famoso", "famosos", "film", "movie", "music", "concert", "actress"},
    "Noticias de Ultima Hora y Politica": {"gobierno", "congreso", "presidente", "presidencia", "elecciones", "electoral", "ministro", "senado", "parlamento", "alcalde", "cancilleria", "politica", "votacion", "tribunal", "government", "congress", "parliament", "election", "president", "minister"},
    "Tecnologia, Gadgets e Inteligencia Artificial": {"tecnologia", "tecnologico", "inteligencia", "artificial", "openai", "chatgpt", "gemini", "software", "hardware", "robot", "robots", "digital", "chip", "chips", "smartphone", "computadora", "aplicacion", "internet", "ciberseguridad", "technology", "gadgets", "cybersecurity"},
    "Finanzas, Negocios y Criptomonedas": {"economia", "economico", "finanzas", "financiero", "mercado", "bolsa", "empresa", "empresas", "negocio", "negocios", "inversion", "inversiones", "banco", "bancos", "bitcoin", "criptomonedas", "dolares", "millones", "logistico", "logistica", "ventas", "capital", "inflacion", "economy", "financial", "business", "markets", "bank", "investment", "inflation"},
    "Gaming y Esports": {"gaming", "esports", "videojuego", "videojuegos", "juego", "juegos", "consola", "nintendo", "playstation", "xbox", "steam", "twitch", "torneo", "2k", "videogames", "videogame", "games", "console"},
    "Salud, Bienestar y Estilo de Vida": {"salud", "medicina", "medico", "medicos", "hospital", "clinica", "paciente", "pacientes", "vacuna", "vacunas", "enfermedad", "tratamiento", "bienestar", "nutricion", "ejercicio", "terapia", "investigacion", "health", "medicine", "medical", "disease", "hospital", "patient", "vaccine", "cancer", "diet", "nutrition", "clinical", "trial", "brain", "bacteria"},
}

TREND_CUES = {"viral", "virales", "tendencia", "tendencias", "moda", "redes", "tiktok", "streamer", "streamers", "creador", "creadores", "bts", "army", "fenomeno", "cultura", "consumo", "reto", "memes", "influencer", "influencers", "trend", "trends", "culture"}
TREND_EXCLUSIONS = {"elecciones", "electoral", "escrutinio", "presidente", "gobierno", "parlamento"}
GAMBLING_CUES = {"apuestas", "apuesta", "casino", "casinos", "loteria", "tragamonedas", "ludopatia", "clandestino", "clandestinas", "clandestinos", "azar", "betting", "igaming"}
VIDEO_GAME_CUES = {"videojuego", "videojuegos", "esports", "nintendo", "playstation", "xbox", "steam", "consola", "consolas", "gamer", "epic"}


def matches_category(item, categoria):
    """Require a visible topic signal unless the publisher feed is section-specific."""
    terms = keywords(" ".join((item.get("titulo", ""), item.get("snippet", ""))))
    if categoria == "Tendencias":
        return bool(terms & TREND_CUES) and not bool(terms & TREND_EXCLUSIONS)
    if categoria == "Gaming y Esports":
        gambling_terms = terms | keywords(item.get("url", ""))
        if ((gambling_terms & GAMBLING_CUES) or "juego online" in item.get("titulo", "").lower()) and not terms & VIDEO_GAME_CUES:
            return False
    if item.get("origen") == "local_rss" and "/tvmas/" not in item.get("url", ""):
        return True
    return bool(terms & CATEGORY_CUES.get(categoria, set()))

CATEGORY_SEARCH_QUERIES = {
    "Deportes en Vivo": ("selección fútbol liga clubes", "fútbol tenis baloncesto"),
    "Entretenimiento, Farandula y Cine": ("conciertos cine estrenos artistas", "cine música artistas estrenos"),
    "Noticias de Ultima Hora y Politica": ("congreso gobierno elecciones", "gobierno parlamento elecciones"),
    "Tecnologia, Gadgets e Inteligencia Artificial": ("tecnología inteligencia artificial empresas", "tecnología inteligencia artificial lanzamiento"),
    "Finanzas, Negocios y Criptomonedas": ("economía bancos empresas inversión", "economía empresas mercados"),
    "Gaming y Esports": ("videojuegos esports lanzamientos", "videojuegos esports torneos"),
    "Salud, Bienestar y Estilo de Vida": ("salud hospitales investigación médica", "salud investigación medicina"),
    "Tendencias": ("tendencias cultura sociedad", "tendencias cultura sociedad"),
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


def _extract_direct_rss(urls, max_items, origin):
    if not urls:
        return []
    noticias = []
    for url in urls:
        try:
            response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
        except requests.RequestException as exc:
            print(f"  [Local RSS] {source_host(url)}: {type(exc).__name__}")
            continue
        for entry in feed.entries[:max_items]:
            link = entry.get("link", "")
            if not link:
                continue
            noticias.append({
                "titulo": entry.get("title", ""),
                "url": link,
                "fecha": entry.get("published", ""),
                "fuente": source_host(link),
                "snippet": unescape(re.sub(r"<[^>]+>", " ", entry.get("description", "")))[:500],
                "origen": origin,
            })

    return noticias


def extract_news_local_rss(categoria, max_items=3):
    """Read verified Peruvian section feeds."""
    return _extract_direct_rss(FUENTES_LOCALES_PERU.get(categoria, []), max_items, "local_rss")


def extract_news_world_rss(categoria, max_items=3):
    """Read specialist feeds for international stories."""
    return _extract_direct_rss(FUENTES_INTERNACIONALES.get(categoria, []), max_items, "direct_rss")


def extract_news_specialist_sources(categoria, geo="PE", lang=None, max_items=20):
    """Search current news from category-specific publishers in one RSS request."""
    region = "PE" if geo == "PE" else "WORLD"
    domains = FUENTES_ESPECIALIZADAS.get(categoria, {}).get(region, ())
    topics = BUSQUEDAS_ESPECIALIZADAS.get(categoria)
    if not domains or not topics:
        return []
    sites = " OR ".join(f"site:{domain}" for domain in domains)
    location = " (Perú OR Lima OR Arequipa OR Cusco OR Trujillo)" if region == "PE" else ""
    query = f"{topics[0 if region == 'PE' else 1]} ({sites}){location} when:4d"
    results = extract_custom_topic_google_rss(query, lang=lang, geo=geo, max_items=max_items)
    return [{**item, "origen": "specialist_rss"} for item in results]


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
    :param categoria: Nombre exacto de una de las 8 categorias.
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


def extract_bing_news_rss(topic, max_items=20):
    """Independent news index for finding additional publisher URLs."""
    url = "https://www.bing.com/news/search?q=" + quote(topic) + "&format=rss&setlang=es"
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
    except Exception as exc:
        print(f"  [Bing News RSS] No disponible: {type(exc).__name__}")
        return []
    results = []
    for entry in feed.entries[:max_items]:
        redirect = urlparse(entry.get("link", ""))
        destination = parse_qs(redirect.query).get("url", [entry.get("link", "")])[0]
        parsed = urlparse(destination)
        if parsed.scheme != "https" or not parsed.hostname or social_source(destination):
            continue
        results.append({
            "titulo": entry.get("title", ""),
            "url": destination,
            "fecha": entry.get("published", ""),
            "fuente": source_host(destination),
            "snippet": unescape(re.sub(r"<[^>]+>", " ", entry.get("description", "")))[:500],
            "origen": "bing_rss",
        })
    return results


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
    Orden: RSS de secciones -> medios especializados -> Google general -> Bing -> API opcionales.
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
            if social_source(url, outlet) or outlet == "wordpress.com":
                continue
            if not matches_category(item, categoria):
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
        if geo == "PE":
            print("    Intentando RSS cultural peruano para Tendencias...")
            add_candidates(extract_news_local_rss(categoria, max_items=max_items * 2), limit=1)
        if len(selected) < max_items:
            add_candidates(extract_news_specialist_sources(categoria, geo=geo, lang=lang, max_items=max_items * 6), limit=2)
        topic = "noticias virales Perú" if geo == "PE" else "noticias virales mundo"
        if len(selected) < max_items:
            candidates = extract_custom_topic_google_rss(topic + " when:4d", lang=lang, geo=geo, max_items=max_items * 6)
            add_candidates(candidates)
        if len(selected) < max_items:
            topic = "tendencias Perú" if geo == "PE" else "tendencias internacionales"
            add_candidates(extract_custom_topic_google_rss(topic + " when:4d", lang=lang, geo=geo, max_items=max_items * 6))
        if len(selected) < max_items:
            add_candidates(extract_bing_news_rss(topic, max_items=max_items * 8))
        print(f"    -> {len(selected)}/{max_items} candidatas de {len(outlet_counts)} medios")
        return selected

    # Un titular local deja espacio para otros medios peruanos en Google News.
    if geo == "PE" and categoria in FUENTES_LOCALES_PERU:
        print(f"    Intentando Fuente Local Directa (Perú) para {categoria}...")
        add_candidates(extract_news_local_rss(categoria, max_items=max_items * 2), limit=1)
    elif geo != "PE" and categoria in FUENTES_INTERNACIONALES:
        print(f"    Intentando RSS especializado internacional para {categoria}...")
        add_candidates(extract_news_world_rss(categoria, max_items=max_items * 2), limit=1)

    if len(selected) < max_items:
        print(f"    Buscando medios especializados de {categoria} ({geo})...")
        add_candidates(extract_news_specialist_sources(categoria, geo=geo, lang=lang, max_items=max_items * 6), limit=2)

    if len(selected) < max_items:
        print(f"    Intentando Google News RSS (geo={geo})...")
        add_candidates(extract_news_google_rss(categoria, max_items=max_items * 6, lang=lang, geo=geo), limit=max(1, max_items - 2))

    if len(selected) < max_items:
        base_topic = CATEGORY_SEARCH_QUERIES.get(categoria, (categoria, categoria))[0 if geo == "PE" else 1]
        topic = f"{base_topic} Perú when:4d" if geo == "PE" else f"{base_topic} when:4d"
        print("    Ampliando con búsqueda temática de Google News...")
        add_candidates(extract_custom_topic_google_rss(topic, lang=lang, geo=geo, max_items=max_items * 6))

    if len(selected) < max_items:
        print("    Ampliando con Bing News RSS...")
        add_candidates(extract_bing_news_rss(topic, max_items=max_items * 8))

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
