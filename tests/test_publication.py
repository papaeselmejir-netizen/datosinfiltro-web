import asyncio
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
from urllib.parse import quote
from xml.etree import ElementTree

from src.editorial import publication_errors, official_primary_source, rank_news, select_corrob_sources, matches_story_aspect, near_duplicate_text, corroboration_queries, contradictory_candidate_count, social_source, same_recent_event, claim_evidence_errors, media_alignment_errors
from src.crawler import _public_url, _public_dns, decode_google_news_url, investigate_news, readable_article_text, BROWSER_HEADERS
from website import builder
from publish_verified import publish, fresh_election_evidence
from src import multimedia, extractor


def article():
    return {
        "schema_version": 2,
        "media_review_version": 1,
        "titulo_articulo": "Prueba de transporte en Lima",
        "articulo_web": "Información contrastada sobre el transporte en Lima. " * 40,
        "resumen": "Dos fuentes informan de un cambio en Lima.",
        "categoria": "Noticias de Ultima Hora y Politica",
        "region": "Perú",
        "autor": "Equipo editorial DatoSinFiltro",
        "fecha_publicacion": "2026-10-03T15:00:00+00:00",
        "fuentes": [
            {"url": "https://example.com/a", "medio": "Medio A", "titulo": "Transporte Lima"},
            {"url": "https://other.example.com/b", "medio": "Medio B", "titulo": "Transporte Lima"},
        ],
        "imagenes": [
            {"url": "https://images.pexels.com/1.jpg", "descripcion": "Autobús en Lima", "credito": "Autor A", "origen": "https://www.pexels.com/photo/1", "licencia": "Pexels License", "licencia_url": "https://www.pexels.com/license/", "tipo": "Ilustración de archivo"},
            {"url": "https://images.pexels.com/2.jpg", "descripcion": "Transporte urbano", "credito": "Autor B", "origen": "https://www.pexels.com/photo/2", "licencia": "Pexels License", "licencia_url": "https://www.pexels.com/license/", "tipo": "Ilustración de archivo"},
        ],
        "imagen_url": "https://images.pexels.com/1.jpg",
        "video_url": "https://www.youtube.com/embed/abcdefghijk",
        "video_titulo": "Cambios en transporte de Lima",
        "video_canal": "Canal informativo",
    }


