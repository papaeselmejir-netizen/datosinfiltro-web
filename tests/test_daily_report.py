import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from types import SimpleNamespace
from zoneinfo import ZoneInfo

with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only"}):
    from main import CATEGORIAS_ACTIVAS, save_daily_editorial_report
    from src.writer import PrimaryAnnouncementOutput, verify_primary_announcement
    from publish_verified import record_daily_publications


class DailyReportTests(unittest.TestCase):
    def test_primary_source_cannot_override_a_claim_needing_corrob(self):
        answer = PrimaryAnnouncementOutput(
            eligible=True,
            claims_requiring_independent_source=["La medida redujo los contagios"],
            reason="Falta evidencia externa",
        )
        with patch("src.writer.client.models.generate_content", return_value=SimpleNamespace(parsed=answer)):
            self.assertFalse(verify_primary_announcement({"titulo_articulo": "Nueva medida"}, "Comunicado oficial"))

    def test_daily_report_merges_runs_and_retries_once(self):
        category = CATEGORIAS_ACTIVAS[0]
        first = {category: {
            "investigadas": 3, "borradores_verificados": 0,
            "candidatas_peru": 4, "candidatas_mundo": 2,
            "rechazos": {"Perú": {"sin_video_relacionado": 2}},
        }}
        second = {category: {
            "investigadas": 2, "borradores_verificados": 1,
            "candidatas_peru": 3, "candidatas_mundo": 2,
            "rechazos": {"Mundial": {"sin_imagen_con_licencia": 1}},
        }}
        with tempfile.TemporaryDirectory() as directory:
            save_daily_editorial_report(first, "2026-10-09T06:00:00-05:00", "2026-10-09T07:00:00-05:00", directory, "run-1")
            report = save_daily_editorial_report(second, "2026-10-09T12:00:00-05:00", "2026-10-09T13:00:00-05:00", directory, "run-2")
            report = save_daily_editorial_report(second, "2026-10-09T12:00:00-05:00", "2026-10-09T13:00:00-05:00", directory, "run-2")
            with open(os.path.join(directory, "2026-10-09.json"), encoding="utf-8") as file:
                saved = json.load(file)
        self.assertEqual(report, saved)
        self.assertEqual(len(saved["runs"]), 2)
        self.assertEqual(saved["categories"][category]["investigadas"], 5)
        self.assertEqual(saved["categories"][category]["borradores_verificados"], 1)
        self.assertEqual(saved["categories"][category]["bloqueo_principal"], "sin_video_relacionado")
        self.assertEqual(len(saved["categories"]), len(CATEGORIAS_ACTIVAS))

    def test_actual_publications_are_counted_after_the_site_swap(self):
        category = CATEGORIAS_ACTIVAS[0]
        now = datetime.now(ZoneInfo("America/Lima")).isoformat(timespec="seconds")
        result = {category: {
            "investigadas": 1, "borradores_verificados": 1,
            "candidatas_peru": 1, "candidatas_mundo": 0, "rechazos": {},
        }}
        with tempfile.TemporaryDirectory() as directory:
            save_daily_editorial_report(result, now, now, directory, "run-1")
            record_daily_publications([{"categoria": category}], directory, "run-1")
            record_daily_publications([{"categoria": category}], directory, "run-1")
            with open(os.path.join(directory, now[:10] + ".json"), encoding="utf-8") as file:
                report = json.load(file)
        self.assertEqual(report["categories"][category]["publicadas"], 1)


if __name__ == "__main__":
    unittest.main()
