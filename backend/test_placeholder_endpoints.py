"""RELI-RAG: no endpoint is left as an HTTP 501 placeholder.

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

# Former placeholders replaced by GET /evaluations and GET /evaluations/export.csv.
REMOVED = (("POST", "/evaluations", 405), ("GET", "/evaluations/1", 404))


class PlaceholderEndpointsTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_no_route_documents_501(self):
        for path, operations in self.client.get("/openapi.json").json()["paths"].items():
            for method, operation in operations.items():
                with self.subTest(method=method, path=path):
                    self.assertNotIn("501", operation["responses"])

    def test_removed_placeholders_are_gone(self):
        for method, path, expected in REMOVED:
            with self.subTest(method=method, path=path):
                self.assertEqual(self.client.request(method, path).status_code, expected)

    def test_health_still_ok(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
