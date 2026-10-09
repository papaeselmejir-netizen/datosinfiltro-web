import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from src.research import event_search_queries, investigate_event
from bs4 import BeautifulSoup
from src.crawler import _jsonld_article_body, investigate_news
from src import multimedia
from src import extractor


class ResearchTests(unittest.TestCase):
    def test_search_uses_event_details_and_snippet(self):
        queries = event_search_queries({
            "titulo": "Empresa presenta satélite de telecomunicaciones en Lima - Medio",
            "snippet": "El lanzamiento será desde Pucusana el jueves",
        })
        self.assertGreaterEqual(len(queries), 3)
        self.assertTrue(any("pucusana" in query for query in queries))
        self.assertTrue(all("medio" not in query for query in queries))

    def test_second_round_runs_when_first_pages_are_unreadable(self):
        story = {"titulo": "Perú presenta satélite de telecomunicaciones en Lima", "url": "https://first.example/a", "fuente": "Uno", "region": "Perú"}
        related = {"titulo": "Satélite de telecomunicaciones presentado en Lima", "url": "https://second.example/b", "fuente": "Dos"}
        sources = [{"url": story["url"]}, {"url": related["url"]}]
        empty = ("", "", [], "", [])
        confirmed = ("Dos textos", "", [], "", sources)
        with patch("src.research.extract_custom_topic_google_rss", return_value=[related]) as google, patch(
            "src.research.extract_bing_news_rss", return_value=[]
        ) as bing, patch("src.research.investigate_news", new_callable=AsyncMock, side_effect=[empty, confirmed]) as reader:
            context, found, stats = asyncio.run(investigate_event(story))
        self.assertEqual(context, "Dos textos")
        self.assertEqual(found, sources)
        self.assertEqual(reader.await_count, 2)
        self.assertGreaterEqual(google.call_count, 2)
        self.assertEqual(bing.call_count, 2)
        self.assertEqual(stats["readable_sources"], 2)

    def test_browser_recovers_one_unreadable_source_within_budget(self):
        text = "La entidad anunció el lanzamiento del satélite en Lima. " * 25
        second_text = "El proyecto tecnológico se presentó durante una conferencia y tendrá nuevas pruebas. " * 20
        stories = [
            {"titulo": "Satélite anunciado en Lima", "url": "https://first.example/a", "fuente": "Uno", "origen": "direct_rss"},
            {"titulo": "Otro medio informa del satélite en Lima", "url": "https://second.example/b", "fuente": "Dos", "origen": "direct_rss"},
        ]
        with patch("src.crawler.extract_text_from_url", side_effect=[("", "", [], ""), (second_text, "", [], "")]), patch(
            "src.crawler.extract_text_with_browser", return_value=text
        ) as browser, patch("src.crawler.asyncio.sleep", new_callable=AsyncMock):
            _, _, _, _, sources = asyncio.run(investigate_news(stories, return_sources=True, required_sources=2, browser_budget=1))
        self.assertEqual(len(sources), 2)
        browser.assert_called_once_with(stories[0]["url"])

    def test_licensed_event_image_is_preferred_to_generic_stock(self):
        event = {"url": "https://commons.wikimedia.org/event.jpg", "tipo": "Ilustración de archivo"}
        stock = {"url": "https://images.pexels.com/stock.jpg", "tipo": "Ilustración de archivo"}
        with patch.object(multimedia, "PEXELS_API_KEY", "configured"), patch.object(
            multimedia, "search_commons_images", return_value=[event]
        ) as commons, patch.object(multimedia, "_search_pexels_licensed", return_value=[stock]) as pexels:
            images = multimedia.search_licensed_images("Conferencia sobre salud en Lima", count=2)
        self.assertEqual(images, [event, stock])
        commons.assert_called_once()
        self.assertEqual(pexels.call_args.args[1], 1)

    def test_gambling_is_not_classified_as_video_games(self):
        self.assertFalse(extractor.matches_category(
            {"titulo": "Bloquean 50 plataformas de juego clandestino y apuestas en Perú"},
            "Gaming y Esports",
        ))
        self.assertFalse(extractor.matches_category(
            {"titulo": "SBC Summit 2026: el juego online y desafíos en Perú", "snippet": "Industria gaming", "url": "https://sbcnoticias.com/peru-sbc-summit-apuesta-total/"},
            "Gaming y Esports",
        ))
        self.assertTrue(extractor.matches_category(
            {"titulo": "Nintendo anuncia nuevo videojuego para consola"},
            "Gaming y Esports",
        ))

    def test_structured_article_body_recovers_text_from_dynamic_page(self):
        html = '<script type="application/ld+json">{"@type":"NewsArticle","articleBody":"La noticia confirma los hechos con detalle."}</script>'
        self.assertEqual(_jsonld_article_body(BeautifulSoup(html, "html.parser")), "La noticia confirma los hechos con detalle.")

    def test_google_news_link_is_decoded_even_without_origin_label(self):
        story = {"titulo": "Comunicado sobre salud en Lima", "url": "https://news.google.com/rss/articles/example", "fuente": "Medio"}
        body = "El comunicado describe los hechos y aporta detalles verificables en Lima. " * 20
        with patch("src.crawler.decode_google_news_url", return_value="https://publisher.example/health") as decoder, patch(
            "src.crawler.extract_text_from_url", return_value=(body, "", [], "")
        ) as reader, patch("src.crawler.asyncio.sleep", new_callable=AsyncMock):
            _, _, _, _, sources = asyncio.run(investigate_news([story], return_sources=True, required_sources=1))
        decoder.assert_called_once_with(story["url"])
        reader.assert_called_once_with("https://publisher.example/health")
        self.assertEqual(len(sources), 1)


if __name__ == "__main__":
    unittest.main()