class PublicationTests(unittest.TestCase):
    def setUp(self):
        # Existing tests exercise the old providers without making live RSS calls.
        self.real_specialist_search = extractor.extract_news_specialist_sources
        self.real_official_peru = extractor.extract_news_official_peru
        specialist = patch.object(extractor, "extract_news_specialist_sources", return_value=[])
        specialist.start()
        self.addCleanup(specialist.stop)
        for name in ("extract_news_official_peru", "extract_news_official_world"):
            official = patch.object(extractor, name, return_value=[])
            official.start()
            self.addCleanup(official.stop)

    def test_category_source_registry_covers_peru_and_world(self):
        self.assertEqual(set(extractor.FUENTES_ESPECIALIZADAS), set(extractor.CATEGORIAS))
        self.assertEqual(set(extractor.FUENTES_OFICIALES_PERU), set(extractor.CATEGORIAS))
        for sources in extractor.FUENTES_ESPECIALIZADAS.values():
            for region in ("PE", "WORLD"):
                self.assertGreaterEqual(len(set(sources[region])), 3)

    def test_official_peru_reader_extracts_dated_original_link(self):
        html = '''<div class="card"><h3><a href="/institucion/mef/noticias/123-prueba">MEF publica calendario económico</a></h3>
        <div>El ministerio presenta fechas para Lima.</div><time datetime="2026-10-09 10:00:00.000">9 de octubre de 2026</time></div>'''
        response = SimpleNamespace(content=html.encode("utf-8"), raise_for_status=lambda: None)
        with patch("src.extractor.requests.get", return_value=response):
            found = self.real_official_peru("Finanzas, Negocios y Criptomonedas", max_items=1)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["url"], "https://www.gob.pe/institucion/mef/noticias/123-prueba")
        self.assertEqual(found[0]["fecha"], "2026-10-09 10:00:00.000")
        self.assertEqual(found[0]["origen"], "official_peru")

    def test_topic_specific_official_feed_can_classify_a_product_title(self):
        item = {
            "titulo": "Rockbeasts llegará en enero de 2027",
            "url": "https://blog.playstation.com/2026/10/08/rockbeasts/",
            "origen": "official_world",
        }
        self.assertTrue(extractor.matches_category(item, "Gaming y Esports"))

    def test_specialist_query_uses_category_sites_and_peru_location(self):
        with patch.object(extractor, "extract_custom_topic_google_rss", return_value=[]) as search:
            self.real_specialist_search("Gaming y Esports", geo="PE", max_items=18)
            query = search.call_args.args[0]
        self.assertIn("site:rpp.pe", query)
        self.assertIn("site:elcomercio.pe", query)
        self.assertIn("videojuegos", query)
        self.assertIn("Perú", query)
        self.assertIn("when:4d", query)
        self.assertEqual(search.call_args.kwargs["max_items"], 18)
        with patch.object(extractor, "extract_custom_topic_google_rss", return_value=[]) as world_search:
            self.real_specialist_search("Salud, Bienestar y Estilo de Vida", geo="US")
            world_query = world_search.call_args.args[0]
        self.assertIn("site:sciencedaily.com", world_query)
        self.assertIn("health", world_query)
        self.assertNotIn("Perú", world_query)

    def test_specialist_results_are_prioritized_and_general_search_fills_remainder(self):
        specialist = [{"titulo": "Lima anuncia torneo de esports", "url": "https://rpp.pe/a", "fuente": "RPP"}]
        general = [{"titulo": "Perú recibe nuevo campeonato de videojuegos", "url": "https://otro.pe/b", "fuente": "Otro"}]
        with patch.object(extractor, "extract_news_specialist_sources", return_value=specialist) as specific, patch.object(
            extractor, "extract_news_google_rss", return_value=general
        ) as broad, patch.object(extractor, "extract_custom_topic_google_rss", return_value=[]), patch.object(
            extractor, "extract_bing_news_rss", return_value=[]
        ):
            selected = extractor.extract_news_multi_source("Gaming y Esports", max_items=2, geo="PE")
        self.assertEqual([item["fuente"] for item in selected], ["RPP", "Otro"])
        specific.assert_called_once()
        broad.assert_called_once()

    def test_recent_event_dedup_distinguishes_followup(self):
        published = "Mano Menezes hizo fuerte autocrítica tras derrota de Perú ante Canadá: Hay una diferencia física importante"
        duplicate = "La diferencia física con el rival es bastante: la voz de Mano tras el 2-0 ante Canadá"
        followup = "Mano Menezes confirma cambios para enfrentar a Colombia en el próximo partido"
        self.assertTrue(same_recent_event(published, duplicate))
        self.assertFalse(same_recent_event(published, followup))
        self.assertFalse(same_recent_event(
            "Elecciones Lima 2026 Rafael López Aliaga lidera boca de urna",
            "Elecciones Junín 2026 Fernando Orihuela lidera boca de urna",
        ))
        self.assertFalse(same_recent_event(
            "BTS en Lima plan de desvíos y cierres viales para concierto",
            "Fans de BTS ingresan a San Marcos en Lima antes del concierto",
        ))
        self.assertTrue(same_recent_event(
            "Pedro Sánchez convoca elecciones anticipadas en España tras el rechazo a su plan de vivienda",
            "Pedro Sánchez convoca elecciones generales anticipadas en España para el 29 de noviembre",
        ))

    def test_volleyball_article_rejects_football_photos(self):
        candidate = article()
        candidate["categoria"] = "Deportes en Vivo"
        candidate["titulo_fuente"] = "Emily Zinger explica su fichaje por San Martín en voleibol"
        candidate["titulo_articulo"] = candidate["titulo_fuente"]
        for image in candidate["imagenes"]:
            image["descripcion"] = "Female soccer players during a football match"
        self.assertIn("Una imagen corresponde a otro deporte", publication_errors(candidate))
        for image in candidate["imagenes"]:
            image["descripcion"] = "Women playing volleyball in a match"
        self.assertNotIn("Una imagen corresponde a otro deporte", publication_errors(candidate))

    def test_ai_article_rejects_unrelated_political_photos(self):
        candidate = article()
        candidate["categoria"] = "Tecnologia, Gadgets e Inteligencia Artificial"
        candidate["titulo_articulo"] = "Gobierno anuncia nuevo grupo de inteligencia artificial"
        for image in candidate["imagenes"]:
            image["descripcion"] = "Donald Trump supporters gather at a protest"
        self.assertIn("Una imagen no representa el tema de inteligencia artificial", publication_errors(candidate))

    def test_stock_media_must_match_the_actual_story(self):
        candidate = article()
        candidate["media_review_version"] = 1
        candidate["titulo_articulo"] = "Promperú evalúa el impacto de los conciertos de BTS en Lima"
        candidate["imagenes"][0]["descripcion"] = "A crowd at a protest in Lima under red smoke"
        candidate["imagenes"][1]["descripcion"] = "Musicians on stage at a concert"
        self.assertIn("El material multimedia no representa el asunto central de la noticia", publication_errors(candidate))
        candidate["imagenes"][0]["descripcion"] = "A crowd enjoying a music concert in Lima"
        candidate["video_titulo"] = "Conciertos de BTS en Lima y su impacto económico"
        self.assertNotIn("El material multimedia no representa el asunto central de la noticia", publication_errors(candidate))

    def test_eviction_story_is_not_illustrated_with_ballot_boxes(self):
        title = "Muere una mujer desahuciada en Madrid tras protestas y elecciones"
        candidate = article()
        candidate["media_review_version"] = 1
        candidate["titulo_articulo"] = title
        candidate["titulo_fuente"] = title
        for image in candidate["imagenes"]:
            image["descripcion"] = "A person casting a ballot in an election"
        candidate["video_source"] = "pexels"
        candidate["video_titulo"] = "Man putting paper on ballot box"
        self.assertIn("El material multimedia no representa el asunto central de la noticia", publication_errors(candidate))
        self.assertEqual(multimedia._stock_topic(title)[0], "housing residential apartment building")
        self.assertEqual(multimedia._stock_topic("Pedro Sánchez convoca elecciones por su plan de vivienda")[0], "voting ballot election")

    def test_usdc_is_not_illustrated_as_bitcoin(self):
        candidate = article()
        candidate["media_review_version"] = 1
        candidate["categoria"] = "Finanzas, Negocios y Criptomonedas"
        candidate["titulo_articulo"] = "Samsung Wallet integrará envíos de USDC"
        candidate["imagenes"][0]["descripcion"] = "Bitcoin coins representing digital currency"
        candidate["imagenes"][1]["descripcion"] = "Smartphone digital wallet payment"
        self.assertIn("El material multimedia no representa el asunto central de la noticia", publication_errors(candidate))

    def test_image_research_does_not_require_a_video_yet(self):
        self.assertFalse(media_alignment_errors({
            "titulo_articulo": "Conciertos de BTS en Lima",
            "imagenes": [{"descripcion": "Crowd enjoying a music concert"}],
        }))

    def test_ai_health_policy_needs_health_context(self):
        candidate = article()
        candidate["media_review_version"] = 1
        candidate["categoria"] = "Tecnologia, Gadgets e Inteligencia Artificial"
        candidate["titulo_articulo"] = "Perú establece lineamientos de inteligencia artificial en salud"
        for image in candidate["imagenes"]:
            image["descripcion"] = "Futuristic humanoid robot in Tokyo"
        self.assertIn("El material multimedia no representa el asunto central de la noticia", publication_errors(candidate))

    def test_satellite_article_requires_space_media(self):
        candidate = article()
        candidate["categoria"] = "Tecnologia, Gadgets e Inteligencia Artificial"
        candidate["titulo_articulo"] = "Google lanza un satélite experimental de inteligencia artificial al espacio"
        candidate["video_source"] = "pexels"
        candidate["video_titulo"] = "Close up of a robot"
        for image in candidate["imagenes"]:
            image["descripcion"] = "A futuristic humanoid robot"
        errors = publication_errors(candidate)
        self.assertIn("Una imagen no representa el tema espacial", errors)
        self.assertIn("El video de archivo no representa el tema espacial", errors)
        self.assertEqual(multimedia._stock_topic(candidate["titulo_articulo"], candidate["categoria"])[0], "satellite space orbit")
        candidate["video_titulo"] = "Satellite orbiting Earth in space"
        for image in candidate["imagenes"]:
            image["descripcion"] = "Satellite in orbit around Earth"
        self.assertNotIn("Una imagen no representa el tema espacial", publication_errors(candidate))

    def test_epic_free_game_article_rejects_other_named_games(self):
        candidate = article()
        candidate["categoria"] = "Gaming y Esports"
        candidate["titulo_articulo"] = "Epic Games Store regala dos juegos para PC"
        for image in candidate["imagenes"]:
            image["descripcion"] = "Vintage Pokemon game cartridges"
        self.assertIn("Una imagen muestra un videojuego ajeno al regalo de Epic", publication_errors(candidate))
        self.assertEqual(multimedia._stock_topic(candidate["titulo_articulo"], candidate["categoria"])[0], "desktop gaming computer setup")

    def test_specialist_health_feed_and_topic_cues(self):
        self.assertIn("https://www.sciencedaily.com/rss/health_medicine.xml", extractor.FUENTES_INTERNACIONALES["Salud, Bienestar y Estilo de Vida"])
        item = {"titulo": "New clinical trial tests a cancer therapy", "snippet": "", "origen": "direct_rss"}
        self.assertTrue(extractor.matches_category(item, "Salud, Bienestar y Estilo de Vida"))

    def test_trends_rejects_election_news_and_accepts_social_culture(self):
        election = {"titulo": "Resultados de elecciones en Junín", "snippet": "", "origen": "google_rss_custom"}
        cultural = {"titulo": "El fenómeno BTS inspira nuevas tendencias de moda en Lima", "snippet": "", "origen": "local_rss"}
        self.assertFalse(extractor.matches_category(election, "Tendencias"))
        self.assertTrue(extractor.matches_category(cultural, "Tendencias"))
        self.assertIn("https://elcomercio.pe/arc/outboundfeeds/rss/category/somos/?outputType=xml", extractor.FUENTES_LOCALES_PERU["Tendencias"])

    def test_business_conference_rejects_ballot_photos(self):
        candidate = article()
        candidate["categoria"] = "Finanzas, Negocios y Criptomonedas"
        candidate["titulo_articulo"] = "Congreso de la Empresa Familiar reúne a ejecutivos"
        for image in candidate["imagenes"]:
            image["descripcion"] = "A person casts a ballot in an election"
        self.assertIn("Una imagen no representa el encuentro empresarial", publication_errors(candidate))
        self.assertEqual(multimedia._stock_topic(candidate["titulo_articulo"], candidate["categoria"])[0], "business conference executives")

    def test_numeric_claims_and_agency_attribution_need_source_evidence(self):
        source = "El resultado fue 47,1% frente a 45% con 99,5% escrutado."
        article_text = "El resultado fue 47.1% frente a 45%. Reuters añade que el candidato tiene 80 años."
        errors = claim_evidence_errors(article_text, source)
        self.assertTrue(any("80" in item for item in errors))
        self.assertTrue(any("Reuters" in item for item in errors))
        self.assertFalse(claim_evidence_errors("El resultado fue 47.1% frente a 45%.", source))

    def test_election_figures_are_rechecked_before_publication(self):
        candidate = article()
        candidate["titulo_articulo"] = "Resultados de elecciones en Brasil"
        candidate["articulo_web"] += " El candidato obtuvo 99,5% de los votos."
        current = ("El resultado fue 99,5% de votos escrutados. " * 30, "", [], "")
        changed = ("El resultado fue 99,8% de votos escrutados. " * 30, "", [], "")
        with patch("src.crawler.extract_text_from_url", return_value=current):
            self.assertTrue(fresh_election_evidence(candidate))
        with patch("src.crawler.extract_text_from_url", return_value=changed):
            self.assertFalse(fresh_election_evidence(candidate))

    def test_category_filter_rejects_election_from_finance(self):
        election = {"titulo": "Papa figura en padrón electoral de Chiclayo", "origen": "google_rss"}
        logistics = {"titulo": "Empresa cierra venta de parque logístico en Lima", "origen": "google_rss"}
        self.assertFalse(extractor.matches_category(election, "Finanzas, Negocios y Criptomonedas"))
        self.assertTrue(extractor.matches_category(logistics, "Finanzas, Negocios y Criptomonedas"))

    def test_election_uses_an_event_video_when_available(self):
        candidate = article()
        candidate["categoria"] = "Noticias de Ultima Hora y Politica"
        candidate["titulo_articulo"] = "Encuestas de elecciones en Lima"
        with patch.object(multimedia, "search_licensed_stock_video") as stock, patch.object(
            multimedia, "search_relevant_youtube_video", return_value={"source": "youtube", "titulo": "Encuestas de elecciones en Lima"}
        ) as youtube:
            video = multimedia.search_relevant_video(candidate["titulo_articulo"], candidate["categoria"])
        self.assertEqual(video["source"], "youtube")
        youtube.assert_called_once()
        stock.assert_not_called()

    def test_bing_rss_uses_original_publisher_url(self):
        original = "https://medio.example/noticia/arequipa"
        redirect = "http://www.bing.com/news/apiclick.aspx?url=" + quote(original, safe="")
        entry = {"title": "Arequipa vota en elecciones regionales", "link": redirect, "published": "Sun, 04 Oct 2026 10:00:00 GMT"}
        with patch("src.extractor.requests.get") as get, patch("src.extractor.feedparser.parse", return_value=SimpleNamespace(entries=[entry])):
            get.return_value.content = b"rss"
            news = extractor.extract_bing_news_rss("elecciones Arequipa")
        self.assertEqual(news[0]["url"], original)
        self.assertEqual(news[0]["fuente"], "medio.example")
        self.assertEqual(news[0]["origen"], "bing_rss")

    def test_corroboration_queries_retry_distinctive_headline_terms(self):
        queries = corroboration_queries("Municipalidad de Lima anuncia nuevo plan de desvíos para concierto de BTS - Medio")
        self.assertEqual(len(queries), 3)
        self.assertIn("lima", queries[0])
        self.assertIn("bts", queries[1])
        self.assertEqual(queries[2], "municipalidad lima anuncia")

    def test_crawler_tries_more_outlets_until_two_are_readable(self):
        items = [
            {"titulo": "Plan de Lima - A", "url": "https://a.example/1", "fuente": "A", "origen": "local_rss"},
            {"titulo": "Plan de Lima - B", "url": "https://b.example/1", "fuente": "B", "origen": "local_rss"},
            {"titulo": "Plan de Lima - B2", "url": "https://b.example/2", "fuente": "B", "origen": "local_rss"},
            {"titulo": "Plan de Lima - C", "url": "https://c.example/1", "fuente": "C", "origen": "local_rss"},
            {"titulo": "Plan de Lima - D", "url": "https://d.example/1", "fuente": "D", "origen": "local_rss"},
        ]
        def text_for(url):
            if url.startswith("https://a.example"):
                return "", "", [], ""
            host = url.split("/")[2]
            return (f"Cobertura independiente publicada por {host}. " * 20, "", [], "")
        with patch("src.crawler.extract_text_from_url", side_effect=text_for) as fetch, patch(
            "src.crawler.asyncio.sleep", new_callable=AsyncMock
        ):
            *_, sources = asyncio.run(investigate_news(items, return_sources=True, required_sources=2))
        self.assertEqual([item["medio"] for item in sources], ["B", "C"])
        self.assertEqual(fetch.call_count, 3)

    def test_compressed_garbage_cannot_count_as_a_source(self):
        self.assertNotIn("br", BROWSER_HEADERS["Accept-Encoding"])
        self.assertFalse(readable_article_text("\ufffd\x01\x02" * 300))
        self.assertTrue(readable_article_text("La selección peruana analizó el encuentro ante Canadá. " * 30))

    def test_category_search_combines_peru_feeds_to_fill_three_slots(self):
        category = "Deportes en Vivo"
        local = [{"titulo": "Alianza Lima anuncia fichaje - Depor", "url": "https://depor.com/a", "fuente": "Depor"}]
        google = [
            {"titulo": "Alianza Lima anuncia fichaje - Otro", "url": "https://otro.pe/a", "fuente": "Otro"},
            {"titulo": "Universitario de Deportes anuncia fichaje - RPP", "url": "https://rpp.pe/b", "fuente": "RPP"},
            {"titulo": "Sporting Cristal confirma entrenador - Infobae", "url": "https://infobae.com/c", "fuente": "Infobae"},
            {"titulo": "Club argentino cambia de entrenador - TN", "url": "https://tn.com.ar/d", "fuente": "TN"},
        ]
        with patch.object(extractor, "extract_news_local_rss", return_value=local) as local_search, patch.object(
            extractor, "extract_news_google_rss", return_value=google
        ) as google_search, patch.object(extractor, "extract_custom_topic_google_rss", return_value=google), patch.object(
            extractor, "extract_bing_news_rss", return_value=[]
        ):
            news = extractor.extract_news_multi_source(category, max_items=3, lang="es", geo="PE")
        self.assertEqual(len(news), 3)
        self.assertEqual({item["fuente"] for item in news}, {"Depor", "RPP", "Infobae"})
        self.assertEqual(local_search.call_args.kwargs["max_items"], 6)
        self.assertEqual(google_search.call_args.kwargs["max_items"], 18)

    def test_geography_checks_event_and_not_publisher_name(self):
        self.assertFalse(extractor.is_peru_story({"titulo": "Nueva película en España - El Peruano"}))
        self.assertTrue(extractor.is_peru_story({"titulo": "Nueva película llega a Lima - Medio español"}))
        world = [
            {"titulo": "Nueva película en España - Medio A", "url": "https://a.example/1", "fuente": "A"},
            {"titulo": "Nueva película llega a Lima - Medio B", "url": "https://b.example/2", "fuente": "B"},
        ]
        with patch.object(extractor, "extract_news_google_rss", return_value=world), patch.object(
            extractor, "extract_custom_topic_google_rss", return_value=[]
        ), patch.object(extractor, "extract_bing_news_rss", return_value=[]):
            selected = extractor.extract_news_multi_source("Entretenimiento, Farandula y Cine", max_items=3, geo="US")
        self.assertEqual([item["fuente"] for item in selected], ["A"])

    def test_search_skips_stale_social_and_viewing_guides(self):
        stale = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        items = [
            {"titulo": "Dónde ver Argentina vs Brasil en Perú - Medio A", "url": "https://a.example/1", "fuente": "A"},
            {"titulo": "Perú anuncia nueva ley de salud - Facebook", "url": "https://b.example/2", "fuente": "facebook.com"},
            {"titulo": "Lima inaugura nuevo hospital - Medio B", "url": "https://c.example/3", "fuente": "B", "fecha": stale},
            {"titulo": "Lima inaugura clínica pública - Medio C", "url": "https://d.example/4", "fuente": "C"},
        ]
        with patch.object(extractor, "extract_news_google_rss", return_value=items), patch.object(
            extractor, "extract_custom_topic_google_rss", return_value=[]
        ), patch.object(extractor, "extract_bing_news_rss", return_value=[]):
            news = extractor.extract_news_multi_source("Salud, Bienestar y Estilo de Vida", max_items=3, geo="PE")
        self.assertEqual([item["fuente"] for item in news], ["C"])

    def test_politics_search_uses_section_feed(self):
        self.assertTrue(all("/category/politica/" in url for url in extractor.FUENTES_LOCALES_PERU["Noticias de Ultima Hora y Politica"]))

    def test_bing_fills_category_when_google_results_are_insufficient(self):
        category = "Gaming y Esports"
        bing = [{"titulo": "Lima anuncia torneo de esports - Medio A", "url": "https://medio.example/a", "fuente": "A"}]
        with patch.object(extractor, "extract_news_google_rss", return_value=[]), patch.object(
            extractor, "extract_custom_topic_google_rss", return_value=[]
        ), patch.object(extractor, "extract_bing_news_rss", return_value=bing) as bing_search:
            selected = extractor.extract_news_multi_source(category, max_items=3, geo="PE")
        self.assertEqual([item["fuente"] for item in selected], ["A"])
        self.assertIn("Perú", bing_search.call_args.args[0])

    def test_world_gaming_uses_specialist_rss(self):
        specialist = [{"titulo": "Nintendo anuncia nuevo videojuego", "url": "https://vidaextra.com/nuevo-juego", "fuente": "vidaextra.com", "origen": "direct_rss"}]
        with patch.object(extractor, "extract_news_world_rss", return_value=specialist) as direct, patch.object(
            extractor, "extract_news_google_rss", return_value=[]
        ), patch.object(extractor, "extract_custom_topic_google_rss", return_value=[]), patch.object(
            extractor, "extract_bing_news_rss", return_value=[]
        ):
            selected = extractor.extract_news_multi_source("Gaming y Esports", max_items=3, geo="US")
        self.assertEqual([item["fuente"] for item in selected], ["vidaextra.com"])
        direct.assert_called_once()

    def test_scoreboards_are_not_editorial_news(self):
        items = [
            {"titulo": "Miami 41-13 Clemson Resultado Final", "fuente": "ESPN"},
            {"titulo": "Lima anuncia nuevo plan para deporte escolar", "fuente": "Medio"},
        ]
        self.assertEqual([item["fuente"] for item in rank_news(items)], ["Medio"])

    def test_early_election_tallies_are_not_stable_articles(self):
        items = [
            {"titulo": "Brasil: primeros resultados del recuento presidencial", "fuente": "A"},
            {"titulo": "Tribunal confirma segunda vuelta presidencial en Brasil", "fuente": "B"},
        ]
        self.assertEqual([item["fuente"] for item in rank_news(items)], ["B"])

    def test_candidate_subtotals_and_other_city_video_are_rejected(self):
        self.assertTrue(contradictory_candidate_count("De los 17 postulantes, 15 son varones y 3 son mujeres."))
        candidate = article()
        candidate["video_titulo"] = "Candidatos a la alcaldía de Arequipa"
        self.assertIn("El video trata una ubicación distinta a la noticia", publication_errors(candidate))
        candidate["video_titulo"] = "Cambios en transporte de Lima"
        candidate["articulo_web"] += " De los 17 candidatos, 15 son hombres y 3 mujeres."
        self.assertIn("Los subtotales de candidatos no coinciden con el total", publication_errors(candidate))

    def test_editorial_gate_requires_media_and_sources(self):
        candidate = article()
        self.assertEqual(publication_errors(candidate), [])
        candidate["video_url"] = "https://untrusted.example/embed/abcdefghijk"
        candidate["imagenes"][0]["licencia"] = ""
        self.assertEqual(len(publication_errors(candidate)), 2)

    def test_single_source_exception_requires_an_actual_primary_domain_and_review(self):
        candidate = article()
        candidate["articulo_web"] = "El MTC publicó el calendario oficial de transporte para Lima. " * 12
        candidate["fuentes"] = [{"url": "https://www.gob.pe/institucion/mtc/noticias/123", "medio": "MTC"}]
        self.assertTrue(official_primary_source(candidate["fuentes"][0]["url"]))
        self.assertIn("Se requieren dos fuentes verificadas", publication_errors(candidate))
        candidate["verificacion_fuentes"] = "comunicado_primario_oficial"
        self.assertEqual(publication_errors(candidate), [])
        for url in ("https://gob.pe.fake.example/a", "https://rpp.pe/a", "https://community.openai.com/t/123", "http://www.gob.pe/a"):
            candidate["fuentes"][0]["url"] = url
            self.assertFalse(official_primary_source(url))
            self.assertIn("Se requieren dos fuentes verificadas", publication_errors(candidate))

    def test_one_licensed_image_and_related_video_are_sufficient(self):
        candidate = article()
        candidate["imagenes"] = candidate["imagenes"][:1]
        self.assertEqual(publication_errors(candidate), [])
        candidate["imagenes"][0]["licencia"] = ""
        self.assertIn("Se requiere una imagen pertinente con licencia registrada", publication_errors(candidate))

    def test_editorial_gate_accepts_licensed_stock_video(self):
        candidate = article()
        candidate.update({
            "video_source": "pexels",
            "video_url": "https://videos.pexels.com/video-files/123/clip.mp4",
            "video_origen": "https://www.pexels.com/video/123/",
            "video_licencia": "Pexels License",
            "video_licencia_url": "https://www.pexels.com/license/",
        })
        self.assertEqual(publication_errors(candidate), [])
        candidate["video_url"] = "https://example.com/clip.mp4"
        self.assertIn("Se requiere un video relacionado con origen verificable", publication_errors(candidate))

    def test_pexels_video_uses_live_api_endpoint(self):
        payload = {"videos": [{
            "url": "https://www.pexels.com/video/lima-peru-traffic-1234/",
            "user": {"name": "Autor"},
            "video_files": [{"file_type": "video/mp4", "width": 1280, "link": "https://videos.pexels.com/video-files/1234/clip.mp4"}],
        }]}
        with patch.object(multimedia, "PEXELS_API_KEY", "test-key"), patch("src.multimedia.requests.get") as get:
            get.return_value.json.return_value = payload
            video = multimedia.search_licensed_stock_video("Tráfico y transporte en Lima")
        self.assertEqual(get.call_args.args[0], "https://api.pexels.com/videos/search")
        self.assertEqual(video["source"], "pexels")

    def test_named_social_apps_override_generic_ai_stock_topic(self):
        title = "Meta presenta un modelo de inteligencia artificial para WhatsApp e Instagram"
        query, _ = multimedia._stock_topic(title)
        self.assertEqual(query, "instagram whatsapp smartphone")
        payload = {"videos": [{
            "url": "https://www.pexels.com/video/a-robotic-rover-moving-around-the-school-8566725/",
            "video_files": [{"file_type": "video/mp4", "width": 1280, "link": "https://videos.pexels.com/video-files/8566725/clip.mp4"}],
        }]}
        with patch.object(multimedia, "PEXELS_API_KEY", "test-key"), patch("src.multimedia.requests.get") as get:
            get.return_value.json.return_value = payload
            self.assertIsNone(multimedia.search_licensed_stock_video(title))
            self.assertEqual(get.call_args.kwargs["params"]["query"], query)

    def test_gadgets_headline_uses_electronics_stock_topic(self):
        query, _ = multimedia._stock_topic("Meta lanza Muse Gadgets para dispositivos de IA")
        self.assertEqual(query, "electronics circuit board")

    def test_stock_media_queries_follow_the_story_context(self):
        self.assertEqual(multimedia._stock_topic("Lima inaugura un nuevo hospital público")[0], "hospital healthcare")
        self.assertEqual(multimedia._stock_topic("Alianza Lima anuncia fichaje de futbolista")[0], "football stadium match")
        self.assertIsNone(multimedia._stock_topic("Partido político anuncia reforma tributaria"))
        self.assertEqual(multimedia._stock_topic("Candidatos a las elecciones de Arequipa")[0], "voting ballot election")
        self.assertEqual(multimedia._stock_topic("Mano Menezes habla tras derrota de Perú", "Deportes en Vivo")[0], "football stadium match")

    def test_youtube_video_must_match_the_named_opponent(self):
        title = "Mano Menezes hizo autocrítica tras derrota de Perú ante Canadá"
        payload = {"items": [
            {"id": {"videoId": "abcdefghijk"}, "snippet": {"title": "Mano Menezes habla tras derrota de Perú ante EEUU", "channelTitle": "A"}},
            {"id": {"videoId": "lmnopqrstuv"}, "snippet": {"title": "Mano Menezes habla tras derrota de Perú ante Canadá", "channelTitle": "B"}},
        ]}
        with patch.object(multimedia, "YOUTUBE_API_KEY", "test-key"), patch("src.multimedia.requests.get") as get:
            get.return_value.json.return_value = payload
            video = multimedia.search_relevant_youtube_video(title)
        self.assertEqual(video["canal"], "B")

    def test_sports_video_cannot_add_a_different_opponent(self):
        candidate = article()
        candidate["categoria"] = "Deportes en Vivo"
        candidate["titulo_fuente"] = "Perú vs Colombia: fecha del amistoso internacional"
        candidate["titulo_articulo"] = candidate["titulo_fuente"]
        candidate["video_titulo"] = "México vs Colombia: dónde ver el amistoso"
        self.assertIn("El video trata otro país o rival", publication_errors(candidate))
        self.assertIn("El video muestra un rival distinto al de la noticia", publication_errors(candidate))

    def test_election_photo_search_rejects_family_photos(self):
        photos = [{
            "alt": "Happy mother and son on a beach", "src": {"large": "https://images.pexels.com/family.jpg"},
            "photographer": "Autor", "url": "https://www.pexels.com/photo/family-123/",
        }, {
            "alt": "People voting at a polling station", "src": {"large": "https://images.pexels.com/vote.jpg"},
            "photographer": "Autor", "url": "https://www.pexels.com/photo/vote-456/",
        }]
        with patch.object(multimedia, "PEXELS_API_KEY", "test-key"), patch("src.multimedia.requests.get") as get:
            get.return_value.json.return_value = {"photos": photos}
            images = multimedia._search_pexels_licensed("Candidatos a las elecciones de Arequipa", 2)
        self.assertEqual([item["url"] for item in images], ["https://images.pexels.com/vote.jpg"])

    def test_cinema_school_is_not_ai_school(self):
        primary = {"titulo": "San Marcos aprueba escuela pública de cine y audiovisual", "url": "https://a.example/1", "fuente": "A"}
        candidates = [
            {"titulo": "San Marcos aprueba escuela profesional de inteligencia artificial", "url": "https://b.example/2", "fuente": "B"},
        ]
        self.assertEqual(select_corrob_sources(primary, candidates), [])
        self.assertEqual(multimedia._stock_topic(primary["titulo"])[0], "film camera production")

    def test_corrob_sources_excludes_unrelated_or_same_outlet(self):
        primary = {"titulo": "Cambio de transporte en Lima", "url": "https://a.example/1", "fuente": "A"}
        candidates = [
            {"titulo": "Lima anuncia cambio de transporte", "url": "https://b.example/2", "fuente": "B"},
            {"titulo": "Cambio de transporte en Lima", "url": "https://a.example/3", "fuente": "A"},
            {"titulo": "Receta de cocina", "url": "https://c.example/4", "fuente": "C"},
        ]
        self.assertEqual([item["fuente"] for item in select_corrob_sources(primary, candidates)], ["B"])

    def test_social_post_does_not_count_as_independent_reporting(self):
        self.assertTrue(social_source("https://www.facebook.com/newsroom/posts/123", "Facebook"))
        primary = {"titulo": "Ley seca por elecciones en Perú", "url": "https://medio.example/1", "fuente": "Medio"}
        posts = [{"titulo": "Ley seca por elecciones en Perú hoy - Facebook", "url": "https://news.google.com/rss/articles/x", "fuente": "Facebook"}]
        self.assertEqual(select_corrob_sources(primary, posts), [])

    def test_same_syndicated_headline_is_not_independent_corroboration(self):
        primary = {"titulo": "Premios Ariel celebran diversidad del cine - Medio A", "url": "https://a.example/1", "fuente": "A"}
        candidates = [{"titulo": "Premios Ariel celebran diversidad del cine - Medio B", "url": "https://b.example/2", "fuente": "B"}]
        self.assertEqual(select_corrob_sources(primary, candidates), [])

    def test_syndicated_body_with_new_title_is_detected(self):
        dispatch = "La academia anunció apoyos para producciones independientes y entregó premios en la ceremonia. " * 12
        self.assertTrue(near_duplicate_text(dispatch, "Publicidad y navegación. " + dispatch + "Más noticias."))
        self.assertFalse(near_duplicate_text(dispatch, "El municipio confirmó nuevas rutas de autobuses para Lima. " * 12))

    def test_named_product_does_not_mix_gadgets_with_image_generator(self):
        primary = {"titulo": "Meta lanza Muse Gadgets y un SDK para dispositivos", "url": "https://a.example/1", "fuente": "A"}
        candidates = [
            {"titulo": "Meta Muse ofrece SDK para hardware", "url": "https://b.example/2", "fuente": "B"},
            {"titulo": "Meta Muse lanza generador de imágenes", "url": "https://c.example/3", "fuente": "C"},
        ]
        self.assertEqual([item["fuente"] for item in select_corrob_sources(primary, candidates)], ["B"])
        self.assertFalse(matches_story_aspect(primary["titulo"], "Muse genera imágenes en Instagram"))

    def test_rank_news_excludes_traffic_traps(self):
        items = [
            {"titulo": "Ver partido EN VIVO GRATIS", "fuente": "A"},
            {"titulo": "Municipio anuncia cambios de transporte en Lima", "fuente": "B"},
        ]
        self.assertEqual([item["fuente"] for item in rank_news(items)], ["B"])

    def test_crawler_refuses_private_urls(self):
        self.assertFalse(_public_url("http://127.0.0.1/admin"))
        self.assertFalse(_public_url("http://192.168.1.2/secret"))
        self.assertFalse(_public_url("file:///etc/passwd"))
        self.assertTrue(_public_url("https://example.com/news"))
        self.assertFalse(_public_dns("http://127.0.0.1/admin"))

    def test_google_news_decoder_uses_current_success_field(self):
        with patch("src.crawler.gnewsdecoder", return_value={"success": True, "decoded_url": "https://example.com/article"}):
            self.assertEqual(decode_google_news_url("https://news.google.com/rss/articles/test"), "https://example.com/article")

    def test_builder_renders_only_verified_articles(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "output" / "2026-10-03" / "Noticias"
            public = Path(temp) / "public"
            output.mkdir(parents=True)
            good = article()
            good["imagenes"] = good["imagenes"][:1]
            output.joinpath("good.json").write_text(json.dumps(good), encoding="utf-8")
            legacy = article()
            legacy["schema_version"] = 1
            output.joinpath("legacy.json").write_text(json.dumps(legacy), encoding="utf-8")
            original = (builder.OUTPUT_DIR, builder.PUBLIC_DIR, builder.SITE_URL)
            builder.OUTPUT_DIR, builder.PUBLIC_DIR, builder.SITE_URL = str(output.parent.parent), str(public), "https://example.org"
            try:
                builder.build_site()
            finally:
                builder.OUTPUT_DIR, builder.PUBLIC_DIR, builder.SITE_URL = original
            search = json.loads(public.joinpath("search.json").read_text(encoding="utf-8"))
            self.assertEqual(len(search), 1)
            page = public.joinpath(search[0]["slug"] + ".html").read_text(encoding="utf-8")
            self.assertIn("Pexels License", page)
            self.assertIn("Medio B", page)
            self.assertIn("youtube.com/embed/abcdefghijk", page)
            self.assertIn("NewsArticle", page)
            self.assertIn('href="#fuentes"', page)
            category_page = public.joinpath("categoria-noticias-de-ultima-hora-y-politica.html").read_text(encoding="utf-8")
            self.assertIn('href="https://example.org/categoria-noticias-de-ultima-hora-y-politica.html"', category_page)
            self.assertIn('href="#peru"', category_page)
            self.assertIn('href="#mundo"', category_page)
            home = public.joinpath("index.html").read_text(encoding="utf-8")
            self.assertIn('class="regional-grid"', home)
            self.assertIn("Ilustración de archivo", home)
            ElementTree.fromstring(public.joinpath("sitemap.xml").read_text(encoding="utf-8"))
            ElementTree.fromstring(public.joinpath("news-sitemap.xml").read_text(encoding="utf-8"))

    def test_auto_publisher_persists_articles_across_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            drafts = Path(temp) / "drafts"
            published = Path(temp) / "published"
            public = Path(temp) / "website" / "public"
            drafts.mkdir()
            public.mkdir(parents=True)
            (public / "css").mkdir()
            (public / "css" / "style.css").write_text("body{}", encoding="utf-8")
            (public / "favicon.svg").write_text("<svg/>", encoding="utf-8")
            (drafts / "first.json").write_text(json.dumps(article()), encoding="utf-8")
            self.assertEqual(publish(drafts, published, public), 1)
            self.assertFalse((drafts / "first.json").exists())
            self.assertEqual(len(list(published.rglob("*.json"))), 1)
            self.assertEqual(len(json.loads((public / "search.json").read_text(encoding="utf-8"))), 1)

            second = article()
            second["titulo_articulo"] = "Segundo cambio del transporte en Lima"
            second["fuentes"][0]["url"] = "https://example.com/b"
            second.update({
                "video_source": "pexels",
                "video_url": "https://videos.pexels.com/video-files/123/clip.mp4",
                "video_origen": "https://www.pexels.com/video/123/",
                "video_licencia": "Pexels License",
                "video_licencia_url": "https://www.pexels.com/license/",
            })
            (drafts / "second.json").write_text(json.dumps(second), encoding="utf-8")
            self.assertEqual(publish(drafts, published, public), 1)
            search = json.loads((public / "search.json").read_text(encoding="utf-8"))
            self.assertEqual(len(search), 2)
            stock_item = next(item for item in search if item["title"] == second["titulo_articulo"])
            page = (public / (stock_item["slug"] + ".html")).read_text(encoding="utf-8")
            self.assertIn("<video controls", page)
            self.assertIn("Pexels License", page)
            self.assertTrue((public / "css" / "style.css").exists())
            self.assertTrue((public / "favicon.svg").exists())


if __name__ == "__main__":
    unittest.main()
