import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from src.research import alternative_source_pairs, event_search_queries, investigate_event, rank_event_candidates
from bs4 import BeautifulSoup
from src.crawler import _extract_text_sync, _jsonld_article_body, investigate_news
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

    def test_events_with_multiple_outlets_are_investigated_first(self):
        pool = [
            {"titulo": "Empresa presenta nueva batería en Lima", "url": "https://one.example/battery", "fuente": "Uno"},
            {"titulo": "Perú aprueba nueva ley de salud pública", "url": "https://two.example/health", "fuente": "Dos"},
            {"titulo": "Nueva ley de salud pública aprobada en Perú", "url": "https://three.example/health", "fuente": "Tres"},
        ]
        chosen = rank_event_candidates(pool, limit=2)
        self.assertEqual({item["url"] for item in chosen}, {pool[1]["url"], pool[2]["url"]})

    def test_one_official_candidate_gets_an_investigation_slot(self):
        pool = [
            {"titulo": "MTC publica nuevo calendario de transporte", "url": "https://www.gob.pe/institucion/mtc/noticias/123", "fuente": "MTC", "origen": "official_peru"},
            {"titulo": "FIFA anuncia nuevo calendario deportivo", "url": "https://a.example/news", "fuente": "A"},
            {"titulo": "Nuevo calendario deportivo anunciado por FIFA", "url": "https://b.example/news", "fuente": "B"},
        ]
        chosen = rank_event_candidates(pool, limit=2)
        self.assertIn(pool[0], chosen)

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

    def test_uncovered_primary_notice_is_read_before_rejection(self):
        story = {"titulo": "MTC publica nuevo calendario para Lima", "url": "https://www.gob.pe/institucion/mtc/noticias/123", "fuente": "MTC"}
        primary = [{"url": story["url"], "_context": "Comunicado del MTC"}]
        with patch("src.research.extract_custom_topic_google_rss", return_value=[]), patch(
            "src.research.extract_bing_news_rss", return_value=[]
        ), patch("src.research.investigate_news", new_callable=AsyncMock, return_value=("Comunicado del MTC", "", [], "", primary)) as reader:
            context, found, stats = asyncio.run(investigate_event(story))
        self.assertEqual(context, "Comunicado del MTC")
        self.assertEqual(found, primary)
        self.assertEqual(stats["related_headlines"], 0)
        reader.assert_awaited_once()

    def test_alternative_pairs_skip_rejected_pair_and_keep_matching_texts(self):
        sources = [
            {"url": f"https://{number}.example/article", "_context": f"--- Fuente: {number} ---\nTexto {number}"}
            for number in range(4)
        ]
        pairs = alternative_source_pairs(sources)
        self.assertEqual(len(pairs), 4)
        self.assertEqual([source["url"] for source in pairs[0][1]], [sources[0]["url"], sources[2]["url"]])
        self.assertIn("Texto 0", pairs[0][0])
        self.assertIn("Texto 2", pairs[0][0])
        self.assertNotIn("Texto 1", pairs[0][0])

    def test_retry_reuses_headlines_before_searching_again(self):
        story = {"titulo": "Perú presenta satélite de telecomunicaciones en Lima", "url": "https://first.example/a", "fuente": "Uno"}
        related = {"titulo": "Satélite de telecomunicaciones presentado en Lima", "url": "https://second.example/b", "fuente": "Dos"}
        sources = [{"url": f"https://{number}.example/a", "_context": f"Texto {number}"} for number in range(4)]
        with patch("src.research.extract_custom_topic_google_rss") as google, patch(
            "src.research.extract_bing_news_rss"
        ) as bing, patch("src.research.investigate_news", new_callable=AsyncMock, return_value=("Cuatro textos", "", [], "", sources)) as reader:
            context, found, stats = asyncio.run(investigate_event(
                story, candidate_cache=[related], searched_rounds=1, required_sources=4,
            ))
        self.assertEqual(context, "Cuatro textos")
        self.assertEqual(found, sources)
        self.assertEqual(stats["queries"], 0)
        reader.assert_awaited_once()
        google.assert_not_called()
        bing.assert_not_called()

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
        self.assertIn("La entidad", sources[0]["_context"])
        self.assertIn("Otro medio", sources[1]["_context"])
        browser.assert_called_once_with(stories[0]["url"])

    def test_gob_pe_reader_uses_release_body_instead_of_date_only(self):
        html = '<main><p>9 de octubre de 2026</p><div class="feed-content">' + (
            'El ministerio publicó un calendario de actividades en Lima. ' * 12
        ) + '</div></main>'
        response = type("Response", (), {
            "status_code": 200, "headers": {}, "encoding": "utf-8",
            "content": html.encode("utf-8"), "text": html,
            "raise_for_status": lambda self: None,
        })()
        with patch("src.crawler._public_url", return_value=True), patch(
            "src.crawler._public_dns", return_value=True
        ), patch("src.crawler.requests.get", return_value=response):
            text, _, _, _ = _extract_text_sync("https://www.gob.pe/institucion/mtc/noticias/123")
        self.assertIn("calendario de actividades", text)
        self.assertGreater(len(text), 300)

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

    def test_licensed_image_search_tries_topic_before_stock(self):
        image = {"url": "https://commons.wikimedia.org/hospital.jpg", "origen": "https://commons.wikimedia.org/wiki/File:Hospital.jpg", "tipo": "Ilustración de archivo"}
        with patch.object(multimedia, "PEXELS_API_KEY", "configured"), patch.object(
            multimedia, "search_commons_images", side_effect=[[], [image]]
        ) as commons, patch.object(multimedia, "_search_pexels_licensed") as pexels:
            found = multimedia.search_licensed_images(
                "Lima inaugura un nuevo hospital público", count=2,
                categoria="Salud, Bienestar y Estilo de Vida", minimum=1,
            )
        self.assertEqual(found, [image])
        self.assertEqual(commons.call_args.kwargs["query_override"], "hospital healthcare")
        pexels.assert_not_called()

    def test_one_matching_commons_image_does_not_need_stock_filler(self):
        image = {"url": "https://commons.wikimedia.org/topic.jpg", "tipo": "Ilustración de archivo"}
        with patch.object(multimedia, "PEXELS_API_KEY", "configured"), patch.object(
            multimedia, "search_commons_images", return_value=[image]
        ), patch.object(multimedia, "_search_pexels_licensed") as pexels:
            found = multimedia.search_licensed_images("Tecnología en Lima", count=2, minimum=1)
        self.assertEqual(found, [image])
        pexels.assert_not_called()

    def test_health_stock_search_follows_subject_of_headline(self):
        category = "Salud, Bienestar y Estilo de Vida"
        self.assertEqual(multimedia._stock_topic("Anemia infantil preocupa en Arequipa", category)[0], "child nutrition healthcare")
        self.assertEqual(multimedia._stock_topic("Aumentan consultas por ansiedad y salud mental", category)[0], "mental health counseling therapy")
        self.assertEqual(multimedia._stock_topic("Estudio médico prueba un nuevo tratamiento", category)[0], "medical research laboratory")

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

    def test_sports_score_prediction_is_not_technology_news(self):
        self.assertFalse(extractor.matches_category(
            {"titulo": "Colombia vs Perú: inteligencia artificial predice marcador final"},
            "Tecnologia, Gadgets e Inteligencia Artificial",
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
