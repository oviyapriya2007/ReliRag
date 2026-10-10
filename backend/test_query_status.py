"""RELI-RAG Day 2-3: status handling and evaluation persistence for POST /query.

Usage (from the project root or backend/):
    python backend/test_query_status.py

Offline: retrieval and Claude (generator and evaluator) are mocked, and the app runs
against an in-memory SQLite database, so no Claude API calls are made and the real
database is never touched. Exits with status 0 when all tests pass, 1 otherwise.
"""

import json
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
from sqlalchemy.orm import selectinload, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Answer, Document, DocumentChunk, Evaluation, Query  # noqa: E402
from app.routers.query import GATE_FAILED_MESSAGE, NOT_SUPPORTED_MESSAGE  # noqa: E402
from app.services.evaluator import (  # noqa: E402
    EVALUATOR_ERROR,
    SUPPORTED,
    UNSUPPORTED,
    UNSUPPORTED_CLAIM,
)
from app.services.generator import ANSWERED  # noqa: E402
from app.services.llm import LLMResult  # noqa: E402
from app.services.retrieval import RetrievedChunk  # noqa: E402
from app.services.similarity_gate import INSUFFICIENT_EVIDENCE  # noqa: E402

MODEL = "claude-test-model"
CHUNK_TEXT = "TCP provides a reliable, ordered byte stream."
ANSWER_TEXT = "TCP provides a reliable, ordered byte stream [1]."


def llm_result(text: str) -> LLMResult:
    return LLMResult(
        text=text, model=MODEL, input_tokens=100, output_tokens=20,
        latency_ms=5, stop_reason="end_turn", attempts=1,
    )


def evaluator_reply(claims: list[dict], answer_relevance: float = 0.95,
                    context_relevance: float = 0.9) -> str:
    return json.dumps({"claims": claims, "answer_relevance": answer_relevance,
                       "context_relevance": context_relevance, "feedback": "Checked."})


