"""Build the public newspaper from reviewed, publishable articles."""

import glob
import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import bleach
import markdown
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader, select_autoescape

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.editorial import publication_errors  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))
OUTPUT_DIR = os.getenv("OUTPUT_DIR", os.path.join(BASE_DIR, "published"))
PUBLIC_DIR = os.getenv("PUBLIC_DIR", os.path.join(BASE_DIR, "website", "public"))
TEMPLATES_DIR = os.path.join(BASE_DIR, "website", "templates")
SITE_URL = os.getenv("SITE_URL", "").rstrip("/")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "")
ADSENSE_PUBLISHER_ID = os.getenv("ADSENSE_PUBLISHER_ID", "")

env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=select_autoescape(["html", "xml"]))
SAFE_TAGS = ["p", "h2", "h3", "ul", "ol", "li", "strong", "em", "blockquote", "a", "br", "code"]
NAV_LABELS = {
    "Noticias de Ultima Hora y Politica": "Actualidad",
    "Deportes en Vivo": "Deportes",
    "Finanzas, Negocios y Criptomonedas": "Economía",
    "Tecnologia, Gadgets e Inteligencia Artificial": "Tecnología",
    "Salud, Bienestar y Estilo de Vida": "Salud",
    "Entretenimiento, Farandula y Cine": "Farándula",
    "Gaming y Esports": "Gaming",
    "Tendencias": "Tendencias",
}


def slugify(value):
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value[:65] or "noticia"


def render_markdown(value):
    raw = markdown.markdown(value or "", extensions=["extra"])
    return bleach.clean(raw, tags=SAFE_TAGS, attributes={"a": ["href", "title"]}, protocols=["http", "https"], strip=True)


def write(name, content):
    destination = os.path.join(PUBLIC_DIR, name)
    with open(destination, "w", encoding="utf-8") as file:
        file.write("\n".join(line.rstrip() for line in content.split("\n")))


def load_articles():
    articles = []
    seen = set()
    for path in glob.glob(os.path.join(OUTPUT_DIR, "**", "*.json"), recursive=True):
        try:
            with open(path, encoding="utf-8") as file:
                article = json.load(file)
            if article.get("schema_version") != 2 or publication_errors(article):
                continue  # Legacy content needs a separate rights and sourcing review.
            published = article.get("fecha_publicacion", "")
            datetime.fromisoformat(published.replace("Z", "+00:00"))
            source = article["fuentes"][0]["url"]
            if source in seen:
                continue
            seen.add(source)
            digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:8]
            article["slug"] = f"{slugify(article['titulo_articulo'])}-{digest}"
            local_time = datetime.fromisoformat(published.replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=-5)))
            article["fecha"] = local_time.strftime("%Y-%m-%d")
            article["fecha_local"] = local_time.strftime("%d/%m/%Y %H:%M")
            article["fecha_publicacion"] = published
            article["section_short"] = NAV_LABELS.get(article.get("categoria"), article.get("categoria", "Noticias"))
            article["html_content"] = render_markdown(article.get("articulo_web", ""))
            article["resumen"] = article.get("resumen") or re.sub(r"<[^>]+>", "", article["html_content"])[:155]
            article["canonical"] = f"{SITE_URL}/{article['slug']}.html" if SITE_URL else ""
            schema = {
                "@context": "https://schema.org", "@type": "NewsArticle",
                "headline": article["titulo_articulo"],
                "description": article["resumen"],
                "image": [image["url"] for image in article["imagenes"]],
                "datePublished": published,
                "dateModified": article.get("fecha_modificacion", published),
                "author": {"@type": "Organization", "name": article.get("autor", "Equipo editorial DatoSinFiltro")},
                "publisher": {"@type": "Organization", "name": "DatoSinFiltro"},
            }
            if article["canonical"]:
                schema["mainEntityOfPage"] = article["canonical"]
            article["news_schema"] = json.dumps(schema, ensure_ascii=False).replace("</", "<\\/")
            articles.append(article)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"Artículo omitido {path}: {exc}")
    # Several articles from one run share a timestamp; keep output stable across OSes.
    return sorted(articles, key=lambda article: (article["fecha_publicacion"], article["slug"]), reverse=True)


