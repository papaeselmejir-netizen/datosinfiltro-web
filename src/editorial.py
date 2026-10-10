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
    "son", "quienes", "cuales", "cual",
}

PLACE_TERMS = {
    "lima", "arequipa", "cusco", "junin", "trujillo", "piura", "callao", "ica",
    "puno", "tacna", "cajamarca", "chiclayo", "huancayo", "iquitos",
    "madrid", "miami", "bogota", "santiago", "buenos", "aires",
    "toluca", "guanajuato", "papantla", "merida", "londres", "tokio", "tokyo",
    "wheeling", "virginia", "washington", "detroit", "arizona", "paulo", "puerto",
    "portugal", "faro", "candaba", "pampanga", "colombia", "versalles", "versailles",
    "nang", "vietnam", "saigon", "manila", "arizona", "sao", "paulo",
}
EVENT_TERMS = {
    "peru", "canada", "brasil", "argentina", "mexico", "chile", "bolivia", "colombia",
    "uruguay", "paraguay", "ecuador", "venezuela", "espana", "francia",
    "alemania", "eeuu", "usa", "estados", "unidos",
}


def keywords(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    return {
        word for word in re.findall(r"[a-z0-9]{3,}", value.lower())
        if word not in STOPWORDS
    }


def place_terms(value):
    return keywords(value) & PLACE_TERMS


def event_terms(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    terms = set(re.findall(r"[a-z]{3,}", value.lower())) & EVENT_TERMS
    if terms & {"eeuu", "usa", "estados", "unidos"}:
        terms.difference_update({"eeuu", "usa", "estados", "unidos"})
        terms.add("estados_unidos")
    return terms


SPORT_MEDIA_TERMS = {
    "volleyball": {"volleyball", "volley", "voleibol", "voley"},
    "basketball": {"basketball", "baloncesto", "basquet", "basket", "hoop"},
    "tennis": {"tennis", "tenis", "racket", "raqueta"},
    "football": {"football", "footballer", "footballers", "soccer", "futbol"},
}

HOUSING_EVICTION_CUES = {
    "desahucio", "desahuciada", "desahuciado", "desahuciadas", "desahuciados",
    "desalojo", "desalojada", "desalojado", "desalojos", "inquilina", "inquilino",
    "eviction", "evicted", "tenant",
}


def sport_for_headline(value):
    terms = keywords(value)
    if terms & {"voley", "voleibol", "volibol", "volleyball", "zinger"}:
        return "volleyball"
    if terms & {"nba", "baloncesto", "basquet", "basket", "hezonja"}:
        return "basketball"
    if terms & {"tenis", "tenista", "wimbledon", "alcaraz"}:
        return "tennis"
    if terms & {"futbol", "futbolista", "menezes", "seleccion", "alianza", "universitario", "cristal"}:
        return "football"
    if terms & {"concacaf", "fifa", "mundial"}:
        return "football"
    return None


def query_terms(value, limit=6):
    """Keep the headline's term order when searching for corroboration or media."""
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    words = [word for word in re.findall(r"[a-z0-9]{3,}", value.lower()) if word not in STOPWORDS]
    return " ".join(dict.fromkeys(words).keys()) if limit is None else " ".join(list(dict.fromkeys(words))[:limit])


def corroboration_queries(headline):
    """Search both the beginning and the named details of a headline."""
    terms = query_terms((headline or "").rsplit(" - ", 1)[0], limit=None).split()
    if not terms:
        return []
    primary = " ".join(terms[:6])
    tail = terms[-4:] if len(terms) > 6 else terms[-2:]
    alternate = " ".join(dict.fromkeys(terms[:2] + tail))
    shorter = " ".join(terms[:3]) if len(terms) >= 5 else ""
    return [query for query in dict.fromkeys((primary, alternate, shorter)) if query]


def relevance(headline, candidate):
    primary = keywords(headline)
    secondary = keywords(candidate)
    if not primary or not secondary:
        return 0
    return len(primary & secondary) / min(len(primary), len(secondary))


def same_recent_event(first, second):
    """Conservatively suppress a second headline about the same recent event."""
    left, right = keywords(first), keywords(second)
    if place_terms(first) and place_terms(second) and not place_terms(first) & place_terms(second):
        return False
    if event_terms(first) and event_terms(second) and not event_terms(first) & event_terms(second):
        return False
    for aspect in (
        {"desvios", "viales", "cierres", "trafico"},
        {"fans", "army", "seguidores"},
        {"trump"},
    ):
        if bool(left & aspect) != bool(right & aspect):
            return False
    overlap = left & right
    return len(overlap) >= 4 and relevance(first, second) >= 0.35


def media_alignment_errors(article):
    """Reject stock descriptions about another subject, brand, place or asset."""
    title = " ".join(filter(None, (article.get("titulo_fuente"), article.get("titulo_articulo"))))
    title_terms = keywords(title)
    captions = [(item.get("descripcion", ""), False) for item in article.get("imagenes", [])[:2] if isinstance(item, dict)]
    if article.get("video_titulo"):
        captions.append((article["video_titulo"], article.get("video_source") == "youtube"))
    if not captions:
        return []

    themes = (
        ({"desvios", "viales", "cierres", "trafico", "transito"}, {"traffic", "road", "roads", "street", "streets", "cars", "vehicles", "bus", "buses", "transport", "desvios", "vial", "salida", "saldran", "transito"}, {"concert", "music", "stage"}),
        ({"concierto", "conciertos", "gira", "cantante"}, {"concert", "concerts", "music", "musician", "stage", "singer", "band", "performance", "crowd", "concierto", "conciertos", "musica", "gira"}, {"protest", "protests", "riot", "military", "soldier", "soldiers", "football", "soccer"}),
        (HOUSING_EVICTION_CUES, {"housing", "home", "house", "apartment", "residential", "building", "tenant", "eviction", "vivienda", "desahucio", "desalojo"}, {"ballot", "voting", "election", "campaign"}),
        ({"elecciones", "electoral", "votacion", "urna", "escrutinio"}, {"vote", "voting", "voter", "voters", "ballot", "election", "elections", "polling", "campaign", "elecciones", "electoral", "votos", "votacion", "urna", "balotaje"}, {"police", "festival", "landscape"}),
        ({"optogenetica", "neuronas"}, {"neuron", "neurons", "neuronas", "brain", "neuroscience", "research", "laboratory", "science", "nobel", "medicina"}, {"covid", "pill", "pills"}),
        ({"nobel"}, {"nobel", "medicine", "medicina", "medical", "science", "scientist", "research", "laboratory", "neuron", "brain"}, {"covid", "pill", "pills"}),
        ({"vivienda"}, {"housing", "home", "house", "apartment", "residential", "building", "vivienda"}, {"bank", "hotel"}),
        ({"asus", "rtx"}, {"asus", "laptop", "computer", "pc", "gaming", "notebook"}, {"sega", "amazon"}),
        ({"aston"}, {"aston", "martin", "car", "cars", "suv", "vehicle", "automotive", "gaming", "game"}, {"alonso", "perez", "racing", "formula"}),
        ({"usdc", "stablecoin", "stablecoins"}, {"usdc", "stablecoin", "digital", "payment", "payments", "wallet", "phone", "smartphone", "mobile"}, {"bitcoin", "btc"}),
        ({"bts"}, {"bts", "concert", "concerts", "music", "musician", "stage", "singer", "crowd", "concierto", "conciertos", "gira"}, {"protest", "protests", "riot", "riots"}),
        ({"xbox"}, {"xbox", "gaming", "gamer", "videogame", "videogames", "console", "game"}, set()),
        ({"atletico"}, SPORT_MEDIA_TERMS["football"] | {"atletico"}, set()),
    )
    required = forbidden = None
    for cues, allowed, excluded in themes:
        if title_terms & cues:
            required, forbidden = allowed, excluded
            break
    if {"inteligencia", "artificial"} <= title_terms and title_terms & {"salud", "hospital", "medicina", "medico", "medicos", "sanitario"}:
        required = {"health", "healthcare", "medical", "medicine", "hospital", "doctor", "doctors", "patient", "patients", "clinic"}
        forbidden = {"robot", "robots", "humanoid"}
    if title_terms & {"papa", "pontifice"} and title_terms & {"salud", "mental", "pastoral"}:
        required = {"pope", "papa", "papal", "vatican", "church", "catholic", "mental", "health", "salud", "pastoral", "healthcare", "prayer", "religious"}
        forbidden = {"food", "meal", "turkish"}
    if title_terms & {"iran", "iranian"} and title_terms & {"ataques", "militares", "guerra"}:
        required = {"iran", "iranian", "military", "middle", "east", "war", "trump"}
        forbidden = {"rally", "campaign", "ballot"}
    if required is None:
        return []
    errors = []
    for caption, event_video in captions:
        terms = keywords(caption)
        exact_video_match = event_video and len(terms & title_terms) >= 3
        if (not terms & required and not exact_video_match) or terms & forbidden:
            errors.append("El material multimedia no representa el asunto central de la noticia")
            break
    return errors


def claim_evidence_errors(article_text, source_text):
    """Catch numeric claims and wire-service attributions absent from source text."""
    number_pattern = re.compile(r"(?<![\w])\d+(?:[.,]\d+)*(?![\w])")

    def numbers(value):
        values = set()
        for raw in number_pattern.findall(value or ""):
            normalized = raw.replace(",", ".")
            try:
                values.add(str(float(normalized)))
            except ValueError:
                continue
        return values

    unsupported = sorted(numbers(article_text) - numbers(source_text))
    errors = [f"Cifras ausentes de las fuentes: {', '.join(unsupported[:8])}"] if unsupported else []
    for agency in ("Reuters", "EFE", "AFP", "Associated Press", "BBC", "CNN"):
        if re.search(r"\b" + re.escape(agency) + r"\b", article_text or "", re.IGNORECASE) and not re.search(
            r"\b" + re.escape(agency) + r"\b", source_text or "", re.IGNORECASE
        ):
            errors.append(f"Atribución a {agency} ausente de las fuentes")
    return errors


STORY_ASPECTS = (
    {"gadgets", "hardware", "dispositivo", "dispositivos", "sdk", "electronica"},
    {"generador", "imagenes", "imagen", "fotografias", "fotografia", "fotos"},
    {"cine", "cinema", "cinematografica", "audiovisual", "audiovisuales", "pelicula", "peliculas"},
    {"inteligencia", "artificial", "robotica"},
)


def matches_story_aspect(reference, candidate):
    """Keep similarly named products with different functions out of one story."""
    reference_terms, candidate_terms = keywords(reference), keywords(candidate)
    return all(not (reference_terms & aspect) or bool(candidate_terms & aspect) for aspect in STORY_ASPECTS)


def normalized_headline(value):
    """Ignore an outlet suffix when detecting syndicated copies of one dispatch."""
    return query_terms((value or "").rsplit(" - ", 1)[0], limit=None)


def near_duplicate_text(first, second):
    """Detect the same wire story republished with different page furniture."""
    def shingles(value):
        words = re.findall(r"[a-z0-9]+", (value or "").lower())[:3000]
        return {tuple(words[index:index + 5]) for index in range(max(0, len(words) - 4))}

    left, right = shingles(first), shingles(second)
    return bool(left and right and len(left & right) / min(len(left), len(right)) >= 0.65)


def rank_news(items):
    """Prefer fresh, specific headlines and reject obvious traffic traps."""
    now = datetime.now(timezone.utc)

    def score(item):
        title = item.get("titulo", "")
        lowered = title.lower()
        if any(phrase in lowered for phrase in (
            "en vivo gratis", "ver gratis", "horóscopo", "horoscopo",
            "dónde ver", "donde ver", "cómo ver", "como ver", "canal tv",
            "qué canal", "que canal", "horarios y canales",
            "últimas noticias del perú y el mundo", "ultimas noticias del peru y el mundo",
            "resultado final", "resultados en vivo", "latest updates", "estadísticas previas",
            "primeros recuentos", "primeros resultados", "resultados preliminares", "boca de urna", "flash electoral",
        )):
            return -100
        value = min(len(keywords(title)), 12) / 12
        value += min(len(item.get("snippet", "")), 300) / 300
        if item.get("fuente") and item["fuente"] != "Desconocida":
            value += 0.5
        raw_date = item.get("fecha", "")
        try:
            if isinstance(raw_date, str):
                try:
                    published = parsedate_to_datetime(raw_date)
                except ValueError:
                    published = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            else:
                published = raw_date
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


OFFICIAL_PRIMARY_SUFFIXES = {"gob.pe", "gov", "gov.uk", "europa.eu"}
OFFICIAL_PRIMARY_HOSTS = {
    "who.int", "un.org", "fifa.com", "inside.fifa.com", "olympics.com",
    "blog.google", "openai.com", "news.microsoft.com", "apple.com",
    "news.samsung.com", "store.epicgames.com", "blog.playstation.com",
}


def official_primary_source(url):
    """Conservative institutional domain check; a news outlet is not primary."""
    if not https_url(url):
        return False
    host = source_host(url)
    return host in OFFICIAL_PRIMARY_HOSTS or any(
        host == domain or host.endswith("." + domain) for domain in OFFICIAL_PRIMARY_SUFFIXES
    )


def social_source(url, outlet=""):
    hosts = {"facebook.com", "instagram.com", "tiktok.com", "x.com", "youtube.com", "reddit.com"}
    host = source_host(url)
    name = (outlet or "").strip().lower()
    return any(host == site or host.endswith("." + site) for site in hosts) or name in {
        "facebook", "facebook.com", "instagram", "instagram.com", "tiktok",
        "tiktok.com", "x", "x.com", "youtube", "youtube.com", "reddit", "reddit.com",
    }


def select_corrob_sources(primary, candidates, limit=2):
    """Select distinct outlets covering the same named subject."""
    selected = []
    ranked = sorted(
        rank_news(candidates),
        key=lambda candidate: relevance(primary.get("titulo"), candidate.get("titulo")),
        reverse=True,
    )
    for candidate in ranked:
        host = source_host(candidate.get("url"))
        # Google News redirect hosts are shared; the RSS publisher label distinguishes them.
        outlet = (candidate.get("fuente") or host).strip().lower()
        if social_source(candidate.get("url"), outlet):
            continue
        if not host or candidate.get("url") == primary.get("url"):
            continue
        if outlet == (primary.get("fuente") or source_host(primary.get("url"))).strip().lower():
            continue
        if normalized_headline(primary.get("titulo")) == normalized_headline(candidate.get("titulo")):
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


def contradictory_candidate_count(text):
    """Catch a clear total-versus-gender subtotal mismatch in election stories."""
    pattern = re.compile(
        r"de los\s+(\d+)\s+(?:postulantes|candidatos)[^.]{0,120}?"
        r"\b(\d+)\s+(?:son\s+)?(?:varones|hombres)\s+y\s+"
        r"(\d+)\s+(?:son\s+)?mujeres\b",
        re.IGNORECASE,
    )
    return any(int(total) != int(men) + int(women) for total, men, women in pattern.findall(text or ""))


def publication_errors(article):
    errors = []
    source_hosts = {source_host(item.get("url")) for item in article.get("fuentes", []) if isinstance(item, dict) and https_url(item.get("url"))}
    source_hosts.discard("")
    primary_exception = (
        len(article.get("fuentes", [])) == 1
        and article.get("verificacion_fuentes") == "comunicado_primario_oficial"
        and isinstance(article["fuentes"][0], dict)
        and official_primary_source(article["fuentes"][0].get("url"))
    )
    if len(source_hosts) < 2 and not primary_exception:
        errors.append("Se requieren dos fuentes verificadas")
    images = article.get("imagenes", [])
    if len(images) < 1 or any(
        not isinstance(item, dict)
        or not all(item.get(field) for field in ("url", "licencia", "licencia_url", "origen", "credito"))
        or not all(https_url(item.get(field)) for field in ("url", "licencia_url", "origen"))
        for item in images[:2]
    ):
        errors.append("Se requiere una imagen pertinente con licencia registrada")
    if not valid_video(article):
        errors.append("Se requiere un video relacionado con origen verificable")
    headline_places = place_terms(article.get("titulo_articulo"))
    if headline_places and article.get("video_source") != "pexels" and not headline_places <= place_terms(article.get("video_titulo")):
        errors.append("El video trata una ubicación distinta a la noticia")
    headline_events = event_terms(article.get("titulo_articulo"))
    if headline_events and article.get("video_source") != "pexels" and not headline_events <= event_terms(article.get("video_titulo")):
        errors.append("El video trata otro país o rival")
    if article.get("categoria") == "Deportes en Vivo" and article.get("video_source") != "pexels" and event_terms(article.get("video_titulo")) - headline_events:
        errors.append("El video muestra un rival distinto al de la noticia")
    if any(
        place_terms(item.get("descripcion")) and not place_terms(item.get("descripcion")) <= headline_places
        for item in images[:2] if isinstance(item, dict)
    ):
        errors.append("Una imagen muestra una ubicación distinta a la noticia")
    if article.get("media_review_version", 0) >= 1:
        errors.extend(media_alignment_errors(article))
    if article.get("categoria") == "Deportes en Vivo":
        sport = sport_for_headline(" ".join(filter(None, (article.get("titulo_fuente"), article.get("titulo_articulo")))))
        if sport:
            required = SPORT_MEDIA_TERMS[sport]
            if any(not (keywords(item.get("descripcion", "")) & required) for item in images[:2] if isinstance(item, dict)):
                errors.append("Una imagen corresponde a otro deporte")
            if article.get("video_source") == "pexels" and not (keywords(article.get("video_titulo")) & required):
                errors.append("El video de archivo corresponde a otro deporte")
    technology_terms = keywords(" ".join(filter(None, (article.get("titulo_fuente"), article.get("titulo_articulo")))))
    if article.get("categoria") == "Tecnologia, Gadgets e Inteligencia Artificial" and technology_terms & {
        "satelite", "satelites", "espacio", "orbita", "orbital", "cohete"
    }:
        required = {"satellite", "satellites", "space", "orbit", "orbital", "rocket", "spacecraft"}
        if any(not (keywords(item.get("descripcion", "")) & required) for item in images[:2] if isinstance(item, dict)):
            errors.append("Una imagen no representa el tema espacial")
        if article.get("video_source") == "pexels" and not (keywords(article.get("video_titulo")) & required):
            errors.append("El video de archivo no representa el tema espacial")
    elif article.get("categoria") == "Tecnologia, Gadgets e Inteligencia Artificial" and technology_terms & {
        "inteligencia", "artificial", "openai", "chatgpt", "gemini"
    }:
        required = {"artificial", "intelligence", "ai", "robot", "digital", "computer", "technology"}
        if any(not (keywords(item.get("descripcion", "")) & required) for item in images[:2] if isinstance(item, dict)):
            errors.append("Una imagen no representa el tema de inteligencia artificial")
        if article.get("video_source") == "pexels" and not (keywords(article.get("video_titulo")) & required):
            errors.append("El video de archivo no representa inteligencia artificial")
    headline_terms = keywords(" ".join(filter(None, (article.get("titulo_fuente"), article.get("titulo_articulo")))))
    if article.get("categoria") == "Gaming y Esports" and {"epic", "games"} <= headline_terms and headline_terms & {
        "regala", "gratis", "gratuitos"
    }:
        required = {"gaming", "gamer", "computer", "pc", "desktop", "videogame", "videogames"}
        unrelated = {"pokemon", "atari", "nintendo", "fortnite", "cartridge", "cartridges"}
        if any(
            not (keywords(item.get("descripcion", "")) & required)
            or keywords(item.get("descripcion", "")) & unrelated
            for item in images[:2] if isinstance(item, dict)
        ):
            errors.append("Una imagen muestra un videojuego ajeno al regalo de Epic")
        if article.get("video_source") == "pexels" and (
            not (keywords(article.get("video_titulo")) & required)
            or keywords(article.get("video_titulo")) & unrelated
        ):
            errors.append("El video de archivo no representa juegos de PC")
    if article.get("categoria") == "Finanzas, Negocios y Criptomonedas" and headline_terms & {
        "empresa", "empresas", "empresarial", "negocios"
    } and headline_terms & {"congreso", "foro", "encuentro", "reunion"}:
        required = {"business", "conference", "meeting", "executive", "corporate", "company"}
        if any(not (keywords(item.get("descripcion", "")) & required) for item in images[:2] if isinstance(item, dict)):
            errors.append("Una imagen no representa el encuentro empresarial")
        if article.get("video_source") == "pexels" and not (keywords(article.get("video_titulo")) & required):
            errors.append("El video de archivo no representa el encuentro empresarial")
    if contradictory_candidate_count(article.get("articulo_web")):
        errors.append("Los subtotales de candidatos no coinciden con el total")
    word_count = len((article.get("articulo_web") or "").split())
    if word_count < (100 if primary_exception else 250):
        errors.append("El artículo es demasiado breve")
    if primary_exception and word_count > 220:
        errors.append("La nota de fuente única supera la extensión permitida")
    if (article.get("titulo_articulo") or "").lower().startswith("error"):
        errors.append("Título de error")
    return errors
