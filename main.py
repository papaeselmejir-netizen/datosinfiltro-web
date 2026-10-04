import asyncio
import os
import json
import sys
import argparse
import glob
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Forzar UTF-8 en la consola de Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.extractor import extract_news_multi_source, extract_custom_topic_google_rss, CATEGORIAS
from src.crawler import investigate_news
from src.writer import generate_multi_channel_content, verify_article_against_sources
from src.multimedia import search_licensed_images, search_relevant_video
from src.editorial import query_terms, select_corrob_sources, source_host, publication_errors, rank_news, matches_story_aspect

load_dotenv()

# Categorias a procesar en esta ejecucion.
# Todas las 8 categorias activas por defecto.
CATEGORIAS_ACTIVAS = list(CATEGORIAS.keys())

# Directorio donde se guardan los articulos generados
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "drafts")
HISTORY_FILE = os.path.join(os.path.dirname(__file__), "history.json")

def load_history():
    history = set()
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history.update(json.load(f))
        except Exception:
            pass
    for folder in (OUTPUT_DIR, os.path.join(os.path.dirname(__file__), "published"), os.path.join(os.path.dirname(__file__), "output")):
        for path in glob.glob(os.path.join(folder, "**", "*.json"), recursive=True):
            try:
                with open(path, encoding="utf-8") as file:
                    article = json.load(file)
                if article.get("fuente_url"):
                    history.add(article["fuente_url"])
                if article.get("titulo_fuente"):
                    history.add(article["titulo_fuente"].lower())
            except (OSError, ValueError):
                continue
    return history

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(list(history), f, ensure_ascii=False, indent=2)


