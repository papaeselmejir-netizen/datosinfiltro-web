"""
Módulo de multimedia: Imágenes y Videos para artículos de noticias.

Cadena de fallback para IMÁGENES:
  1. Google Images Scraping (gratis, ilimitado, máxima relevancia)
  2. Brave Search API ($5/mes gratis = ~1,000 búsquedas, muy estable)
  3. Google Custom Search API (100/día, ya configurada)

Para VIDEOS:
  1. YouTube Data API (ya configurada)

Nota: Bing Search v7 fue retirado por Microsoft en agosto 2025.
Usamos Brave Search como fallback en su lugar.
"""
import os
import re
import json
import requests
from urllib.parse import quote_plus, urljoin, urlparse, parse_qs
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from src.editorial import keywords, query_terms, relevance

load_dotenv()

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
GOOGLE_CX = os.getenv("GOOGLE_CX", "")
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")

# User-Agents rotativos para scraping
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]

_ua_index = 0


def _get_next_ua():
    """Rota entre User-Agents para evitar bloqueos."""
    global _ua_index
    ua = _USER_AGENTS[_ua_index % len(_USER_AGENTS)]
    _ua_index += 1
    return ua


def _extract_keywords(titulo, max_words=4):
    """
    Extrae palabras clave relevantes del titulo para buscar multimedia.
    Elimina stopwords en español para mejorar la precision de busqueda.
    """
    stopwords = {
        "el", "la", "los", "las", "un", "una", "de", "del", "en", "al",
        "y", "o", "que", "por", "con", "para", "es", "se", "su", "como",
        "mas", "pero", "si", "no", "ya", "ha", "fue", "son", "ser", "este",
        "esta", "eso", "esto", "a", "e", "i", "u", "lo", "le", "les",
        "muy", "ni", "sin", "sobre", "entre", "cada", "todo", "mi", "tu",
        "nos", "te", "me", "su", "sus", "dos", "tres", "qué", "cómo",
        "tras", "ante", "bajo", "según", "hacia", "desde",
    }
    # Limpiar caracteres especiales
    clean = re.sub(r"[^\w\s]", "", titulo.lower())
    words = [w for w in clean.split() if w not in stopwords and len(w) > 2]
    return " ".join(words[:max_words])


# =============================================================================
# FUENTE 1: Google Images Scraping (PRINCIPAL - Gratis e Ilimitada)
# =============================================================================

def _is_valid_image_url(url):
    """Valida que una URL sea una imagen real y no un tracking pixel o icono."""
    if not url or len(url) < 20:
        return False
    if not url.startswith("http"):
        return False
    # Filtrar data URIs, tracking pixels, logos, etc.
    skip_patterns = [
        "data:image", "1x1", "pixel", "tracker", "logo", "icon",
        "avatar", "badge", "emoji", ".gif", "gravatar", "blank",
        "gstatic.com/images", "google.com/images", "googleapis.com/images",
        "encrypted-tbn", "widget", "sprite", "arrow", "button", "googleusercontent.com"
    ]
    url_lower = url.lower()
    return not any(skip in url_lower for skip in skip_patterns)


def _extract_images_from_google_html(html_content, count=5):
    """
    Extrae URLs de imágenes del HTML de resultados de Google Images.
    Busca las imágenes en los datos JSON embebidos y en los elementos <img>.
    """
    images = []
    seen = set()

    # Estrategia 1: Buscar URLs de imagen en los scripts JSON de la página
    # Google embebe las URLs originales en scripts tipo AF_initDataCallback
    # Las URLs aparecen como strings que comienzan con http y terminan en extensiones de imagen
    img_pattern = re.compile(
        r'\"(https?://[^\"]{30,}\.(?:jpg|jpeg|png|webp)(?:\?[^\"]*)?)\",\s*\d{2,5},\s*\d{2,5}',
        re.IGNORECASE
    )
    for match in img_pattern.finditer(html_content):
        url = match.group(1)
        # Decodificar unicode escapes como \u003d
        url = url.encode().decode('unicode_escape', errors='ignore')
        if _is_valid_image_url(url) and url not in seen:
            seen.add(url)
            images.append(url)
            if len(images) >= count:
                return images

    # Estrategia 2: Buscar en atributos data-src de los thumbnails
    soup = BeautifulSoup(html_content, "html.parser")

    # Los resultados de Google Images usan divs con data-id y contienen <img> con src
    for img_tag in soup.find_all("img"):
        src = img_tag.get("data-src") or img_tag.get("data-iurl") or ""
        if _is_valid_image_url(src) and src not in seen:
            seen.add(src)
            images.append(src)
            if len(images) >= count:
                return images

    # Estrategia 3: Buscar URLs en links que apuntan a imgres (Google Image redirect)
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if "/imgres?" in href:
            parsed = parse_qs(urlparse(href).query)
            img_url = parsed.get("imgurl", [None])[0]
            if img_url and _is_valid_image_url(img_url) and img_url not in seen:
                seen.add(img_url)
                images.append(img_url)
                if len(images) >= count:
                    return images

    return images


