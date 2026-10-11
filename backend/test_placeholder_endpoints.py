"""RELI-RAG: unimplemented endpoints answer 501 instead of returning fake data.

Usage (from the project root or backend/):
    python backend/test_placeholder_endpoints.py

Offline: no database, embedding, or Claude call is used.
Exits with status 0 when all tests pass, 1 otherwise.
"""

import os
import sys
import unittest
from pathlib import Path

# Must be set before `app` is imported so the app never connects to the real database.
os.environ["DATABASE_URL"] = "sqlite://"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.routers import analytics, compare, evaluations  # noqa: E402

PLACEHOLDERS = (
    ("POST", "/evaluations", evaluations.NOT_IMPLEMENTED_DETAIL),
    ("GET", "/evaluations", evaluations.NOT_IMPLEMENTED_DETAIL),
    ("GET", "/evaluations/1", evaluations.NOT_IMPLEMENTED_DETAIL),
    ("GET", "/analytics/summary", analytics.NOT_IMPLEMENTED_DETAIL),
    ("POST", "/compare", compare.NOT_IMPLEMENTED_DETAIL),
)


class PlaceholderEndpointsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_placeholders_return_501_without_data(self):
        for method, path, detail in PLACEHOLDERS:
            with self.subTest(method=method, path=path):
                response = self.client.request(method, path)
                self.assertEqual(response.status_code, 501, response.text)
                self.assertEqual(response.json(), {"detail": detail})

    def test_placeholders_document_501_in_openapi(self):
        paths = self.client.get("/openapi.json").json()["paths"]
        for method, path, _ in PLACEHOLDERS:
            path = path.replace("/evaluations/1", "/evaluations/{evaluation_id}")
            with self.subTest(method=method, path=path):
                self.assertIn("501", paths[path][method.lower()]["responses"])

    def test_health_still_ok(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
