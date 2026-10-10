"""Replace repeated historical covers with verified alternatives."""

import argparse
import copy
import json
import os
from collections import Counter
from pathlib import Path

from src.editorial import media_alignment_errors, publication_errors, sport_for_headline
from src.multimedia import PEXELS_API_KEY, _search_pexels_licensed, image_identity, search_licensed_images
from website import builder


BASE = Path(__file__).resolve().parent


def _cover(article):
    images = article.get("imagenes") or []
    return image_identity(images[0] if images else article.get("imagen_url", ""))


def _with_cover(article, image, existing_index=None):
    result = copy.deepcopy(article)
    images = result.get("imagenes") or []
    if existing_index is not None:
        images[0], images[existing_index] = images[existing_index], images[0]
    else:
        images = [image] + images[1:2]
    result["imagenes"] = images
    result["imagen_url"] = images[0]["url"]
    result["extra_images"] = [item["url"] for item in images[1:]]
    return result


def _safe_replacement(original, candidate):
    image = candidate["imagenes"][0]
    if not all(image.get(field) for field in ("url", "descripcion", "credito", "origen", "licencia", "licencia_url")):
        return False
    if media_alignment_errors({"titulo_articulo": candidate.get("titulo_articulo", ""), "imagenes": [image]}):
        return False
    return not set(publication_errors(candidate)) - set(publication_errors(original))


def repair_covers(published_dir, search=True, write=True):
    published_dir = Path(published_dir)
    records = []
    for path in sorted(published_dir.rglob("*.json")):
        try:
            article = json.loads(path.read_text(encoding="utf-8"))
            images = article.get("imagenes") or []
            options = [image_identity(image) for image in images[:2]]
            if not options or not options[0]:
                continue
            records.append({"path": path, "article": article, "options": options})
        except (OSError, ValueError, TypeError):
            continue
    before = Counter(record["options"][0] for record in records)
    assigned = {}
    chosen = {}
    unresolved = []

    # Keep original covers where possible; move repeated ones to an existing
    # second image before requesting anything new.
    for index, record in enumerate(records):
        for option_index, identity in enumerate(record["options"]):
            if identity and identity not in assigned:
                candidate = _with_cover(record["article"], record["article"]["imagenes"][option_index], option_index)
                if _safe_replacement(record["article"], candidate):
                    assigned[identity] = index
                    chosen[index] = candidate
                    break
        if index not in chosen:
            unresolved.append(index)

    def move(index, visited):
        record = records[index]
        for option_index, identity in enumerate(record["options"]):
            if not identity or identity in visited:
                continue
            visited.add(identity)
            owner = assigned.get(identity)
            if owner is not None and not move(owner, visited):
                continue
            candidate = _with_cover(record["article"], record["article"]["imagenes"][option_index], option_index)
            if not _safe_replacement(record["article"], candidate):
                continue
            old = _cover(chosen[index]) if index in chosen else ""
            if old:
                assigned.pop(old, None)
            assigned[identity] = index
            chosen[index] = candidate
            return True
        return False

    for index in unresolved:
        move(index, set())

    # The matching above can use secondary images already in the archive.
    # For remaining stories, search fresh licensed photographs by headline.
    for index, record in enumerate(records):
        if index in chosen or not search:
            continue
        article = record["article"]
        title = article.get("titulo_articulo") or article.get("titulo_fuente") or ""
        search_title = title
        if article.get("categoria") == "Deportes en Vivo" and not sport_for_headline(title):
            descriptions = " ".join(image.get("descripcion", "") for image in article.get("imagenes", [])[:2])
            if "football" in descriptions.lower() or "soccer" in descriptions.lower():
                search_title += " fútbol"
        candidates = search_licensed_images(
            search_title, count=4, categoria=article.get("categoria"), minimum=4,
            excluded=set(assigned),
        )
        for image in candidates:
            identity = image_identity(image)
            if not identity or identity in assigned:
                continue
            candidate = _with_cover(article, image)
            if _safe_replacement(article, candidate):
                assigned[identity] = index
                chosen[index] = candidate
                break
        if index not in chosen and PEXELS_API_KEY:
            stock = _search_pexels_licensed(
                search_title, 4, article.get("categoria"),
                excluded=set(assigned) | {image_identity(item) for item in candidates},
            )
            for image in stock:
                identity = image_identity(image)
                if not identity or identity in assigned:
                    continue
                candidate = _with_cover(article, image)
                if _safe_replacement(article, candidate):
                    assigned[identity] = index
                    chosen[index] = candidate
                    break

    changes = []
    remaining = []
    for index, record in enumerate(records):
        candidate = chosen.get(index)
        if candidate is None:
            remaining.append(record["article"].get("titulo_articulo", record["path"].name))
            continue
        if _cover(candidate) != record["options"][0]:
            changes.append((record["path"], candidate))
    if write:
        for path, article in changes:
            path.write_text(json.dumps(article, ensure_ascii=False, indent=4), encoding="utf-8")
        if changes:
            builder.build_site()
    after = Counter(_cover(chosen.get(index, record["article"])) for index, record in enumerate(records))
    report = {
        "articles": len(records),
        "repeated_covers_before": sum(count > 1 for count in before.values()),
        "affected_articles_before": sum(count for count in before.values() if count > 1),
        "changed_covers": len(changes),
        "repeated_covers_after": sum(count > 1 for count in after.values()),
        "affected_articles_after": sum(count for count in after.values() if count > 1),
        "without_unique_cover": remaining,
    }
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-search", action="store_true")
    args = parser.parse_args()
    outcome = repair_covers(BASE / "published", search=not args.no_search, write=not args.dry_run)
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as file:
            file.write("\n### Renovación de portadas anteriores\n\n")
            file.write(f"- Noticias revisadas: {outcome['articles']}\n")
            file.write(f"- Portadas cambiadas: {outcome['changed_covers']}\n")
            file.write(f"- Noticias con portada repetida antes: {outcome['affected_articles_before']}\n")
            file.write(f"- Noticias con portada repetida después: {outcome['affected_articles_after']}\n")
            for title in outcome["without_unique_cover"]:
                file.write(f"- Pendiente: {title}\n")