def search_google_images_scraping(titulo, count=3):
    """
    Busca imágenes relevantes haciendo scraping de Google Images.
    Usa el TÍTULO COMPLETO de la noticia (no keywords) para máxima relevancia.
    
    :param titulo: Título completo de la noticia
    :param count: Número de imágenes a obtener
    :return: Lista de URLs de imágenes
    """
    # Usar título completo para búsqueda más precisa
    query = quote_plus(titulo)
    url = f"https://www.google.com/search?q={query}&tbm=isch&hl=es&num=20"

    headers = {
        "User-Agent": _get_next_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "es-PE,es;q=0.9,en-US;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Chromium";v="125", "Not=A?Brand";v="8"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        images = _extract_images_from_google_html(response.text, count=count)

        if images:
            print(f"    [Google Scraping] {len(images)} imágenes encontradas para: '{titulo[:50]}...'")
        else:
            print(f"    [Google Scraping] Sin resultados para: '{titulo[:50]}...'")

        return images[:count]

    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        print(f"    [Google Scraping] HTTP {status} - Posible bloqueo temporal")
        return []
    except Exception as e:
        print(f"    [Google Scraping] Error: {e}")
        return []


# =============================================================================
# FUENTE 2: Brave Search API (FALLBACK - $5/mes gratis = ~1,000 búsquedas)
# Bing Search v7 fue retirado por Microsoft en agosto 2025.
# Brave Search es la mejor alternativa: índice propio, imágenes de noticias.
# Registrarse en: https://brave.com/search/api/
# =============================================================================

def search_brave_images(titulo, count=3):
    """
    Busca imágenes usando Brave Search API.
    Cada cuenta recibe $5/mes en créditos gratuitos = ~1,000 búsquedas.
    
    Ventaja: Índice independiente con imágenes reales de noticias.
    
    :param titulo: Título de la noticia
    :param count: Número de imágenes
    :return: Lista de URLs de imágenes
    """
    if not BRAVE_API_KEY:
        return []

    try:
        response = requests.get(
            "https://api.search.brave.com/res/v1/images/search",
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": BRAVE_API_KEY,
            },
            params={
                "q": titulo,  # Título COMPLETO para máxima relevancia
                "count": count,
                "safesearch": "strict", # 'moderate' causes 422 on images endpoint
                "search_lang": "es",
                "country": "ALL", # 'PE' is not supported by Brave API
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        images = []
        for result in data.get("results", []):
            # Brave devuelve 'properties.url' con la imagen original
            img_url = result.get("properties", {}).get("url", "") or result.get("thumbnail", {}).get("src", "")
            if _is_valid_image_url(img_url):
                images.append(img_url)

        if images:
            print(f"    [Brave API] {len(images)} imágenes encontradas")
        return images[:count]

    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        if status == 401:
            print(f"    [Brave API] API key inválida o sin configurar")
        elif status == 429:
            print(f"    [Brave API] Créditos mensuales agotados ($5/mes)")
        else:
            print(f"    [Brave API] HTTP {status}")
        return []
    except Exception as e:
        print(f"    [Brave API] Error: {e}")
        return []


# =============================================================================
# FUENTE 3: Google Custom Search API (FALLBACK FINAL - ya existía)
# =============================================================================

def search_google_image(titulo, count=3):
    """
    Busca imágenes usando Google Custom Search API.
    Límite: 100 queries/día gratis.
    Usa la misma API key de Google Cloud (YOUTUBE_API_KEY) y GOOGLE_CX.
    """
    api_key = YOUTUBE_API_KEY
    cx = GOOGLE_CX

    if not api_key or not cx:
        return []

    try:
        response = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "q": titulo,  # Título completo
                "cx": cx,
                "key": api_key,
                "searchType": "image",
                "num": min(count, 10),
                "safe": "active",
                "imgSize": "large",
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        images = [item["link"] for item in data.get("items", []) if _is_valid_image_url(item.get("link", ""))]

        if images:
            print(f"    [Google CSE] {len(images)} imágenes encontradas")
        return images[:count]

    except Exception as e:
        print(f"    [Google CSE] Error: {e}")
        return []


# =============================================================================
# ORQUESTADOR: Garantiza 3 imágenes con cadena de fallback
# =============================================================================

def search_multimedia_images(titulo, count=3, existing_images=None):
    """
    Busca imágenes para un artículo usando cadena de fallback:
      1. Google Images Scraping (gratis, ilimitado)
      2. Brave Search API ($5/mes gratis = ~1,000 búsquedas)
      3. Google Custom Search API (100/día)
    
    Si ya hay imágenes del crawler, solo busca las que faltan.
    
    :param titulo: Título de la noticia
    :param count: Número total de imágenes deseadas
    :param existing_images: Lista de imágenes ya extraídas del crawler
    :return: Lista de URLs de imágenes (hasta `count` elementos)
    """
    if existing_images is None:
        existing_images = []

    # Filtrar las imágenes del crawler para eliminar iconos, placeholders (como googleusercontent.com)
    existing_images = [url for url in existing_images if _is_valid_image_url(url)]

    # Cuántas imágenes necesitamos buscar
    needed = count - len(existing_images)
    if needed <= 0:
        print(f"    [Multimedia] Ya hay {len(existing_images)} imágenes del crawler. OK.")
        return existing_images[:count]

    print(f"    [Multimedia] Necesito {needed} imagen(es) más (ya hay {len(existing_images)} del crawler)")

    # Recopilar imágenes ya vistas para no duplicar
    seen = set(existing_images)
    all_images = list(existing_images)

    # Cadena de fallback
    sources = [
        ("Google Scraping", lambda: search_google_images_scraping(titulo, count=needed + 2)),
        ("Brave API", lambda: search_brave_images(titulo, count=needed + 2)),
        ("Google CSE", lambda: search_google_image(titulo, count=needed + 2)),
    ]

    for source_name, search_fn in sources:
        if len(all_images) >= count:
            break

        results = search_fn()
        for img_url in results:
            if img_url not in seen and _is_valid_image_url(img_url):
                seen.add(img_url)
                all_images.append(img_url)
                if len(all_images) >= count:
                    break

    found = len(all_images) - len(existing_images)
    print(f"    [Multimedia] Total: {len(all_images)} imágenes ({found} nuevas encontradas)")

    return all_images[:count]


# =============================================================================
# VIDEO: YouTube Data API (ya existente, optimizada)
# =============================================================================

def search_youtube_video(titulo):
    """
    Busca un video de YouTube relacionado al titulo de la noticia.
    Optimizado con filtro de frescura para obtener videos de noticias recientes.
    
    :param titulo: Titulo de la noticia
    :return: URL embebible del video (para iframe) o string vacio
    """
    if not YOUTUBE_API_KEY:
        return ""

    keywords = _extract_keywords(titulo, max_words=5)
    if not keywords:
        return ""

    try:
        # Calcular fecha de hace 7 días para filtrar videos recientes
        from datetime import datetime, timedelta
        week_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

        response = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet",
                "q": keywords,
                "type": "video",
                "maxResults": 1,
                "relevanceLanguage": "es",
                "videoEmbeddable": "true",
                "order": "relevance",
                "publishedAfter": week_ago,
                "key": YOUTUBE_API_KEY,
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        items = data.get("items", [])

        # Si no hay resultados recientes, buscar sin filtro de fecha
        if not items:
            response = requests.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "part": "snippet",
                    "q": keywords,
                    "type": "video",
                    "maxResults": 1,
                    "relevanceLanguage": "es",
                    "videoEmbeddable": "true",
                    "order": "relevance",
                    "key": YOUTUBE_API_KEY,
                },
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            items = data.get("items", [])

        if items:
            video_id = items[0]["id"]["videoId"]
            embed_url = f"https://www.youtube.com/embed/{video_id}"
            video_title = items[0]["snippet"]["title"]
            print(f"    [YouTube] Video encontrado: '{video_title[:50]}...'")
            return embed_url

        return ""

    except Exception as e:
        print(f"    [YouTube] Error: {e}")
        return ""


# =============================================================================
# LEGACY: Pexels (mantener por compatibilidad pero ya no se usa como principal)
# =============================================================================

def search_pexels_images(titulo, count=3):
    """
    Busca imagenes en Pexels. LEGACY - Solo como último recurso.
    Las imágenes de Pexels son genéricas y NO corresponden a noticias reales.
    """
    if not PEXELS_API_KEY:
        return []

    keywords = _extract_keywords(titulo)
    if not keywords:
        return []

    try:
        response = requests.get(
            "https://api.pexels.com/v1/search",
            params={"query": keywords, "per_page": count, "orientation": "landscape"},
            headers={"Authorization": PEXELS_API_KEY},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        images = []
        for photo in data.get("photos", []):
            img_url = photo.get("src", {}).get("large", "")
            if img_url:
                images.append(img_url)

        if images:
            print(f"    [Pexels] {len(images)} imagenes encontradas (genéricas)")
        return images

    except Exception as e:
        print(f"    [Pexels] Error: {e}")
        return []


def search_licensed_images(titulo, count=2):
    """Return topic-matched images with recorded reuse terms."""
    matches = []
    if PEXELS_API_KEY:
        matches = _search_pexels_licensed(titulo, count)
    if len(matches) < count:
        commons = search_commons_images(titulo, count - len(matches))
        matches.extend(item for item in commons if item["url"] not in {match["url"] for match in matches})
    return matches[:count]


def _stock_topic(titulo):
    """Translate a few unambiguous Spanish news topics into stock-media searches."""
    terms = keywords(titulo)
    topics = (
        ({"cine", "cinema", "cinematografica", "audiovisual", "audiovisuales", "pelicula", "peliculas"},
         "film camera production", {"film", "filming", "filmmaking", "camera", "cinema", "movie", "videography", "video"}),
        ({"gadgets", "hardware", "dispositivo", "dispositivos", "sdk", "electronica"},
         "electronics circuit board", {"electronic", "electronics", "circuit", "board", "chip", "microchip", "motherboard", "hardware", "soldering"}),
        ({"whatsapp", "instagram", "facebook", "meta"},
         "instagram whatsapp smartphone" if {"instagram", "whatsapp"} <= terms else "smartphone social media",
         {"smartphone", "phone", "mobile", "social", "media", "app", "screen", "device", "chat", "messaging"}),
        ({"desvios", "viales", "cierres", "carreteras", "trafico", "transito", "vehicular", "movilidad", "transporte", "metropolitano"},
         "traffic jam city", {"traffic", "road", "street", "car", "cars", "vehicle", "vehicles", "bus", "transport", "transit", "train"}),
        ({"premios", "ariel", "galardones", "alfombra"},
         "film awards red carpet", {"award", "awards", "carpet", "cinema", "film", "movie", "trophy"}),
        ({"escuela", "universidad", "estudiantes", "campus"},
         "artificial intelligence university", {"robot", "robotic", "technology", "computer", "computers", "digital", "intelligence", "laboratory", "school", "students"}),
    )
    for cues, query, media_terms in topics:
        if terms & cues:
            return query, media_terms
    return None


def _search_pexels_licensed(titulo, count):
    topic = _stock_topic(titulo)
    queries = [query_terms(titulo, 5)]
    if topic:
        prioritize_stock = bool(keywords(titulo) & {"cine", "cinema", "cinematografica", "audiovisual", "audiovisuales", "pelicula", "peliculas", "gadgets", "hardware", "dispositivo", "dispositivos", "sdk", "electronica"}) or {"instagram", "whatsapp"} <= keywords(titulo)
        queries = [topic[0], queries[0]] if prioritize_stock else [queries[0], topic[0]]
    if not queries[0]:
        return []
    matches = []
    seen = set()
    for query in dict.fromkeys(queries):
        if len(matches) >= count:
            break
        try:
            response = requests.get(
                "https://api.pexels.com/v1/search",
                params={"query": query, "per_page": 40, "orientation": "landscape"},
                headers={"Authorization": PEXELS_API_KEY}, timeout=12,
            )
            response.raise_for_status()
            photos = response.json().get("photos", [])
        except Exception as exc:
            print(f"    [Pexels] No se pudieron validar imágenes: {type(exc).__name__}")
            continue
        for photo in photos:
            description = photo.get("alt") or ""
            description_terms = keywords(description)
            if not description or not (
                (topic and query == topic[0] and description_terms & topic[1])
                or keywords(titulo) & description_terms
            ):
                continue
            lowered = description.lower()
            if "lima" in keywords(titulo) and any(place in lowered for place in ("buenos aires", "argentina", "madrid")):
                continue
            if topic and not (description_terms & topic[1]):
                continue
            url = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("large")
            if not url or url in seen:
                continue
            seen.add(url)
            matches.append({
                "url": url, "descripcion": description,
                "credito": photo.get("photographer", "Pexels"),
                "origen": photo.get("url", ""),
                "licencia": "Pexels License",
                "licencia_url": "https://www.pexels.com/license/",
                "tipo": "Ilustración de archivo",
            })
            if len(matches) >= count:
                break
    return matches


def search_commons_images(titulo, count=2):
    """Use Commons file metadata to keep attribution and license alongside images."""
    if count <= 0:
        return []
    query = query_terms(titulo, 5)
    if not query:
        return []
    try:
        response = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query", "format": "json", "formatversion": 2,
                "generator": "search", "gsrsearch": query, "gsrnamespace": 6,
                "gsrlimit": 20, "prop": "imageinfo", "iiprop": "url|extmetadata|size",
                "iiurlwidth": 1200,
                "iiextmetadatafilter": "LicenseShortName|LicenseUrl|Artist|ImageDescription",
            },
            headers={"User-Agent": "DatoSinFiltro/0.2 (editorial image research)"},
            timeout=15,
        )
        response.raise_for_status()
        matches = []
        for page in response.json().get("query", {}).get("pages", []):
            title = page.get("title", "").removeprefix("File:")
            if not page.get("imageinfo") or "logo" in title.lower():
                continue
            info = page["imageinfo"][0]
            if info.get("width", 0) < 800 or info.get("height", 0) < 400:
                continue
            metadata = info.get("extmetadata", {})
            license_name = BeautifulSoup(metadata.get("LicenseShortName", {}).get("value", ""), "html.parser").get_text(" ", strip=True)
            normalized_license = license_name.lower()
            if not any(value in normalized_license for value in ("cc by", "cc0", "public domain")) or re.search(r"\b(?:nc|nd)\b", normalized_license):
                continue
            license_url = metadata.get("LicenseUrl", {}).get("value", "") or "https://commons.wikimedia.org/wiki/Commons:Licensing"
            author = BeautifulSoup(metadata.get("Artist", {}).get("value", ""), "html.parser").get_text(" ", strip=True)
            description = BeautifulSoup(metadata.get("ImageDescription", {}).get("value", ""), "html.parser").get_text(" ", strip=True) or title
            if not (keywords(titulo) & keywords(f"{title} {description}")):
                continue
            url = info.get("thumburl") or info.get("url", "")
            if not url.startswith("https://"):
                continue
            matches.append({
                "url": url,
                "descripcion": description[:180],
                "credito": author[:140] or "Wikimedia Commons",
                "origen": "https://commons.wikimedia.org/wiki/" + page["title"].replace(" ", "_"),
                "licencia": license_name,
                "licencia_url": license_url,
                "tipo": "Ilustración de archivo",
            })
            if len(matches) >= count:
                break
        return matches
    except Exception as exc:
        print(f"    [Commons] No se pudieron validar imágenes: {exc}")
        return []


