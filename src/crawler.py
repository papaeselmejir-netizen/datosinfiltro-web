import requests
from bs4 import BeautifulSoup
import asyncio
import re
import ipaddress
import socket
from urllib.parse import urljoin, urlparse
from googlenewsdecoder import gnewsdecoder
from src.editorial import near_duplicate_text, social_source, source_host


def decode_google_news_url(google_news_url):
    """
    Decodifica una URL de Google News RSS para obtener la URL real del articulo.
    Usa el paquete googlenewsdecoder que llama a la API interna de Google.
    """
    try:
        result = gnewsdecoder(google_news_url)
        if result.get("success") or result.get("status"):
            return result["decoded_url"]
        else:
            print(f"    No se pudo decodificar: {result.get('message', 'Error desconocido')}")
            return None
    except Exception as e:
        print(f"    Error decodificando URL: {e}")
        return None


# Headers mejorados para reducir bloqueos 403
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "es-PE,es;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Sec-Ch-Ua": '"Chromium";v="125", "Not=A?Brand";v="8", "Google Chrome";v="125"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}

# Headers alternativos para retry en caso de bloqueo
ALT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-PE,es;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}


def _truncate_at_sentence(text, max_length=2500):
    """
    Corta el texto al final de la ultima oracion completa antes del limite.
    Evita cortar a mitad de palabra o frase.
    """
    if len(text) <= max_length:
        return text

    # Buscar el ultimo punto seguido de espacio o fin de texto antes del limite
    truncated = text[:max_length]
    last_period = -1

    # Buscar el ultimo separador de oracion (. ! ?)
    for sep in [". ", ".\n", "! ", "!\n", "? ", "?\n"]:
        pos = truncated.rfind(sep)
        if pos > last_period:
            last_period = pos

    if last_period > max_length * 0.4:
        # Cortar despues del ultimo punto (incluir el punto)
        return truncated[:last_period + 1].strip()
    else:
        # Si no hay punto razonable, cortar en el ultimo espacio
        last_space = truncated.rfind(" ")
        if last_space > 0:
            return truncated[:last_space].strip() + "..."
    return truncated.strip() + "..."


def _public_url(url):
    parsed = urlparse(url or "")
    host = parsed.hostname or ""
    if parsed.scheme not in ("http", "https") or not host or parsed.username or parsed.password:
        return False
    if host == "localhost" or host.endswith((".local", ".internal")):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True


def _public_dns(url):
    parsed = urlparse(url)
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        return bool(addresses) and all(ipaddress.ip_address(address[4][0]).is_global for address in addresses)
    except (OSError, ValueError, TypeError):
        return False