async def process_single_news(noticia, categoria, distributor=None):
    """
    Procesa UNA sola noticia: investiga, redacta y distribuye.
    Evita contaminacion de contexto al procesar cada noticia de forma independiente.
    Solo crea un borrador cuando hay fuentes y multimedia verificables.
    """
    titulo = noticia["titulo"]
    print(f"\n    --- Procesando: {titulo[:70]}... ---")

    # FASE 2: Investigacion (leer el contenido real de la URL)
    print(f"    [Investigando] Leyendo contenido de la fuente...")
    topic = query_terms(titulo)
    candidates = await asyncio.to_thread(
        extract_custom_topic_google_rss, topic, geo="PE" if noticia.get("region") == "Perú" else "US", max_items=12
    )
    corroborating = select_corrob_sources(noticia, candidates, limit=3)
    contexto, _, _, _, sources = await investigate_news(
        [noticia, *corroborating], return_sources=True
    )
    if len({source_host(source["url"]) for source in sources}) < 2:
        print("    Faltan dos medios independientes con texto suficiente. Saltando.")
        return None

    print("    [Multimedia] Buscando imágenes con licencia y un video relacionado...")
    images, video = await asyncio.gather(
        asyncio.to_thread(search_licensed_images, titulo, 2),
        asyncio.to_thread(search_relevant_video, titulo),
    )
    if len(images) < 2 or not video:
        print("    Multimedia insuficiente o no verificable. Saltando.")
        return None

    # FASE 3: Redaccion con IA
    print(f"    [Redactando] Generando contenido multi-canal...")
    region = noticia.get("region", "General")
    content = generate_multi_channel_content(titulo, contexto, categoria, region=region)

    if not content:
        print(f"    Error en la generacion de contenido. Saltando.")
        return None
    if not all(matches_story_aspect(titulo, content.get(field, "")) for field in ("titulo_articulo", "resumen")):
        print("    El texto redactado cambió el producto o la función central. Saltando.")
        return None
    if not await asyncio.to_thread(verify_article_against_sources, content.get("articulo_web", ""), contexto):
        print("    La revisión automática detectó afirmaciones no sustentadas. Saltando.")
        return None

    # Check if the LLM generated an error message instead of an article
    if content.get("titulo_articulo", "").lower().startswith("error"):
        print(f"    Error: El LLM devolvió un contenido ilegible/error. Saltando.")
        return None

    # Agregar region, imagen principal, imagenes extra y video al contenido generado
    content["region"] = noticia.get("region", "General")
    content["schema_version"] = 2
    content["titulo_fuente"] = titulo
    content["autor"] = "Equipo editorial DatoSinFiltro"
    content["fecha_creacion"] = datetime.now(ZoneInfo("America/Lima")).isoformat(timespec="seconds")
    content["fuentes"] = sources
    content["imagenes"] = images
    content["imagen_url"] = images[0]["url"]
    content["extra_images"] = [item["url"] for item in images[1:]]
    content["video_url"] = video["url"]
    content["video_titulo"] = video["titulo"]
    content["video_canal"] = video["canal"]
    content["video_source"] = video["source"]
    content["video_tipo"] = video["tipo"]
    content["video_origen"] = video.get("origen", "")
    content["video_licencia"] = video.get("licencia", "")
    content["video_licencia_url"] = video.get("licencia_url", "")
    content["video_poster"] = video.get("poster", "")
    content["fuente_url"] = noticia.get("url", "")
    errors = publication_errors(content)
    if errors:
        print(f"    Borrador rechazado: {', '.join(errors)}")
        return None
    
    print(f"    Contenido generado exitosamente.")

    # Guardar resultado como JSON organizando por fecha y categoria
    date_folder = datetime.now().strftime("%Y-%m-%d")
    safe_cat = categoria.replace(" ", "_").replace(",", "")
    category_dir = os.path.join(OUTPUT_DIR, date_folder, safe_cat)
    os.makedirs(category_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%H%M%S")
    safe_title = titulo[:40].replace(" ", "_").replace(",", "").replace(":", "")
    filename = f"{timestamp}_{safe_title}_{uuid.uuid4().hex[:8]}.json"
    
    # Limpiar caracteres no validos para nombres de archivo
    filename = "".join(c for c in filename if c.isalnum() or c in "._-")
    filepath = os.path.join(category_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(content, f, indent=4, ensure_ascii=False)
    print(f"    Guardado en: {filepath}")

    return content


def _insert_images_in_article(html_content, images, titulo):
    """
    Inserta imágenes distribuidas en el cuerpo del artículo HTML.
    Coloca cada imagen después de un subtítulo H2 o entre párrafos para 
    mantener la estructura visual tipo portal de noticias profesional.
    """
    import re

    # Buscar posiciones de subtítulos H2 para insertar imágenes después de ellos
    h2_pattern = re.compile(r'(</h2>)', re.IGNORECASE)
    h2_positions = list(h2_pattern.finditer(html_content))

    if len(h2_positions) >= len(images):
        # Distribuir imágenes después de los primeros H2
        offset = 0
        for i, img_url in enumerate(images):
            match = h2_positions[i]
            insert_pos = match.end() + offset
            alt_text = f"Imagen relacionada: {titulo[:60]}"
            img_html = f'\n<figure class="article-inline-img"><img src="{img_url}" alt="{alt_text}" loading="lazy"><figcaption>{alt_text}</figcaption></figure>\n'
            html_content = html_content[:insert_pos] + img_html + html_content[insert_pos:]
            offset += len(img_html)
    else:
        # Fallback: buscar párrafos y distribuir entre ellos
        p_pattern = re.compile(r'(</p>)', re.IGNORECASE)
        p_positions = list(p_pattern.finditer(html_content))

        if p_positions:
            # Calcular posiciones equidistantes
            step = max(1, len(p_positions) // (len(images) + 1))
            offset = 0
            for i, img_url in enumerate(images):
                p_idx = min((i + 1) * step, len(p_positions) - 1)
                match = p_positions[p_idx]
                insert_pos = match.end() + offset
                alt_text = f"Imagen relacionada: {titulo[:60]}"
                img_html = f'\n<figure class="article-inline-img"><img src="{img_url}" alt="{alt_text}" loading="lazy"><figcaption>{alt_text}</figcaption></figure>\n'
                html_content = html_content[:insert_pos] + img_html + html_content[insert_pos:]
                offset += len(img_html)

    return html_content


async def process_category(categoria, distributor=None, max_noticias=2, max_drafts=None):
    """
    Procesa una sola categoria: extrae noticias y procesa cada una individualmente.
    """
    print(f"\n{'='*60}")
    print(f"  CATEGORIA: {categoria}")
    print(f"{'='*60}")

    # FASE 1: Extraccion de noticias (multi-source con fallback)
    print(f"\n  [Fase 1] Extrayendo noticias...")
    
    # 1.1 Obtener noticias MUNDIALES (geo=US, lang=es)
    print(f"  -> Buscando noticias MUNDIALES...")
    noticias_mundial = extract_news_multi_source(categoria, max_items=max_noticias, lang="es", geo="US")
    for n in noticias_mundial:
        n["region"] = "Mundial"
        
    # 1.2 Obtener noticias LOCALES (geo=PE, lang=es)
    print(f"  -> Buscando noticias EXCLUSIVAS PERU...")
    noticias_peru = extract_news_multi_source(categoria, max_items=max_noticias, lang="es", geo="PE")
    for n in noticias_peru:
        n["region"] = "Perú"
        
    noticias = rank_news(noticias_mundial + noticias_peru)

    if not noticias:
        print(f"  No se encontraron noticias para '{categoria}'. Saltando.")
        return []

    # Cargar historial para deduplicar
    history = load_history()
    noticias_filtradas = []
    
    for n in noticias:
        url_key = n.get("url", "")
        titulo_key = n.get("titulo", "").lower()
        if (url_key and url_key in history) or (titulo_key and titulo_key in history):
            # Ya procesada, la ignoramos
            continue
        noticias_filtradas.append(n)

    if not noticias_filtradas:
        print(f"  Todas las noticias encontradas para '{categoria}' ya fueron procesadas antes. Saltando.")
        return []

    for i, n in enumerate(noticias_filtradas, 1):
        print(f"    {i}. [{n.get('region')}] [{n.get('origen', '?')}] {n['titulo'][:80]}")

    # Procesar cada noticia de forma INDIVIDUAL (sin contaminacion de contexto)
    resultados = []
    for noticia in noticias_filtradas:
        if max_drafts is not None and len(resultados) >= max_drafts:
            break
        try:
            result = await process_single_news(noticia, categoria, distributor=None) # Ya no enviamos 1 por 1
            if result:
                resultados.append(result)
                # Los borradores y publicados se consultan en load_history.
                history.add(noticia.get("url", ""))
                history.add(noticia["titulo"].lower())
        except Exception as e:
            print(f"    ERROR procesando noticia: {e}")
            continue

    # FASE 4: Aprobacion Batch por Telegram
    if distributor and resultados:
        print(f"\n  [Fase 4] Solicitando aprobacion batch por Telegram para {len(resultados)} articulos...")
        
        # Iniciar listener batch
        approved_contents = await distributor.run_batch_approval_flow(resultados, categoria)
        
        print(f"  -> {len(approved_contents)} articulos aprobados de {len(resultados)}.")
        for content in approved_contents:
            distributor.publish_to_wordpress(content)
            distributor.publish_to_x(content)
            distributor.publish_to_facebook(content)
        
        # Solo retornamos los que fueron finalmente aprobados para el resumen
        return approved_contents

    return resultados


async def main(topic=None):
    print("=" * 60)
    if topic:
        print(f"  PIPELINE AUTONOMO: BÚSQUEDA MANUAL DE TEMA")
        print(f"  Tema: {topic}")
    else:
        print("  PIPELINE AUTONOMO DE CONTENIDO MULTI-CATEGORIA")
    print(f"  Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if not topic:
        print(f"  Categorias activas: {len(CATEGORIAS_ACTIVAS)}")
    print(f"  Idioma: {os.getenv('NEWS_LANG', 'es')} | Pais: {os.getenv('NEWS_COUNTRY', 'PE')}")
    print("=" * 60)

    # Los borradores se revisan y publican desde el CMS protegido.
    distributor = None

    if topic:
        print(f"\n  [Fase 1] Buscando noticias sobre: {topic}")
        noticias = rank_news(extract_custom_topic_google_rss(topic, geo="PE", max_items=8))
        for noticia in noticias:
            noticia["region"] = "Perú"
        if not noticias:
            print("  No se encontraron noticias para el tema especificado.")
            return
            
        for i, n in enumerate(noticias, 1):
            print(f"    {i}. [{n.get('origen')}] {n['titulo'][:80]}")
            
        print("\n  [Fase 2 y 3] Procesando...")
        for noticia in noticias[:5]:
            try:
                if await process_single_news(noticia, "Tendencias", distributor=None):
                    break
            except Exception as e:
                print(f"  ERROR procesando tema personalizado: {e}")
        return

    todos_los_resultados = {}
    max_per_run = max(1, int(os.getenv("MAX_DRAFTS_PER_RUN", "8")))
    max_per_region = max(1, int(os.getenv("MAX_NEWS_PER_REGION", "2")))

    for categoria in CATEGORIAS_ACTIVAS:
        remaining = max_per_run - sum(len(group) for group in todos_los_resultados.values())
        if remaining <= 0:
            break
        try:
            resultados = await process_category(categoria, distributor, max_noticias=max_per_region, max_drafts=remaining)
            if resultados:
                todos_los_resultados[categoria] = resultados
        except Exception as e:
            print(f"\n  ERROR procesando '{categoria}': {e}")
            continue

    # Resumen final
    total_articulos = sum(len(v) for v in todos_los_resultados.values())
    print(f"\n{'='*60}")
    print(f"  RESUMEN FINAL")
    print(f"{'='*60}")
    print(f"  Categorias con contenido: {len(todos_los_resultados)}/{len(CATEGORIAS_ACTIVAS)}")
    print(f"  Total de articulos generados: {total_articulos}")
    for cat, contents in todos_los_resultados.items():
        for content in contents:
            titulo = content.get("titulo_articulo", "Sin titulo")
            print(f"    - [{cat[:25]}] {titulo[:60]}")
    print(f"\n  Articulos guardados en (Borradores): {os.path.abspath(OUTPUT_DIR)}")
    print("  Pipeline finalizado.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline Autonomo DatoSinFiltro")
    parser.add_argument("--topic", type=str, help="Tema especifico a buscar manualmente", default=None)
    args = parser.parse_args()
    
    asyncio.run(main(topic=args.topic))
