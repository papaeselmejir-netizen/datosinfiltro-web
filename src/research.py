"""Bounded, event-focused research before drafting a news article."""

import asyncio
import re

from src.crawler import investigate_news
from src.editorial import (
    corroboration_queries, keywords, matches_story_aspect, normalized_headline,
    query_terms, rank_news, select_corrob_sources,
)
from src.extractor import extract_bing_news_rss, extract_custom_topic_google_rss


def event_search_queries(story):
    """Search the same event with headline details and one snippet-based variant."""
    title = (story.get("titulo") or "").rsplit(" - ", 1)[0]
    queries = corroboration_queries(title)
    title_words = query_terms(title, limit=None).split()
    if len(title_words) >= 4:
        queries.extend((
            " ".join(title_words[:2] + title_words[-1:]),
            " ".join(title_words[:1] + title_words[-2:]),
        ))
    snippet_words = query_terms(story.get("snippet", ""), limit=None).split()
    additions = [word for word in snippet_words if word not in title_words]
    if len(title_words) >= 2 and additions:
        named = [word.lower() for word in re.findall(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{3,}\b", story.get("snippet", ""))
                 if word.lower() in additions]
        detail = named[:1] or additions[:1]
        queries.insert(min(3, len(queries)), " ".join(dict.fromkeys(title_words[:2] + title_words[-2:] + detail)))
    return list(dict.fromkeys(queries))[:4]


GENERIC_NEWS_TERMS = {
    "inteligencia", "artificial", "tecnologia", "tecnologico", "salud", "medicina",
    "politica", "elecciones", "gobierno", "deportes", "futbol", "liga", "copa",
    "partido", "equipo", "economia", "mercado", "empresa", "empresas",
    "negocios", "finanzas", "gaming", "juegos", "videojuegos", "esports",
    "cine", "musica", "concierto", "conciertos", "viral", "tendencias",
    "nueva", "nuevo", "ultimas", "noticia", "noticias",
}


def rank_event_candidates(candidates, limit):
    """Prefer events corroborated by headlines sharing distinctive details."""
    ranked = rank_news(candidates)

    def related(first, second):
        if first.get("url") == second.get("url") or first.get("fuente") == second.get("fuente"):
            return False
        if normalized_headline(first.get("titulo")) == normalized_headline(second.get("titulo")):
            return False
        if not matches_story_aspect(first.get("titulo"), second.get("titulo")):
            return False
        specific_first = keywords(first.get("titulo")) - GENERIC_NEWS_TERMS
        specific_second = keywords(second.get("titulo")) - GENERIC_NEWS_TERMS
        return len(specific_first & specific_second) >= 2

    coverage = {item["url"]: sum(related(item, other) for other in ranked) for item in ranked}
    return sorted(ranked, key=lambda item: coverage[item["url"]], reverse=True)[:limit]


async def investigate_event(story, browser_budget=2):
    """Expand coverage only when earlier searches cannot supply two readable sources.

    The browser fallback, page count and search rounds have explicit caps. The
    normal source independence and article verification gates still decide if
    the article can be published.
    """
    queries = event_search_queries(story)
    candidates = []
    seen_urls = set()
    stats = {"queries": 0, "related_headlines": 0, "readable_sources": 0}
    context, sources = "", []
    if not queries:
        return context, sources, stats

    # Two rounds: the second is only needed when the first lacks readable
    # corroboration. Bing is queried with a second formulation in that case.
    for round_queries in (queries[:2], queries[2:]):
        if not round_queries:
            continue
        searches = []
        for query in round_queries:
            searches.append(asyncio.to_thread(
                extract_custom_topic_google_rss, query,
                geo="PE" if story.get("region") == "Perú" else "US",
                max_items=25,
            ))
        searches.append(asyncio.to_thread(extract_bing_news_rss, round_queries[0], max_items=25))
        results = await asyncio.gather(*searches, return_exceptions=True)
        stats["queries"] += len(searches)
        for result in results:
            if isinstance(result, Exception):
                print(f"    Buscador no disponible: {type(result).__name__}")
                continue
            for candidate in result:
                url = candidate.get("url")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    candidates.append(candidate)

        related = select_corrob_sources(story, candidates, limit=18)
        stats["related_headlines"] = len(related)
        if not related:
            continue
        context, _, _, _, sources = await investigate_news(
            [story, *related], return_sources=True, required_sources=2,
            browser_budget=browser_budget,
        )
        stats["readable_sources"] = len(sources)
        if len(sources) >= 2:
            break
    return context, sources, stats
