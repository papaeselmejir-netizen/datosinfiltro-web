import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from src.editorial import publication_errors, rank_news, select_corrob_sources, matches_story_aspect, near_duplicate_text
from src.crawler import _public_url, _public_dns, decode_google_news_url
from website import builder
from publish_verified import publish
from src import multimedia, extractor


def article():
    return {
        "schema_version": 2,
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
        ) as google_search:
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
        with patch.object(extractor, "extract_news_google_rss", return_value=world):
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
        with patch.object(extractor, "extract_news_google_rss", return_value=items):
            news = extractor.extract_news_multi_source("Salud, Bienestar y Estilo de Vida", max_items=3, geo="PE")
        self.assertEqual([item["fuente"] for item in news], ["C"])

    def test_editorial_gate_requires_media_and_sources(self):
        candidate = article()
        self.assertEqual(publication_errors(candidate), [])
        candidate["video_url"] = "https://untrusted.example/embed/abcdefghijk"
        candidate["imagenes"][0]["licencia"] = ""
        self.assertEqual(len(publication_errors(candidate)), 2)

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
            output.joinpath("good.json").write_text(json.dumps(article()), encoding="utf-8")
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