def claim(text: str, verdict: str, chunk_id: int | None, quote: str | None) -> dict:
    return {"claim_text": text, "verdict": verdict, "evidence_chunk_id": chunk_id,
            "evidence_quote": quote}


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
                document=document, page_number=4, chunk_index=0, content=CHUNK_TEXT,
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
            page=4, text=CHUNK_TEXT, similarity=similarity,
        )]

    def passing_claims(self) -> list[dict]:
        return [claim("TCP provides a reliable, ordered byte stream.", SUPPORTED, self.chunk_id,
                      "reliable, ordered byte stream")]

    def post_query(self, similarity: float, claude_text: str | None = None,
                   evaluator_texts: list[str] | None = None):
        """POST /query with mocked retrieval and Claude.

        The generator's Claude returns `claude_text`; the evaluator's Claude returns
        `evaluator_texts` in order (default: one passing evaluation).
        Returns (response JSON, generator Claude mock, evaluator Claude mock).
        """
        if evaluator_texts is None:
            evaluator_texts = [evaluator_reply(self.passing_claims())]
        with patch("app.services.similarity_gate.retrieve", return_value=self.retrieved(similarity)), \
             patch("app.services.generator.call_claude") as claude, \
             patch("app.services.evaluator.call_claude") as evaluator:
            if claude_text is not None:
                claude.return_value = llm_result(claude_text)
            evaluator.side_effect = [llm_result(text) for text in evaluator_texts]
            response = self.client.post(
                "/query", json={"question": "What is TCP?", "document_ids": [self.document_id]}
            )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), claude, evaluator

    def saved_evaluations(self, query_id: int) -> list[Evaluation]:
        with self.Session() as db:
            return db.scalars(
                select(Evaluation)
                .join(Answer)
                .where(Answer.query_id == query_id)
                .options(selectinload(Evaluation.claims))
            ).all()

    def assert_no_evaluation(self, attempt: dict) -> None:
        self.assertIn("evaluation", attempt)
        self.assertIsNone(attempt["evaluation"])
        self.assertIsNone(attempt["timings"]["evaluate_ms"])

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
        body, claude, _ = self.post_query(0.9, ANSWER_TEXT)

        claude.assert_called_once()
        self.assert_status_consistent(body, ANSWERED)
        self.assertEqual(body["final_answer"], ANSWER_TEXT)
        attempt = body["attempts"][0]
        self.assertEqual(attempt["answer"], ANSWER_TEXT)
        self.assertEqual(attempt["citations"], [1])
        self.assertEqual(attempt["model"], MODEL)

    def test_answer_passing_evaluation_is_persisted(self):
        body, _, evaluator = self.post_query(0.9, ANSWER_TEXT)

        evaluator.assert_called_once()
        prompt = evaluator.call_args.args[0]
        self.assertIn("What is TCP?", prompt)
        self.assertIn(ANSWER_TEXT, prompt)
        self.assertIn(f"chunk_id={self.chunk_id}", prompt)
        self.assert_status_consistent(body, ANSWERED)

        [evaluation] = self.saved_evaluations(body["query_id"])
        self.assertTrue(evaluation.passed)
        self.assertIsNone(evaluation.failure_type)
        self.assertEqual(evaluation.faithfulness, 1.0)
        self.assertEqual(evaluation.answer_relevance, 0.95)
        self.assertEqual(evaluation.context_relevance, 0.9)
        self.assertEqual(evaluation.feedback, "Checked.")
        self.assertEqual((evaluation.model, evaluation.input_tokens, evaluation.output_tokens),
                         (MODEL, 100, 20))
        self.assertIsNotNone(evaluation.latency_ms)
        [saved_claim] = evaluation.claims
        self.assertEqual(saved_claim.verdict, SUPPORTED)
        self.assertEqual(saved_claim.evidence_chunk_id, self.chunk_id)
        self.assertEqual(saved_claim.evidence_quote, "reliable, ordered byte stream")

        attempt = body["attempts"][0]
        self.assertEqual(attempt["evaluation"], {
            "faithfulness": 1.0,
            "answer_relevance": 0.95,
            "context_relevance": 0.9,
            "passed": True,
            "failure_type": None,
            "feedback": "Checked.",
            "claims": [{
                "claim_text": "TCP provides a reliable, ordered byte stream.",
                "verdict": SUPPORTED,
                "evidence_chunk_id": self.chunk_id,
                "evidence_quote": "reliable, ordered byte stream",
            }],
        })
        self.assertEqual(attempt["timings"]["evaluate_ms"], evaluation.latency_ms)
        self.assertEqual(attempt["timings"]["generate_ms"], 5)

    def test_answer_failing_evaluation_keeps_answer_and_final_verdicts(self):
        claims = self.passing_claims() + [
            claim("TCP was standardised in 1999.", SUPPORTED, self.chunk_id + 999, "1999"),
            claim("TCP is faster than UDP.", UNSUPPORTED, None, None),
        ]
        body, _, _ = self.post_query(0.9, ANSWER_TEXT, [evaluator_reply(claims)])

        self.assert_status_consistent(body, ANSWERED)
        self.assertEqual(body["final_answer"], ANSWER_TEXT)
        [evaluation] = self.saved_evaluations(body["query_id"])
        self.assertFalse(evaluation.passed)
        self.assertEqual(evaluation.failure_type, UNSUPPORTED_CLAIM)
        self.assertAlmostEqual(evaluation.faithfulness, 1 / 3)
        self.assertEqual([c.claim_text for c in evaluation.claims],
                         [c["claim_text"] for c in claims])
        self.assertEqual([c.verdict for c in evaluation.claims],
                         [SUPPORTED, UNSUPPORTED, UNSUPPORTED])
        self.assertEqual([c.evidence_chunk_id for c in evaluation.claims],
                         [self.chunk_id, None, None])

        returned = body["attempts"][0]["evaluation"]
        self.assertFalse(returned["passed"])
        self.assertEqual(returned["failure_type"], UNSUPPORTED_CLAIM)
        self.assertAlmostEqual(returned["faithfulness"], 1 / 3)
        self.assertEqual(
            [(c["claim_text"], c["verdict"], c["evidence_chunk_id"], c["evidence_quote"])
             for c in returned["claims"]],
            [("TCP provides a reliable, ordered byte stream.", SUPPORTED, self.chunk_id,
              "reliable, ordered byte stream"),
             ("TCP was standardised in 1999.", UNSUPPORTED, None, None),
             ("TCP is faster than UDP.", UNSUPPORTED, None, None)],
        )

    def test_evaluator_error_is_persisted_without_changing_answer(self):
        body, _, evaluator = self.post_query(0.9, ANSWER_TEXT, ["not json", "still not json"])

        self.assertEqual(evaluator.call_count, 2)
        self.assert_status_consistent(body, ANSWERED)
        self.assertEqual(body["final_answer"], ANSWER_TEXT)
        [evaluation] = self.saved_evaluations(body["query_id"])
        self.assertFalse(evaluation.passed)
        self.assertEqual(evaluation.failure_type, EVALUATOR_ERROR)
        self.assertIsNone(evaluation.faithfulness)
        self.assertIsNone(evaluation.answer_relevance)
        self.assertIsNone(evaluation.context_relevance)
        self.assertEqual(evaluation.input_tokens, 200)
        self.assertEqual(evaluation.claims, [])

        attempt = body["attempts"][0]
        returned = attempt["evaluation"]
        self.assertFalse(returned["passed"])
        self.assertEqual(returned["failure_type"], EVALUATOR_ERROR)
        self.assertIsNone(returned["faithfulness"])
        self.assertIsNone(returned["answer_relevance"])
        self.assertIsNone(returned["context_relevance"])
        self.assertIn("Evaluation failed", returned["feedback"])
        self.assertEqual(returned["claims"], [])
        self.assertEqual(attempt["timings"]["evaluate_ms"], evaluation.latency_ms)
        self.assertEqual(attempt["citations"], [1])

    def test_evaluator_exception_does_not_fail_query(self):
        with patch("app.services.query_pipeline.evaluate_answer",
                   side_effect=RuntimeError("evaluator crashed")):
            body, _, _ = self.post_query(0.9, ANSWER_TEXT)

        self.assert_status_consistent(body, ANSWERED)
        self.assertEqual(body["final_answer"], ANSWER_TEXT)
        [evaluation] = self.saved_evaluations(body["query_id"])
        self.assertEqual(evaluation.failure_type, EVALUATOR_ERROR)
        self.assertIn("evaluator crashed", evaluation.feedback)

    def test_evaluation_save_failure_keeps_answer(self):
        original_commit = self.Session.class_.commit
        failed_commits = []

        def commit_failing_on_evaluation(session):
            if any(isinstance(obj, Evaluation) for obj in session.new):
                failed_commits.append(session)
                raise RuntimeError("db down")
            return original_commit(session)

        with patch.object(self.Session.class_, "commit", commit_failing_on_evaluation):
            body, _, _ = self.post_query(0.9, ANSWER_TEXT)

        self.assertEqual(len(failed_commits), 1)
        self.assert_status_consistent(body, ANSWERED)
        self.assertEqual(self.saved_evaluations(body["query_id"]), [])
        self.assert_no_evaluation(body["attempts"][0])
        self.assertEqual(body["attempts"][0]["answer"], ANSWER_TEXT)

    def test_latest_evaluation_is_returned(self):
        body, _, _ = self.post_query(0.9, ANSWER_TEXT)
        with self.Session() as db:
            answer = db.scalars(select(Answer).where(Answer.query_id == body["query_id"])).one()
            db.add(Evaluation(answer_id=answer.id, faithfulness=0.5, answer_relevance=0.9,
                              context_relevance=0.9, passed=False,
                              failure_type=UNSUPPORTED_CLAIM, feedback="Re-evaluated.",
                              latency_ms=42))
            db.commit()

        fetched = self.client.get(f"/query/{body['query_id']}").json()
        attempt = fetched["attempts"][0]
        self.assertEqual(attempt["evaluation"]["feedback"], "Re-evaluated.")
        self.assertEqual(attempt["evaluation"]["claims"], [])
        self.assertEqual(attempt["timings"]["evaluate_ms"], 42)
        self.assertEqual(fetched["status"], ANSWERED)

    def test_claude_refusal_is_insufficient_evidence(self):
        refusals = [
            "INSUFFICIENT_EVIDENCE",
            "INSUFFICIENT_EVIDENCE\n\nThe passages do not mention any Wi-Fi password.",
            "INSUFFICIENT_EVIDENCE. Passage [1] covers TCP but not the question asked.",
            "**INSUFFICIENT_EVIDENCE**",
        ]
        for text in refusals:
            with self.subTest(claude_text=text):
                body, claude, evaluator = self.post_query(0.9, text)

                claude.assert_called_once()
                evaluator.assert_not_called()
                self.assertEqual(self.saved_evaluations(body["query_id"]), [])
                self.assert_status_consistent(body, INSUFFICIENT_EVIDENCE)
                self.assertEqual(body["final_answer"], NOT_SUPPORTED_MESSAGE)
                attempt = body["attempts"][0]
                self.assertIsNone(attempt["answer"])
                self.assertEqual(attempt["citations"], [])
                self.assertEqual(attempt["model"], MODEL)
                self.assertEqual(len(attempt["retrieval"]), 1)
                self.assert_no_evaluation(attempt)

    def test_similarity_gate_rejection_skips_claude(self):
        body, claude, evaluator = self.post_query(0.05)

        claude.assert_not_called()
        evaluator.assert_not_called()
        self.assertEqual(self.saved_evaluations(body["query_id"]), [])
        self.assert_status_consistent(body, INSUFFICIENT_EVIDENCE)
        self.assertEqual(body["final_answer"], GATE_FAILED_MESSAGE)
        attempt = body["attempts"][0]
        self.assertIsNone(attempt["answer"])
        self.assertIsNone(attempt["model"])
        self.assertEqual(attempt["citations"], [])
        self.assertEqual(len(attempt["retrieval"]), 1)
        self.assert_no_evaluation(attempt)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