def write_sitemap(articles, category_pages):
    if not SITE_URL or urlparse(SITE_URL).scheme != "https":
        write("robots.txt", "User-agent: *\nDisallow: /\n")
        return
    write("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n")
    root = ET.Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    for name, modified in [("index.html", ""), ("quienes-somos.html", ""), ("politica-editorial.html", ""), ("privacidad.html", ""), *[(page, "") for page in category_pages], *[(f"{item['slug']}.html", item["fecha_publicacion"]) for item in articles]]:
        item = ET.SubElement(root, "url")
        ET.SubElement(item, "loc").text = f"{SITE_URL}/{name}"
        if modified:
            ET.SubElement(item, "lastmod").text = modified
    write("sitemap.xml", ET.tostring(root, encoding="unicode", xml_declaration=True))

    news_root = ET.Element("urlset", {
        "xmlns": "http://www.sitemaps.org/schemas/sitemap/0.9",
        "xmlns:news": "http://www.google.com/schemas/sitemap-news/0.9",
    })
    cutoff = datetime.now(timezone.utc) - timedelta(days=2)
    for article in articles:
        published = datetime.fromisoformat(article["fecha_publicacion"].replace("Z", "+00:00"))
        if published < cutoff:
            continue
        node = ET.SubElement(news_root, "url")
        ET.SubElement(node, "loc").text = article["canonical"]
        news = ET.SubElement(node, "news:news")
        publication = ET.SubElement(news, "news:publication")
        ET.SubElement(publication, "news:name").text = "DatoSinFiltro"
        ET.SubElement(publication, "news:language").text = "es"
        ET.SubElement(news, "news:publication_date").text = article["fecha_publicacion"]
        ET.SubElement(news, "news:title").text = article["titulo_articulo"]
    write("news-sitemap.xml", ET.tostring(news_root, encoding="unicode", xml_declaration=True))


def build_site():
    os.makedirs(PUBLIC_DIR, exist_ok=True)
    articles = load_articles()
    with open(os.path.join(BASE_DIR, "categories.json"), encoding="utf-8") as file:
        names = json.load(file)
    categories = [{"name": name, "short": NAV_LABELS.get(name, name), "slug": slugify(name), "articles": []} for name in names]
    by_name = {item["name"]: item for item in categories}
    for article in articles:
        if article.get("categoria") in by_name:
            by_name[article["categoria"]]["articles"].append(article)

    common = {"base_path": "./", "categories": categories, "site_url": SITE_URL, "contact_email": CONTACT_EMAIL, "current_year": datetime.now(timezone.utc).year}
    generated = ["index.html", "search.json", "robots.txt"]
    write("index.html", env.get_template("index.html").render(articles=articles, **common))
    for article in articles:
        related = [item for item in articles if item["slug"] != article["slug"] and item["categoria"] == article["categoria"]][:4]
        if len(related) < 4:
            related.extend(item for item in articles if item["slug"] != article["slug"] and item not in related)
        name = f"{article['slug']}.html"
        write(name, env.get_template("article.html").render(article=article, recent_articles=related[:4], **common))
        generated.append(name)
    category_pages = []
    for category in categories:
        name = f"categoria-{category['slug']}.html"
        write(name, env.get_template("category.html").render(categoria=category["name"], category_short=category["short"], category_slug=category["slug"], articles=category["articles"], **common))
        generated.append(name)
        category_pages.append(name)
    search_index = [{
        "title": item["titulo_articulo"], "slug": item["slug"], "category": item["categoria"],
        "date": item["fecha"], "image": item["imagen_url"],
    } for item in articles]
    write("search.json", json.dumps(search_index, ensure_ascii=False))
    for page, template in (("quienes-somos.html", "about.html"), ("politica-editorial.html", "editorial.html"), ("privacidad.html", "privacy.html")):
        write(page, env.get_template(template).render(**common))
        generated.append(page)
    write_sitemap(articles, category_pages)
    if SITE_URL:
        generated.extend(["sitemap.xml", "news-sitemap.xml"])
    if ADSENSE_PUBLISHER_ID.startswith("pub-"):
        write("ads.txt", f"google.com, {ADSENSE_PUBLISHER_ID}, DIRECT, f08c47fec0942fa0\n")
        generated.append("ads.txt")
    write("generated-files.json", json.dumps(generated, ensure_ascii=False, indent=2))
    print(f"Sitio generado con {len(articles)} noticias verificadas y {len(categories)} categorías")


if __name__ == "__main__":
    build_site()
