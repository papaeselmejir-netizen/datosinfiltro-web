import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from src.editorial import publication_errors, rank_news, select_corrob_sources, matches_story_aspect
from src.crawler import _public_url, _public_dns, decode_google_news_url
from website import builder
from publish_verified import publish
from src import multimedia


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

    def test_corrob_sources_excludes_unrelated_or_same_outlet(self):
        primary = {"titulo": "Cambio de transporte en Lima", "url": "https://a.example/1", "fuente": "A"}
        candidates = [
            {"titulo": "Cambio de transporte en Lima", "url": "https://b.example/2", "fuente": "B"},
            {"titulo": "Cambio de transporte en Lima", "url": "https://a.example/3", "fuente": "A"},
            {"titulo": "Receta de cocina", "url": "https://c.example/4", "fuente": "C"},
        ]
        self.assertEqual([item["fuente"] for item in select_corrob_sources(primary, candidates)], ["B"])

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