def search_relevant_youtube_video(titulo):
    """Choose a recent embeddable video whose title shares the story's terms."""
    if not YOUTUBE_API_KEY:
        return None
    from datetime import datetime, timedelta, timezone
    query = query_terms(titulo, 6)
    anchor_terms = set(query_terms(titulo, 3).split())
    if not query:
        return None
    try:
        response = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet", "q": query, "type": "video", "maxResults": 10,
                "relevanceLanguage": "es", "videoEmbeddable": "true",
                "order": "relevance",
                "publishedAfter": (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "key": YOUTUBE_API_KEY,
            }, timeout=12,
        )
        response.raise_for_status()
        matches = []
        for item in response.json().get("items", []):
            video_id = item.get("id", {}).get("videoId", "")
            snippet = item.get("snippet", {})
            score = relevance(titulo, snippet.get("title", ""))
            video_terms = keywords(snippet.get("title", ""))
            if len(video_id) == 11 and score >= 0.4 and len(keywords(titulo) & video_terms) >= 2 and anchor_terms & video_terms:
                matches.append((score, {
                    "url": f"https://www.youtube.com/embed/{video_id}",
                    "titulo": snippet.get("title", ""),
                    "canal": snippet.get("channelTitle", ""),
                    "fecha": snippet.get("publishedAt", ""),
                }))
        return max(matches, key=lambda item: item[0])[1] if matches else None
    except Exception as exc:
        status = exc.response.status_code if isinstance(exc, requests.HTTPError) and exc.response is not None else type(exc).__name__
        print(f"    [YouTube] No se pudo validar video ({status})")
        return None


