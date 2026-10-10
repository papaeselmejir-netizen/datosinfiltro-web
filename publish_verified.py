"""Publish validated drafts and rebuild the static site as one local transaction."""

import glob
import json
import os
import re
import shutil
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.editorial import claim_evidence_errors, keywords, publication_errors
from website import builder

BASE = Path(__file__).resolve().parent


def record_daily_publications(articles, directory, run_id):
    """Add actual publications to the research report after the site is swapped."""
    if not directory:
        return
    day = datetime.now(ZoneInfo("America/Lima")).date().isoformat()
    path = Path(directory) / f"{day}.json"
    if not path.is_file():
        return
    report = json.loads(path.read_text(encoding="utf-8"))
    runs = report.get("runs", {})
    if not run_id and runs:
        run_id = max(runs, key=lambda key: runs[key].get("started_at", ""))
    run = runs.get(run_id)
    if not run:
        return
    run["published"] = dict(Counter(article.get("categoria") for article in articles))
    for category, totals in report.get("categories", {}).items():
        totals["publicadas"] = sum(
            item.get("published", {}).get(category, 0)
            for item in report["runs"].values()
        )
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as file:
            file.write(f"\n### Publicaciones reales del {day}\n\n")
            file.write("| Categoría | Publicadas hoy | Bloqueo principal |\n| --- | ---: | --- |\n")
            for category, totals in report["categories"].items():
                file.write(f"| {category} | {totals['publicadas']} | {totals['bloqueo_principal']} |\n")


def fresh_election_evidence(article):
    """Recheck mutable election figures immediately before making a page public."""
    if article.get("categoria") != "Noticias de Ultima Hora y Politica" or not (
        keywords(" ".join(str(article.get(field, "")) for field in ("titulo_fuente", "titulo_articulo")))
        & {"elecciones", "electoral", "escrutinio", "encuestas", "votacion"}
    ):
        return True
    from src.crawler import extract_text_from_url, readable_article_text

    texts = []
    for source in article.get("fuentes", [])[:2]:
        text = extract_text_from_url(source.get("url", ""))[0]
        if not readable_article_text(text):
            return False
        texts.append(text)
    if len(texts) < 2:
        return False
    article_text = " ".join(str(article.get(field, "")) for field in ("titulo_articulo", "resumen", "articulo_web"))
    return not claim_evidence_errors(article_text, " ".join(texts))


def publish(drafts_dir=None, published_dir=None, public_dir=None):
    drafts_dir = Path(drafts_dir or BASE / "drafts").resolve()
    published_dir = Path(published_dir or BASE / "published").resolve()
    public_dir = Path(public_dir or BASE / "website" / "public").resolve()
    with (BASE / "categories.json").open(encoding="utf-8") as file:
        categories = set(json.load(file))

    staged_articles = []
    for source in glob.glob(str(drafts_dir / "**" / "*.json"), recursive=True):
        source = Path(source)
        try:
            article = json.loads(source.read_text(encoding="utf-8"))
            if article.get("schema_version") != 2 or article.get("media_review_version", 0) < 1 or article.get("categoria") not in categories:
                continue
            if publication_errors(article):
                continue
            if not fresh_election_evidence(article):
                print(f"Borrador electoral desactualizado o sin fuentes legibles: {source.name}")
                continue
            article["fecha_publicacion"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            article["revision_humana"] = False
            category = re.sub(r"[^A-Za-z0-9]+", "_", article["categoria"])
            destination = published_dir / article["fecha_publicacion"][:10] / category / source.name
            if destination.exists():
                continue
            staged_articles.append((source, destination, article))
        except (OSError, ValueError, TypeError) as exc:
            print(f"Borrador ilegible {source}: {exc}")
    if not staged_articles:
        print("No hay borradores verificados para publicar")
        return 0

    created = []
    stage = None
    backup = None
    swapped = False
    try:
        for _, destination, article in staged_articles:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")
            created.append(destination)

        # Path.mkdir inherits the public directory's ACL on Windows. tempfile.mkdtemp
        # creates a private directory there, making the rebuilt site unreadable to
        # other workspace processes after the atomic rename.
        stage = public_dir.parent / f".publish-next-{uuid.uuid4().hex}"
        stage.mkdir()
        for asset in ("css", "js"):
            if (public_dir / asset).is_dir():
                shutil.copytree(public_dir / asset, stage / asset)
        if (public_dir / "favicon.svg").is_file():
            shutil.copy2(public_dir / "favicon.svg", stage / "favicon.svg")
        old_published, old_public = builder.OUTPUT_DIR, builder.PUBLIC_DIR
        try:
            builder.OUTPUT_DIR, builder.PUBLIC_DIR = str(published_dir), str(stage)
            builder.build_site()
        finally:
            builder.OUTPUT_DIR, builder.PUBLIC_DIR = old_published, old_public
        if not (stage / "index.html").is_file():
            raise RuntimeError("La compilación no creó la portada")

        if public_dir.exists():
            backup = public_dir.parent / f".publish-backup-{uuid.uuid4().hex}"
            public_dir.rename(backup)
        try:
            stage.rename(public_dir)
            stage = None
            swapped = True
        except Exception:
            if backup:
                backup.rename(public_dir)
                backup = None
            raise
        for source, _, _ in staged_articles:
            try:
                source.unlink()
            except OSError as exc:
                print(f"Aviso: no se pudo retirar el borrador {source}: {exc}")
        if backup:
            try:
                shutil.rmtree(backup)
            except OSError as exc:
                print(f"Aviso: copia de seguridad retenida en {backup}: {exc}")
        try:
            record_daily_publications(
                [article for _, _, article in staged_articles],
                os.getenv("PIPELINE_DAILY_REPORT_DIR"),
                (os.getenv("GITHUB_RUN_ID") + "-" + os.getenv("GITHUB_RUN_ATTEMPT", "1"))
                if os.getenv("GITHUB_RUN_ID") else None,
            )
        except (OSError, ValueError, TypeError) as exc:
            print(f"Aviso: no se pudo actualizar el balance diario: {type(exc).__name__}")
        print(f"Publicadas {len(staged_articles)} noticias verificadas")
        return len(staged_articles)
    except Exception:
        if not swapped:
            for destination in created:
                destination.unlink(missing_ok=True)
        raise
    finally:
        if stage and stage.exists():
            shutil.rmtree(stage)


if __name__ == "__main__":
    publish()