def _extract_text_sync(url, headers=None):
    """
    Descarga y extrae el texto principal de una URL de articulo y su imagen destacada.
    Funcion sincrona que sera ejecutada en un thread separado.
    """
    if headers is None:
        headers = BROWSER_HEADERS

    try:
        if not _public_url(url) or not _public_dns(url):
            return "", "", [], ""
        for _ in range(5):
            response = requests.get(url, headers=headers, timeout=15, allow_redirects=False)
            if response.status_code not in (301, 302, 303, 307, 308):
                break
            destination = urljoin(url, response.headers.get("Location", ""))
            if not _public_url(destination) or not _public_dns(destination):
                return "", "", [], ""
            url = destination
        else:
            return "", "", [], ""
        response.raise_for_status()

        # Corregir encoding: forzar deteccion automatica
        if response.encoding and response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding

        html_content = response.text

        soup = BeautifulSoup(html_content, "html.parser")

        # Eliminar scripts, estilos y navegacion
        for tag in soup(
            [
                "script", "style", "header", "footer", "nav",
                "aside", "figure", "figcaption", "iframe", "noscript",
                "button", "form", "svg", "video", "audio",
            ]
        ):
            tag.extract()

        # Intentar extraer solo el contenido del articulo
        article = soup.find("article") or soup.find("main")

        if article:
            paragraphs = article.find_all("p")
            if paragraphs:
                text = " ".join(p.get_text(separator=" ", strip=True) for p in paragraphs)
            else:
                text = article.get_text(separator=" ", strip=True)
        else:
            # Fallback: extraer todos los parrafos de la pagina
            paragraphs = soup.find_all("p")
            if paragraphs:
                text = " ".join(p.get_text(separator=" ", strip=True) for p in paragraphs)
            else:
                text = soup.get_text(separator=" ", strip=True)

        # Limpiar espacios multiples y caracteres problematicos (BOM, etc)
        text = re.sub(r"\s+", " ", text).strip()
        text = text.replace("\ufeff", "").replace("\u200b", "")

        # Extraer imagen principal (og:image o twitter:image)
        image_url = ""
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            image_url = og_image["content"]
        else:
            twitter_image = soup.find("meta", attrs={"name": "twitter:image"})
            if twitter_image and twitter_image.get("content"):
                image_url = twitter_image["content"]

        # Extraer imagenes adicionales del cuerpo del articulo
        extra_images = []
        seen_srcs = {image_url} if image_url else set()
        
        # Re-parsear el HTML original para buscar imagenes (no el soup limpio)
        raw_soup = BeautifulSoup(html_content, "html.parser")
        article_el = raw_soup.find("article") or raw_soup.find("main") or raw_soup
        
        for img_tag in article_el.find_all(["img", "source"]):
            # Buscar en todos los atributos comunes de lazy-loading
            src = (img_tag.get("src") or 
                   img_tag.get("data-src") or 
                   img_tag.get("data-lazy-src") or 
                   img_tag.get("data-original") or 
                   img_tag.get("srcset") or "")
            
            # Si es srcset, tomar la primera URL
            if src and "," in src:
                src = src.split(",")[0].split()[0]
                
            if not src or src.startswith("data:image"):
                continue
                
            # Convertir URLs relativas a absolutas
            src = urljoin(url, src.strip())
            
            if src in seen_srcs:
                continue
                
            # Filtrar iconos, avatars, logos, trackers y imagenes tiny
            if any(skip in src.lower() for skip in [
                "logo", "icon", "avatar", "pixel", "badge", "emoji",
                "1x1", "tracker", "ad-", "sponsor", "widget", ".gif",
                "gravatar", "author", "profile", "blank"
            ]):
                continue
                
            # Solo URLs absolutas validas
            if src.startswith("http") and len(src) > 20:
                seen_srcs.add(src)
                extra_images.append(src)
                if len(extra_images) >= 6:  # max 6 extras para tener de donde escoger
                    break

        # Extraer video embebido (YouTube, Vimeo, Dailymotion, etc.)
        video_url = ""
        for iframe in raw_soup.find_all("iframe"):
            iframe_src = iframe.get("src") or ""
            if any(vhost in iframe_src for vhost in ["youtube.com", "youtu.be", "vimeo.com", "dailymotion.com"]):
                video_url = iframe_src
                if not video_url.startswith("http"):
                    video_url = "https:" + video_url
                break
        
        # Si no encontramos iframe, buscar tags <video> con source
        if not video_url:
            video_tag = raw_soup.find("video")
            if video_tag:
                source = video_tag.find("source")
                if source and source.get("src"):
                    video_url = source["src"]
                elif video_tag.get("src"):
                    video_url = video_tag["src"]

        # Corte inteligente por oraciones
        return _truncate_at_sentence(text, max_length=2500), image_url, extra_images, video_url

    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 403:
            # No imprimir error aqui; el caller hara retry con headers alternativos
            raise
        print(f"    Error HTTP extrayendo {url[:60]}...: {e}")
        return "", "", [], ""
    except Exception as e:
        print(f"    Error extrayendo {url[:60]}...: {e}")
        return "", "", [], ""


def extract_text_from_url(url):
    """
    Extrae texto e imagen de una URL con retry automatico usando headers alternativos.
    """
    # Intento 1: Headers principales
    try:
        text, image, extras, video = _extract_text_sync(url, headers=BROWSER_HEADERS)
        if text:
            return text, image, extras, video
    except requests.exceptions.HTTPError:
        pass

    # Intento 2: Headers alternativos (Safari)
    try:
        text, image, extras, video = _extract_text_sync(url, headers=ALT_HEADERS)
        if text:
            return text, image, extras, video
    except requests.exceptions.HTTPError as e:
        print(f"    403 Forbidden (ambos intentos): {url[:60]}...")
        return "", "", [], ""

    return "", "", [], ""


def readable_article_text(text):
    """Do not count compressed or otherwise corrupted bytes as reporting."""
    if len(text or "") < 300:
        return False
    bad = sum(char == "\ufffd" or (ord(char) < 32 and char not in "\n\r\t") for char in text)
    words = re.findall(r"[A-Za-zÀ-ÿ]{3,}", text)
    return bad / len(text) < 0.005 and len(words) >= 45