def search_licensed_stock_video(titulo):
    """Find clearly labelled illustrative footage when no event-specific video exists."""
    if not PEXELS_API_KEY:
        return None
    title_terms = keywords(titulo)
    topic = _stock_topic(titulo)
    query = topic[0] if topic else query_terms(titulo, 4)
    if not query:
        return None
    try:
        response = requests.get(
            "https://api.pexels.com/videos/search",
            params={"query": query, "per_page": 40, "orientation": "landscape"},
            headers={"Authorization": PEXELS_API_KEY}, timeout=15,
        )
        response.raise_for_status()
        for video in response.json().get("videos", []):
            origin = video.get("url", "")
            slug = origin.rsplit("/video/", 1)[-1].rsplit("/", 1)[0].replace("-", " ")
            slug_terms = keywords(slug)
            if topic:
                if not (slug_terms & topic[1]):
                    continue
            elif len(title_terms & slug_terms) < 2:
                continue
            files = [item for item in video.get("video_files", []) if item.get("file_type") == "video/mp4" and item.get("width") and item.get("width") <= 1920]
            if not files:
                continue
            file = max(files, key=lambda item: item["width"])
            if urlparse(file.get("link", "")).hostname != "videos.pexels.com":
                continue
            return {
                "url": file["link"], "titulo": slug.capitalize(),
                "canal": video.get("user", {}).get("name", "Pexels"),
                "origen": origin, "licencia": "Pexels License",
                "licencia_url": "https://www.pexels.com/license/",
                "poster": video.get("image", ""), "source": "pexels",
                "tipo": "Video ilustrativo de archivo",
            }
    except Exception as exc:
        status = exc.response.status_code if isinstance(exc, requests.HTTPError) and exc.response is not None else type(exc).__name__
        print(f"    [Pexels Video] No se pudo validar video ({status})")
    return None


def search_relevant_video(titulo):
    video = search_relevant_youtube_video(titulo)
    if video:
        video["source"] = "youtube"
        video["tipo"] = "Video relacionado del canal original"
        return video
    return search_licensed_stock_video(titulo)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    test_titulo = "Streamer famoso es detenido por las autoridades en Lima"
    print(f"Test titulo: {test_titulo}")
    print(f"Keywords: {_extract_keywords(test_titulo)}")

    print("\n--- Google Images Scraping ---")
    imgs = search_google_images_scraping(test_titulo, count=3)
    for i, img in enumerate(imgs, 1):
        print(f"  {i}. {img[:100]}...")

    print("\n--- Bing Image Search API ---")
    imgs = search_bing_images(test_titulo, count=3)
    for i, img in enumerate(imgs, 1):
        print(f"  {i}. {img[:100]}...")

    print("\n--- Orquestador (cadena completa) ---")
    imgs = search_multimedia_images(test_titulo, count=3)
    for i, img in enumerate(imgs, 1):
        print(f"  {i}. {img[:100]}...")

    print("\n--- YouTube ---")
    video = search_youtube_video(test_titulo)
    print(f"  Video: {video}")
