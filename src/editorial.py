"""Small, deterministic publication gates; AI output is never its own evidence."""

import re
import unicodedata
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

STOPWORDS = {
    "ante", "como", "con", "del", "desde", "donde", "entre", "esta",
    "este", "para", "pero", "por", "que", "segun", "sobre", "tras",
    "una", "uno", "unos", "unas", "las", "los", "noticias", "hoy",
    "vivo", "ultima", "hora", "nuevo", "nueva", "peru", "mundo",
}


def keywords(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    return {
        word for word in re.findall(r"[a-z0-9]{3,}", value.lower())
        if word not in STOPWORDS
    }


def query_terms(value, limit=6):
    """Keep the headline's term order when searching for corroboration or media."""
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    words = [word for word in re.findall(r"[a-z0-9]{3,}", value.lower()) if word not in STOPWORDS]
    return " ".join(dict.fromkeys(words).keys()) if limit is None else " ".join(list(dict.fromkeys(words))[:limit])


def relevance(headline, candidate):
    primary = keywords(headline)
    secondary = keywords(candidate)
    if not primary or not secondary:
        return 0
    return len(primary & secondary) / min(len(primary), len(secondary))


STORY_ASPECTS = (
    {"gadgets", "hardware", "dispositivo", "dispositivos", "sdk", "electronica"},
    {"generador", "imagenes", "imagen", "fotografias", "fotografia", "fotos"},
)


def matches_story_aspect(reference, candidate):
    """Keep similarly named products with different functions out of one story."""
    reference_terms, candidate_terms = keywords(reference), keywords(candidate)
    return all(not (reference_terms & aspect) or bool(candidate_terms & aspect) for aspect in STORY_ASPECTS)


def rank_news(items):
    """Prefer fresh, specific headlines and reject obvious traffic traps."""
    now = datetime.now(timezone.utc)

    def score(item):
        title = item.get("titulo", "")
        lowered = title.lower()
        if any(phrase in lowered for phrase in ("en vivo gratis", "ver gratis", "horóscopo", "horoscopo")):
            return -100
        value = min(len(keywords(title)), 12) / 12
        value += min(len(item.get("snippet", "")), 300) / 300
        if item.get("fuente") and item["fuente"] != "Desconocida":
            value += 0.5
        raw_date = item.get("fecha", "")
        try:
            published = parsedate_to_datetime(raw_date) if isinstance(raw_date, str) else raw_date
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            age_hours = (now - published).total_seconds() / 3600
            if age_hours > 96:
                return -100
            value += 2 if age_hours <= 24 else 1 if age_hours <= 72 else -2
        except (TypeError, ValueError, OverflowError, AttributeError):
            pass
        return value

    return [item for item in sorted(items, key=score, reverse=True) if score(item) > -50]


def source_host(url):
    host = urlparse(url or "").hostname or ""
    return host.removeprefix("www.").lower()


def select_corrob_sources(primary, candidates, limit=2):
    """Select distinct outlets covering the same named subject."""
    selected = []
    ranked = sorted(
        candidates,
        key=lambda candidate: relevance(primary.get("titulo"), candidate.get("titulo")),
        reverse=True,
    )
    for candidate in ranked:
        host = source_host(candidate.get("url"))
        # Google News redirect hosts are shared; the RSS publisher label distinguishes them.
        outlet = (candidate.get("fuente") or host).strip().lower()
        if not host or candidate.get("url") == primary.get("url"):
            continue
        if outlet == (primary.get("fuente") or source_host(primary.get("url"))).strip().lower():
            continue
        if any(outlet == (item.get("fuente") or source_host(item.get("url"))).strip().lower() for item in selected):
            continue
        overlap = keywords(primary.get("titulo")) & keywords(candidate.get("titulo"))
        if relevance(primary.get("titulo"), candidate.get("titulo")) < 0.20 or len(overlap) < 2:
            continue
        if not matches_story_aspect(primary.get("titulo"), candidate.get("titulo")):
            continue
        selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected


def valid_embed(url):
    parsed = urlparse(url or "")
    return parsed.scheme == "https" and parsed.hostname in {
        "www.youtube.com", "youtube.com", "www.youtube-nocookie.com"
    } and bool(re.fullmatch(r"/embed/[A-Za-z0-9_-]{11}", parsed.path))


def valid_video(article):
    if not article.get("video_titulo"):
        return False
    if article.get("video_source") == "pexels":
        parsed = urlparse(article.get("video_url") or "")
        return (
            parsed.scheme == "https" and parsed.hostname == "videos.pexels.com"
            and all(article.get(field) for field in ("video_origen", "video_licencia", "video_licencia_url", "video_canal"))
            and https_url(article.get("video_origen")) and https_url(article.get("video_licencia_url"))
        )
    return valid_embed(article.get("video_url"))


def https_url(value):
    parsed = urlparse(value or "")
    return parsed.scheme == "https" and bool(parsed.hostname)


def publication_errors(article):
    errors = []
    source_hosts = {source_host(item.get("url")) for item in article.get("fuentes", []) if isinstance(item, dict) and https_url(item.get("url"))}
    source_hosts.discard("")
    if len(source_hosts) < 2:
        errors.append("Se requieren dos fuentes verificadas")
    images = article.get("imagenes", [])
    if len(images) < 2 or any(
        not isinstance(item, dict)
        or not all(item.get(field) for field in ("url", "licencia", "licencia_url", "origen", "credito"))
        or not all(https_url(item.get(field)) for field in ("url", "licencia_url", "origen"))
        for item in images[:2]
    ):
        errors.append("Se requieren dos imágenes con licencia registrada")
    if not valid_video(article):
        errors.append("Se requiere un video relacionado con origen verificable")
    if len((article.get("articulo_web") or "").split()) < 250:
        errors.append("El artículo es demasiado breve")
    if (article.get("titulo_articulo") or "").lower().startswith("error"):
        errors.append("Título de error")
    return errors
