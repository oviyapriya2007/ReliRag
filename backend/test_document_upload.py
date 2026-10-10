"""RELI-RAG Day 2: POST /documents/upload response metadata.

Usage (from the project root or backend/):
    python backend/test_document_upload.py

Offline: ingestion (PDF parsing and embedding) is mocked, and the app runs against an
in-memory SQLite database, so the real database is never touched.
Exits with status 0 when all tests pass, 1 otherwise.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Must be set before `app` is imported so the app never connects to the real database.
os.environ["DATABASE_URL"] = "sqlite://"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Document  # noqa: E402

PDF_BYTES = b"%PDF-1.4\n% test\n"


def fake_ingest(total_chunks: int):
    def ingest(db, document, _data):
        document.total_pages = 3
        document.total_chunks = total_chunks
        db.commit()
        db.refresh(document)
        return document

    return ingest


class DocumentUploadTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.addCleanup(app.dependency_overrides.clear)
        self.addCleanup(engine.dispose)
        self.client = TestClient(app)

    def upload(self, total_chunks: int):
        with patch("app.routers.documents.ingest_document", side_effect=fake_ingest(total_chunks)):
            return self.client.post(
                "/documents/upload",
                files={"file": ("notes.pdf", PDF_BYTES, "application/pdf")},
            )

    def test_upload_returns_stored_uploaded_at(self):
        response = self.upload(total_chunks=5)
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()

        self.assertEqual(body["filename"], "notes.pdf")
        self.assertEqual(body["total_pages"], 3)
        self.assertEqual(body["total_chunks"], 5)
        self.assertTrue(body.get("uploaded_at"), body)

        listed = self.client.get("/documents").json()
        self.assertEqual(listed, [body])

    def test_upload_without_text_is_rejected_and_discarded(self):
        response = self.upload(total_chunks=0)
        self.assertEqual(response.status_code, 422, response.text)

        with self.Session() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Document)), 0)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
