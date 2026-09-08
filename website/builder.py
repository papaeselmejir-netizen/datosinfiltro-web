import os
import json
import glob
import sys
from jinja2 import Environment, FileSystemLoader
import markdown
import shutil

# Forzar UTF-8 en la consola de Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Rutas
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
WEBSITE_DIR = os.path.join(BASE_DIR, "website")
TEMPLATES_DIR = os.path.join(WEBSITE_DIR, "templates")
PUBLIC_DIR = os.path.join(WEBSITE_DIR, "public")

# Inicializar Jinja2
env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
index_template = env.get_template("index.html")
article_template = env.get_template("article.html")
category_template = env.get_template("category.html")

def build_site():
    print("🚀 Construyendo sitio web estático...")
    
    # Asegurar que public/css existe
    os.makedirs(os.path.join(PUBLIC_DIR, "css"), exist_ok=True)
    
    # Copiar CSS a public
    if os.path.exists(os.path.join(PUBLIC_DIR, "css", "style.css")):
        pass # ya existe y estamos modificando directo en public, pero lo ideal es copiar de assets.
        # Por ahora lo escribimos directo en public/css/style.css, asi que no lo sobreescribimos.

    # Buscar todos los JSON en output (recursivo)
    json_files = glob.glob(os.path.join(OUTPUT_DIR, "**", "*.json"), recursive=True)
    
    articles = []
    seen_images = set()
    
    for file_path in json_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            img_url = data.get("imagen_url")
            
            # Saltar noticias sin imagen
            if not img_url:
                print(f"Saltando noticia sin imagen: {file_path}")
                continue
                
            # Saltar si la imagen ya fue usada en otra noticia (evitar imagenes repetidas)
            if img_url in seen_images:
                print(f"Saltando imagen repetida: {file_path}")
                continue
                
            seen_images.add(img_url)
                
            # Extraer fecha del nombre del archivo o ruta (ej. 2026-09-06)
            parts = file_path.split(os.sep)
            fecha = parts[-3] if len(parts) >= 3 and "-" in parts[-3] else "Reciente"
            
            # Obtener tiempo del nombre de archivo (ej. 230944)
            filename = os.path.basename(file_path)
            time_prefix = filename.split('_')[0] if '_' in filename else "000000"
            sort_key = f"{fecha}-{time_prefix}"
            
            # Generar un slug (URL amigable) basado en el titulo
            titulo = data.get("titulo_articulo", "Noticia")
            slug = titulo.lower().replace(" ", "-").replace(":", "").replace(",", "")
            slug = "".join(c for c in slug if c.isalnum() or c == "-")
            data["slug"] = slug[:60]
            data["fecha"] = fecha
            data["sort_key"] = sort_key
            
            # Convertir el markdown del articulo a HTML
            md_text = data.get("articulo_web", "")
            raw_html = markdown.markdown(md_text)
            
            # Las imágenes ya fueron inyectadas en el HTML por el pipeline principal
            # (con _insert_images_in_article en main.py / update_all_news.py)
            data["html_content"] = raw_html
            
            articles.append(data)
            
        except Exception as e:
            print(f"Error procesando {file_path}: {e}")

    # Ordenar por fecha de más reciente a más antiguo usando sort_key
    articles.sort(key=lambda x: x.get("sort_key", ""), reverse=True)

    # 1. Generar index.html
    index_html = index_template.render(articles=articles, base_path="./")
    with open(os.path.join(PUBLIC_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)
    print(f"✅ index.html generado con {len(articles)} noticias.")

    # 2. Generar cada articulo (pagina individual)
    for article in articles:
        recent_articles = [a for a in articles if a['slug'] != article['slug']][:4]
        article_html = article_template.render(
            article=article, 
            recent_articles=recent_articles,
            base_path="./"
        )
        file_out = os.path.join(PUBLIC_DIR, f"{article['slug']}.html")
        with open(file_out, "w", encoding="utf-8") as f:
            f.write(article_html)
            
    print(f"✅ {len(articles)} páginas de artículos generadas.")
    
    # 3. Agrupar por categoria y generar paginas de categoria
    grouped_articles = {}
    for article in articles:
        cat = article.get("categoria", "General")
        if cat not in grouped_articles:
            grouped_articles[cat] = []
        grouped_articles[cat].append(article)
        
    for cat, group in grouped_articles.items():
        cat_slug = cat.lower().replace(" ", "-").replace(":", "").replace(",", "")
        cat_slug = "".join(c for c in cat_slug if c.isalnum() or c == "-")
        cat_html = category_template.render(categoria=cat, articles=group, base_path="./")
        with open(os.path.join(PUBLIC_DIR, f"categoria-{cat_slug}.html"), "w", encoding="utf-8") as f:
            f.write(cat_html)
            
    print(f"✅ {len(grouped_articles)} páginas de categorías generadas.")

    # 4. Generar search.json para el buscador
    search_index = []
    for article in articles:
        search_index.append({
            "title": article.get("titulo_articulo", ""),
            "slug": article.get("slug", ""),
            "category": article.get("categoria", ""),
            "date": article.get("fecha", ""),
            "image": article.get("imagen_url", "")
        })
    with open(os.path.join(PUBLIC_DIR, "search.json"), "w", encoding="utf-8") as f:
        json.dump(search_index, f, ensure_ascii=False)
        
    print(f"✅ search.json generado.")

    print(f"🎉 Construcción finalizada. Abre {os.path.join(PUBLIC_DIR, 'index.html')} en tu navegador.")

if __name__ == "__main__":
    build_site()