async def investigate_news(noticias, return_sources=False, required_sources=None):
    """
    Recibe una lista de noticias (con titulo y URL) y extrae el contexto real.
    Ejecuta las peticiones HTTP en threads separados para no bloquear el event loop.
    :param noticias: Lista de dicts con 'titulo', 'url', y opcionalmente 'snippet'
    :return: (contexto_combinado, imagen_principal)
    """
    context_parts = []
    main_image_url = ""
    all_extra_images = []
    main_video_url = ""
    verified_sources = []
    accepted_texts = []

    for i, noticia in enumerate(noticias):
        titulo = noticia["titulo"]
        noticia_url = noticia["url"]
        snippet = noticia.get("snippet", "")
        origen = noticia.get("origen", "google_rss")

        print(f"  [{i+1}/{len(noticias)}] Leyendo: {titulo[:70]}...")

        # Si la noticia ya viene con snippet (GNews/Currents), usarlo como base
        base_context = f"Resumen: {snippet}\n" if snippet else ""

        # Para Google RSS, necesitamos decodificar la URL
        real_url = noticia_url
        if origen in ("google_rss", "google_rss_custom"):
            decoded = await asyncio.to_thread(decode_google_news_url, noticia_url)
            if decoded:
                real_url = decoded
                print(f"    URL real: {real_url[:80]}")
            else:
                if not return_sources:
                    context_parts.append(
                        f"--- Fuente: {titulo} ---\n{base_context}(Solo titulo disponible)"
                    )
                print(f"    URL no decodificable, usando titulo/snippet")
                continue

        if return_sources and social_source(real_url, noticia.get("fuente")):
            print("    Red social; no cuenta como fuente periodística independiente")
            continue

        if return_sources and any(source_host(source["url"]) == source_host(real_url) for source in verified_sources):
            print("    Medio ya verificado; buscando otra fuente independiente")
            continue

        # Extraer texto, imagen, imagenes extra y video del articulo
        text, image, extras, video = await asyncio.to_thread(extract_text_from_url, real_url)
        if text and not readable_article_text(text):
            print("    Texto ilegible o insuficiente; buscando otro medio")
            text = ""

        if image and not main_image_url:
            main_image_url = image
        
        if extras:
            all_extra_images.extend(extras)
        
        if video and not main_video_url:
            main_video_url = video

        if text and len(text) > 100:
            if return_sources and len(text) >= 300 and any(near_duplicate_text(text, accepted) for accepted in accepted_texts):
                print("    Texto sindicado duplicado; no cuenta como fuente independiente")
                continue
            if not return_sources or len(text) >= 300:
                context_parts.append(f"--- Fuente: {titulo} ---\n{base_context}{text}")
            if len(text) >= 300:
                accepted_texts.append(text)
                verified_sources.append({
                    "titulo": titulo,
                    "url": real_url,
                    "medio": noticia.get("fuente", ""),
                    "fecha": noticia.get("fecha", ""),
                })
                if return_sources and required_sources and len(verified_sources) >= required_sources:
                    print(f"    Cobertura confirmada en {required_sources} medios independientes")
                    break
            img_count = 1 + len(extras) if image else len(extras)
            print(f"    OK ({len(text)} chars, imgs: {img_count}, video: {'Si' if video else 'No'})")
        elif base_context:
            if not return_sources:
                context_parts.append(f"--- Fuente: {titulo} ---\n{base_context}")
            print(f"    Sin contenido completo, usando snippet")
        else:
            if not return_sources:
                context_parts.append(f"--- Fuente: {titulo} ---\n(Solo titulo disponible)")
            print(f"    Sin contenido suficiente, usando titulo")

        await asyncio.sleep(1)

    if not context_parts and not return_sources:
        titles_context = "\n".join([f"- {n['titulo']}" for n in noticias])
        context_parts.append(f"--- Titulares principales ---\n{titles_context}")
        print("  Usando titulares como contexto de respaldo")

    result = ("\n\n".join(context_parts), main_image_url, all_extra_images[:4], main_video_url)
    return (*result, verified_sources) if return_sources else result


if __name__ == "__main__":
    test_url = "https://news.google.com/rss/articles/CBMigAFBVV95cUxQY2lDbG83Xy1uUUNMb2tlQVNzdWgyRmQ3eTV6SUNBNXpVTENyZi1pZUdfc050ZG1JNmJzRWNNaU5KaUVUbF9mSVhIV1daeFV4ejFvNkI1TTVRcnFrWHcxNVZqLS01Q1RmdW83b24tMlNRVnhBeVZMcVBaZkxpbmp6eA?oc=5"
    real = decode_google_news_url(test_url)
    print(f"URL Real: {real}")
