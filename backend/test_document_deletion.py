"""RELI-RAG: offline tests for deleting documents (M1): soft deletion of documents that past
answer attempts used, permanent deletion of unused ones, and intact history either way.

Usage (from the project root or backend/):
    python backend/test_document_deletion.py

Offline: retrieval and Claude are mocked, and the app runs against an in-memory SQLite database
with foreign keys enforced, so deletes cascade as PostgreSQL's ON DELETE rules do. No API calls
are made and the real database is never touched. Exits with status 0 when all tests pass.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Must be set before `app` is imported so the app never connects to the real database.
os.environ["DATABASE_URL"] = "sqlite://"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event, func, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Claim,
    Document,
    DocumentChunk,
    Evaluation,
    RetrievalLog,
)
from app.services.evaluator import SUPPORTED  # noqa: E402
from app.services.llm import LLMResult  # noqa: E402
from app.services.retrieval import RetrievedChunk, load_logged_chunks  # noqa: E402

MODEL = "claude-test-model"
TEXTS = {
    "a0": "Policy 1. Item A requires written approval from a manager.",
    "a1": "Policy 2. Item A approvals are valid for twelve months.",
    "b0": "Policy 3. Item B is available to every member.",
}
ANSWER = ("Item A requires written approval from a manager [1]. Item B is available to every "
          "member [2]. Item A approvals are valid for twelve months [3].")


def llm_result(text: str) -> LLMResult:
    return LLMResult(text=text, model=MODEL, input_tokens=100, output_tokens=20, latency_ms=5,
                     stop_reason="end_turn", attempts=1)


class DocumentDeletionTest(unittest.TestCase):
    def setUp(self):
        for name, value in {"claude_model": MODEL, "similarity_gate": 0.30,
                            "evaluator_model": None, "evaluator_pass_threshold": 0.80,
                            "evaluator_max_parse_attempts": 2}.items():
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                               poolclass=StaticPool)

        @event.listens_for(engine, "connect")
        def _enforce_foreign_keys(dbapi_connection, _):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        self.Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

        with self.Session() as db:
            doc_a = Document(filename="a.pdf", total_pages=2, total_chunks=2)
            doc_b = Document(filename="b.pdf", total_pages=1, total_chunks=1)
            unused = Document(filename="unused.pdf", total_pages=1, total_chunks=1)
            chunks = {
                "a0": DocumentChunk(document=doc_a, page_number=1, chunk_index=0,
                                    content=TEXTS["a0"]),
                "a1": DocumentChunk(document=doc_a, page_number=2, chunk_index=1,
                                    content=TEXTS["a1"]),
                "b0": DocumentChunk(document=doc_b, page_number=1, chunk_index=0,
                                    content=TEXTS["b0"]),
                "u0": DocumentChunk(document=unused, page_number=1, chunk_index=0,
                                    content="Policy 9. Unused."),
            }
            db.add_all([doc_a, doc_b, unused, *chunks.values()])
            db.commit()
            self.docs = {"a": doc_a.id, "b": doc_b.id, "unused": unused.id}
            self.chunks = {key: (c.id, c.document_id) for key, c in chunks.items()}

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def retrieved(self, key: str, rank: int) -> RetrievedChunk:
        chunk_id, document_id = self.chunks[key]
        return RetrievedChunk(chunk_id=chunk_id, document_id=document_id,
                              document=f"{key[0]}.pdf", page=1, text=TEXTS[key],
                              similarity=0.9 - 0.01 * rank)

    def evaluation(self) -> str:
        claims = []
        for key in ("a0", "b0", "a1"):
            fact = TEXTS[key].split(". ", 1)[1]
            claims.append({"claim_text": fact, "verdict": SUPPORTED,
                           "evidence_chunk_id": self.chunks[key][0],
                           "evidence_quote": fact.rstrip(".")})
        return json.dumps({"claims": claims, "answer_relevance": 0.95, "context_relevance": 0.9,
                           "feedback": "Checked."})

    def ask(self) -> dict:
        retrieved = [self.retrieved("a0", 1), self.retrieved("b0", 2), self.retrieved("a1", 3)]
        with patch("app.services.similarity_gate.retrieve", return_value=retrieved), \
             patch("app.services.generator.call_claude", return_value=llm_result(ANSWER)), \
             patch("app.services.evaluator.call_claude",
                   return_value=llm_result(self.evaluation())):
            response = self.client.post("/query", json={"question": "What applies to items?"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_history_before_deletion_is_unchanged(self):
        body = self.ask()
        attempt = body["attempts"][0]

        self.assertEqual([r["rank"] for r in attempt["retrieval"]], [1, 2, 3])
        self.assertEqual(attempt["citations"], [1, 2, 3])
        self.assertTrue(attempt["evaluation"]["passed"])
        self.assertEqual(self.client.get(f"/query/{body['query_id']}").json(), body)

    def counts(self) -> dict[str, int]:
        with self.Session() as db:
            return {model.__name__: db.scalar(select(func.count()).select_from(model))
                    for model in (Document, DocumentChunk, RetrievalLog, Evaluation, Claim)}

    def listed_documents(self) -> list[str]:
        return sorted(d["filename"] for d in self.client.get("/documents").json())

    def test_retrieved_document_is_soft_deleted_and_history_is_unchanged(self):
        body = self.ask()
        before = self.counts()

        response = self.client.delete(f"/documents/{self.docs['a']}")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {
            "id": self.docs["a"], "filename": "a.pdf", "deleted": True,
            "message": "Deleted document 'a.pdf'. Its 2 chunks are kept, hidden from search, "
                       "for the history of 1 past answer attempt(s).",
        })
        self.assertEqual(self.listed_documents(), ["b.pdf", "unused.pdf"])
        # Nothing is deleted: the row stays (marked deleted), with its chunks and their history.
        self.assertEqual(self.counts(), before)
        with self.Session() as db:
            self.assertIsNotNone(db.get(Document, self.docs["a"]).deleted_at)
            self.assertIsNone(db.get(Document, self.docs["b"]).deleted_at)
        # The whole stored query (retrieval, citations, claims and their evidence) is unchanged.
        self.assertEqual(self.client.get(f"/query/{body['query_id']}").json(), body)

    def test_evaluation_history_and_analytics_are_unchanged_by_soft_deletion(self):
        self.ask()
        listing = self.client.get("/evaluations").json()
        export = self.client.get("/evaluations/export.csv").text
        summary = self.client.get("/analytics/summary").json()

        for key in ("a", "b"):
            self.assertEqual(self.client.delete(f"/documents/{self.docs[key]}").status_code, 200)

        self.assertEqual(self.client.get("/evaluations").json(), listing)
        self.assertEqual([d["filename"] for d in listing["items"][0]["documents"]],
                         ["a.pdf", "b.pdf"])
        self.assertEqual(self.client.get("/evaluations/export.csv").text, export)
        self.assertEqual(self.client.get("/analytics/summary").json(), summary)
        self.assertEqual(self.listed_documents(), ["unused.pdf"])

    def test_repeated_deletion_returns_404(self):
        self.ask()
        for key in ("a", "unused"):
            with self.subTest(document=key):
                self.assertEqual(self.client.delete(f"/documents/{self.docs[key]}").status_code,
                                 200)
                repeat = self.client.delete(f"/documents/{self.docs[key]}")
                self.assertEqual(repeat.status_code, 404, repeat.text)
                self.assertEqual(repeat.json()["detail"], f"Document {self.docs[key]} not found.")

    def test_unused_document_is_deleted_permanently(self):
        self.ask()
        before = self.counts()
        response = self.client.delete(f"/documents/{self.docs['unused']}")

        self.assertEqual(response.json(), {
            "id": self.docs["unused"], "filename": "unused.pdf", "deleted": True,
            "message": "Deleted document 'unused.pdf' and 1 chunks.",
        })
        after = self.counts()
        self.assertEqual((after["Document"], after["DocumentChunk"]),
                         (before["Document"] - 1, before["DocumentChunk"] - 1))
        self.assertEqual({k: after[k] for k in ("RetrievalLog", "Evaluation", "Claim")},
                         {k: before[k] for k in ("RetrievalLog", "Evaluation", "Claim")})
        with self.Session() as db:
            self.assertIsNone(db.get(Document, self.docs["unused"]))

    def test_document_cited_only_by_a_claim_is_kept(self):
        body = self.ask()
        with self.Session() as db:
            claim = db.scalars(select(Claim).limit(1)).one()
            claim.evidence_chunk_id = self.chunks["u0"][0]
            db.commit()

        response = self.client.delete(f"/documents/{self.docs['unused']}")

        self.assertIn("kept, hidden from search", response.json()["message"])
        with self.Session() as db:
            self.assertIsNotNone(db.get(Document, self.docs["unused"]))
        claims = self.client.get(f"/query/{body['query_id']}").json()["attempts"][0][
            "evaluation"]["claims"]
        self.assertIn(self.chunks["u0"][0], [c["evidence_chunk_id"] for c in claims])

    def test_logged_chunks_of_soft_deleted_documents_can_be_replayed(self):
        self.ask()
        self.client.delete(f"/documents/{self.docs['a']}")
        with self.Session() as db:
            answer_id = db.scalar(select(RetrievalLog.answer_id).limit(1))
            replayed = load_logged_chunks(db, answer_id)
        self.assertEqual([c.chunk_id for c in replayed],
                         [self.chunks[key][0] for key in ("a0", "b0", "a1")])

    def test_rank_gaps_in_older_history_keep_citations_aligned(self):
        # History whose retrieval log lost rows (e.g. a document deleted before soft deletion).
        body = self.ask()
        with self.Session() as db:
            log = db.scalars(select(RetrievalLog).where(RetrievalLog.rank == 1)).one()
            db.delete(log)
            db.commit()

        attempt = self.client.get(f"/query/{body['query_id']}").json()["attempts"][0]
        # Citation [1] is dropped; [2] and [3] still point at the passages logged at those ranks.
        self.assertEqual([r["rank"] for r in attempt["retrieval"]], [2, 3])
        self.assertEqual(attempt["citations"], [2, 3])
        self.assertEqual(attempt["answer"], ANSWER)


class RetrievalFilterTest(unittest.TestCase):
    """The vector search excludes soft-deleted documents (checked on the PostgreSQL SQL)."""

    def test_vector_search_excludes_soft_deleted_documents(self):
        from sqlalchemy.dialects import postgresql

        from app.services import retrieval

        captured = []

        class FakeSession:
            def execute(self, stmt):
                captured.append(stmt)
                return []

        for document_ids in (None, [1, 2]):
            with self.subTest(document_ids=document_ids):
                captured.clear()
                retrieval._nearest(FakeSession(), [0.0] * 384, 5, document_ids)
                sql = str(captured[0].compile(dialect=postgresql.dialect()))
                self.assertIn("documents.deleted_at IS NULL", sql)



if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
