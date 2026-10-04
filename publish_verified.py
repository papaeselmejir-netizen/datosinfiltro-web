"""Publish validated drafts and rebuild the static site as one local transaction."""

import glob
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.editorial import publication_errors
from website import builder

BASE = Path(__file__).resolve().parent


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
            if article.get("schema_version") != 2 or article.get("categoria") not in categories:
                continue
            if publication_errors(article):
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

        stage = Path(tempfile.mkdtemp(prefix=".publish-next-", dir=public_dir.parent))
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
