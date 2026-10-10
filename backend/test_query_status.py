"""RELI-RAG Day 2: status handling for POST /query and GET /query/{id}.

Usage (from the project root or backend/):
    python backend/test_query_status.py

Offline: retrieval and Claude are mocked, and the app runs against an in-memory SQLite
database, so no Claude API calls are made and the real database is never touched.
Exits with status 0 when all tests pass, 1 otherwise.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Must be set before `app` is imported so the app never connects to the real database.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SIMILARITY_GATE"] = "0.30"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Answer, Document, DocumentChunk, Query  # noqa: E402
from app.routers.query import GATE_FAILED_MESSAGE, NOT_SUPPORTED_MESSAGE  # noqa: E402
from app.services.generator import ANSWERED  # noqa: E402
from app.services.llm import LLMResult  # noqa: E402
from app.services.retrieval import RetrievedChunk  # noqa: E402
from app.services.similarity_gate import INSUFFICIENT_EVIDENCE  # noqa: E402

MODEL = "claude-test-model"


def llm_result(text: str) -> LLMResult:
    return LLMResult(
        text=text, model=MODEL, input_tokens=100, output_tokens=20,
        latency_ms=5, stop_reason="end_turn", attempts=1,
    )


class QueryStatusTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

        with self.Session() as db:
            document = Document(filename="benchmark.pdf", total_pages=1, total_chunks=1)
            chunk = DocumentChunk(
                document=document, page_number=4, chunk_index=0,
                content="TCP provides a reliable, ordered byte stream.",
            )
            db.add_all([document, chunk])
            db.commit()
            self.chunk_id, self.document_id = chunk.id, document.id

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

    def retrieved(self, similarity: float) -> list[RetrievedChunk]:
        return [RetrievedChunk(
            chunk_id=self.chunk_id, document_id=self.document_id, document="benchmark.pdf",
            page=4, text="TCP provides a reliable, ordered byte stream.", similarity=similarity,
        )]

    def post_query(self, similarity: float, claude_text: str | None = None):
        """POST /query with mocked retrieval and Claude; returns (response JSON, Claude mock)."""
        with patch("app.services.similarity_gate.retrieve", return_value=self.retrieved(similarity)), \
             patch("app.services.generator.call_claude") as claude:
            if claude_text is not None:
                claude.return_value = llm_result(claude_text)
            response = self.client.post(
                "/query", json={"question": "What is TCP?", "document_ids": [self.document_id]}
            )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), claude

    def assert_status_consistent(self, body: dict, expected: str) -> None:
        """Response, GET /query/{id}, and saved query/answer rows all report `expected`."""
        self.assertEqual(body["status"], expected)
        self.assertEqual(body["attempts"][0]["status"], expected)

        fetched = self.client.get(f"/query/{body['query_id']}")
        self.assertEqual(fetched.status_code, 200, fetched.text)
        self.assertEqual(fetched.json(), body)

        with self.Session() as db:
            query = db.get(Query, body["query_id"])
            answers = db.scalars(select(Answer).where(Answer.query_id == query.id)).all()
            self.assertEqual(query.final_status, expected)
            self.assertEqual([a.status for a in answers], [expected])

    def test_normal_answer_is_answered(self):
        text = "TCP provides a reliable, ordered byte stream [1]."
        body, claude = self.post_query(0.9, text)

        claude.assert_called_once()
        self.assert_status_consistent(body, ANSWERED)
        self.assertEqual(body["final_answer"], text)
        attempt = body["attempts"][0]
        self.assertEqual(attempt["answer"], text)
        self.assertEqual(attempt["citations"], [1])
        self.assertEqual(attempt["model"], MODEL)

    def test_claude_refusal_is_insufficient_evidence(self):
        refusals = [
            "INSUFFICIENT_EVIDENCE",
            "INSUFFICIENT_EVIDENCE\n\nThe passages do not mention any Wi-Fi password.",
            "INSUFFICIENT_EVIDENCE. Passage [1] covers TCP but not the question asked.",
            "**INSUFFICIENT_EVIDENCE**",
        ]
        for text in refusals:
            with self.subTest(claude_text=text):
                body, claude = self.post_query(0.9, text)

                claude.assert_called_once()
                self.assert_status_consistent(body, INSUFFICIENT_EVIDENCE)
                self.assertEqual(body["final_answer"], NOT_SUPPORTED_MESSAGE)
                attempt = body["attempts"][0]
                self.assertIsNone(attempt["answer"])
                self.assertEqual(attempt["citations"], [])
                self.assertEqual(attempt["model"], MODEL)
                self.assertEqual(len(attempt["retrieval"]), 1)

    def test_similarity_gate_rejection_skips_claude(self):
        body, claude = self.post_query(0.05)

        claude.assert_not_called()
        self.assert_status_consistent(body, INSUFFICIENT_EVIDENCE)
        self.assertEqual(body["final_answer"], GATE_FAILED_MESSAGE)
        attempt = body["attempts"][0]
        self.assertIsNone(attempt["answer"])
        self.assertIsNone(attempt["model"])
        self.assertEqual(attempt["citations"], [])
        self.assertEqual(len(attempt["retrieval"]), 1)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
