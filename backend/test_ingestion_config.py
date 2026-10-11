"""RELI-RAG: configurable ingestion settings (chunking and embedding).

Usage (from the project root or backend/):
    python backend/test_ingestion_config.py

Offline: the embedding model is faked and the app runs against an in-memory SQLite database,
so no model download, PDF, or real database is needed.
Exits with status 0 when all tests pass, 1 otherwise.
"""

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Must be set before `app` is imported so the app never connects to the real database.
os.environ["DATABASE_URL"] = "sqlite://"
# Pin the ingestion settings so a local .env cannot change the expected results.
INGESTION_ENV = {
    "CHUNK_SIZE": "800",
    "CHUNK_OVERLAP": "150",
    "EMBEDDING_MODEL": "all-MiniLM-L6-v2",
    "EMBEDDING_BATCH_SIZE": "32",
}
os.environ.update(INGESTION_ENV)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pydantic import ValidationError  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import Settings, settings  # noqa: E402
from app.db import Base  # noqa: E402
from app.models import EMBEDDING_DIM, Document, DocumentChunk  # noqa: E402
from app.services import ingestion  # noqa: E402
from app.services.ingestion import PageText  # noqa: E402


def fake_model() -> MagicMock:
    """A SentenceTransformer stand-in returning one EMBEDDING_DIM vector per text."""
    model = MagicMock()
    model.encode.side_effect = lambda texts, **_: SimpleNamespace(
        tolist=lambda: [[0.5] * EMBEDDING_DIM for _ in texts]
    )
    return model


class IngestionSettingsTest(unittest.TestCase):
    def load(self, **env):
        """Settings from the process environment plus `env`, ignoring any .env file."""
        base = {k: v for k, v in os.environ.items() if k not in INGESTION_ENV}
        with patch.dict(os.environ, {**base, **env}, clear=True):
            return Settings(_env_file=None)

    def test_defaults_match_previous_constants(self):
        loaded = self.load()
        self.assertEqual(loaded.chunk_size, 800)
        self.assertEqual(loaded.chunk_overlap, 150)
        self.assertEqual(loaded.embedding_model, "all-MiniLM-L6-v2")
        self.assertEqual(loaded.embedding_batch_size, 32)

    def test_environment_overrides(self):
        loaded = self.load(CHUNK_SIZE="500", CHUNK_OVERLAP="0", EMBEDDING_MODEL=" other-model ",
                           EMBEDDING_BATCH_SIZE="8")
        self.assertEqual(loaded.chunk_size, 500)
        self.assertEqual(loaded.chunk_overlap, 0)
        self.assertEqual(loaded.embedding_model, "other-model")
        self.assertEqual(loaded.embedding_batch_size, 8)

    def test_invalid_values_are_rejected(self):
        cases = {
            "zero chunk size": {"CHUNK_SIZE": "0"},
            "negative chunk size": {"CHUNK_SIZE": "-1"},
            "negative overlap": {"CHUNK_OVERLAP": "-1"},
            "overlap equal to size": {"CHUNK_SIZE": "200", "CHUNK_OVERLAP": "200"},
            "overlap larger than size": {"CHUNK_SIZE": "100"},
            "zero batch size": {"EMBEDDING_BATCH_SIZE": "0"},
            "empty model": {"EMBEDDING_MODEL": ""},
            "blank model": {"EMBEDDING_MODEL": "   "},
        }
        for name, env in cases.items():
            with self.subTest(name), self.assertRaises(ValidationError):
                self.load(**env)


class IngestionUsesSettingsTest(unittest.TestCase):
    def test_default_chunking_is_unchanged(self):
        pieces = ingestion.split_text("x" * 2000)
        self.assertEqual([len(p) for p in pieces], [800, 800, 700])

    def test_configured_chunking(self):
        text = "abcdefghijklmnopqrstuvwxy"
        with patch.object(settings, "chunk_size", 10), patch.object(settings, "chunk_overlap", 2):
            pieces = ingestion.split_text(text)
            chunks = ingestion.chunk_pages([PageText(1, text), PageText(2, "short")])
        self.assertEqual(pieces, ["abcdefghij", "ijklmnopqr", "qrstuvwxy"])
        self.assertEqual([(c.page_number, c.chunk_index, c.content) for c in chunks],
                         [(1, 0, "abcdefghij"), (1, 1, "ijklmnopqr"), (1, 2, "qrstuvwxy"),
                          (2, 3, "short")])

    def test_explicit_split_arguments_override_settings(self):
        with patch.object(settings, "chunk_size", 10), patch.object(settings, "chunk_overlap", 2):
            self.assertEqual(ingestion.split_text("abcdef", size=4, overlap=1), ["abcd", "def"])
        with self.assertRaisesRegex(ValueError, "overlap must be smaller than size"):
            ingestion.split_text("abcdef", size=4, overlap=4)

    def test_embedding_uses_configured_batch_size(self):
        model = fake_model()
        with patch.object(settings, "embedding_batch_size", 7), \
             patch.object(ingestion, "get_embedding_model", return_value=model):
            vectors = ingestion.embed_texts(["a", "b"])
        self.assertEqual(len(vectors), 2)
        self.assertEqual(model.encode.call_args.kwargs["batch_size"], 7)
        self.assertTrue(model.encode.call_args.kwargs["normalize_embeddings"])

    def test_embedding_model_loads_configured_name(self):
        constructor = MagicMock()
        ingestion.get_embedding_model.cache_clear()
        self.addCleanup(ingestion.get_embedding_model.cache_clear)
        fake_module = SimpleNamespace(SentenceTransformer=constructor)
        with patch.dict(sys.modules, {"sentence_transformers": fake_module}):
            ingestion.get_embedding_model()
            constructor.assert_called_once_with("all-MiniLM-L6-v2")

            ingestion.get_embedding_model.cache_clear()
            with patch.object(settings, "embedding_model", "custom-model"):
                ingestion.get_embedding_model()
            constructor.assert_called_with("custom-model")

    def test_ingest_document_uses_configured_settings(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                               poolclass=StaticPool)
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

        model = fake_model()
        pages = [PageText(1, "a" * 25), PageText(3, "b" * 8)]
        with Session() as db, \
             patch.object(settings, "chunk_size", 10), \
             patch.object(settings, "chunk_overlap", 2), \
             patch.object(settings, "embedding_batch_size", 4), \
             patch.object(ingestion, "extract_pages", return_value=(3, pages)), \
             patch.object(ingestion, "get_embedding_model", return_value=model):
            document = Document(filename="notes.pdf")
            db.add(document)
            db.commit()
            ingestion.ingest_document(db, document, b"%PDF-")

            stored = db.scalars(select(DocumentChunk).order_by(DocumentChunk.chunk_index)).all()
            self.assertEqual((document.total_pages, document.total_chunks), (3, 4))
            self.assertEqual([(c.page_number, len(c.content)) for c in stored],
                             [(1, 10), (1, 10), (1, 9), (3, 8)])
            self.assertTrue(all(len(c.embedding) == EMBEDDING_DIM for c in stored))
        self.assertEqual(model.encode.call_args.kwargs["batch_size"], 4)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
