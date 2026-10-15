"""RELI-RAG Day 4: offline tests for the run_reli_rag() orchestrator behind POST /query mode="reli".

Usage (from the project root or backend/):
    python backend/test_reli_rag.py

Offline: retrieval and every Claude caller (generator, evaluator, query rewriter) are mocked, and
the app runs against an in-memory SQLite database, so no API calls are made and the real
database is never touched. Exits with status 0 when all tests pass, 1 otherwise.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# Must be set before `app` is imported so the app never connects to the real database.
os.environ["DATABASE_URL"] = "sqlite://"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import selectinload, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Answer, Document, DocumentChunk, Query, RetrievalLog  # noqa: E402
from app.routers.query import GATE_FAILED_MESSAGE, NOT_SUPPORTED_MESSAGE  # noqa: E402
from app.services import generator  # noqa: E402
from app.services.corrector import RETRY_TOP_K, REWRITE, STRICT  # noqa: E402
from app.services.evaluator import (  # noqa: E402
    EVALUATOR_ERROR,
    IRRELEVANT_RETRIEVAL,
    MISSING_INFO,
    PARTIALLY_SUPPORTED,
    SUPPORTED,
    UNSUPPORTED,
    UNSUPPORTED_CLAIM,
)
from app.services.generator import ANSWERED  # noqa: E402
from app.services.llm import LLMError, LLMResult  # noqa: E402
from app.services.query_pipeline import ERROR  # noqa: E402
from app.services.retrieval import RetrievedChunk  # noqa: E402
from app.services.similarity_gate import INSUFFICIENT_EVIDENCE  # noqa: E402

MODEL = "claude-test-model"
PINNED_SETTINGS = {
    "claude_model": MODEL,
    "claude_max_tokens": 1024,
    "similarity_gate": 0.30,
    "evaluator_model": None,
    "evaluator_max_tokens": 2048,
    "evaluator_pass_threshold": 0.80,
    "evaluator_max_parse_attempts": 2,
}

QUESTION = "What is the allowance for item A?"
REWRITTEN = "item A allowance amount per year"
CHUNK_TEXTS = [
    "Policy 1. Members may request item A after approval.",
    "Policy 2. Item B has an allowance of 50 units per year.",
    "Policy 3. Item A has an allowance of 200 units per year.",
    "Policy 4. Requests must be submitted in writing.",
]
FIRST_ANSWER = "Members may request item A after approval [1]."
SECOND_ANSWER = "Item A has an allowance of 200 units per year [1]."
UNSUPPORTED_TEXT = "Item A has an allowance of 100 units."


def llm_result(text: str) -> LLMResult:
    return LLMResult(text=text, model=MODEL, input_tokens=100, output_tokens=20,
                     latency_ms=5, stop_reason="end_turn", attempts=1)


def replies(items) -> list:
    """Mock side effects: strings become Claude replies, exceptions are raised."""
    return [item if isinstance(item, Exception) else llm_result(item) for item in items]


class ReliRagTest(unittest.TestCase):
    def setUp(self):
        for name, value in PINNED_SETTINGS.items():
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        self.Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

        with self.Session() as db:
            document = Document(filename="policies.pdf", total_pages=4, total_chunks=4)
            chunks = [DocumentChunk(document=document, page_number=i + 1, chunk_index=i,
                                    content=text) for i, text in enumerate(CHUNK_TEXTS)]
            db.add_all([document, *chunks])
            db.commit()
            self.document_id = document.id
            self.chunk_ids = [chunk.id for chunk in chunks]

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    # --- fixtures -------------------------------------------------------------------------

    def retrieved(self, indexes, similarity=0.8) -> list[RetrievedChunk]:
        return [RetrievedChunk(chunk_id=self.chunk_ids[i], document_id=self.document_id,
                               document="policies.pdf", page=i + 1, text=CHUNK_TEXTS[i],
                               similarity=similarity - 0.01 * rank)
                for rank, i in enumerate(indexes)]

    def supported(self, index: int) -> dict:
        text = CHUNK_TEXTS[index].split(". ", 1)[1]
        return {"claim_text": text, "verdict": SUPPORTED,
                "evidence_chunk_id": self.chunk_ids[index], "evidence_quote": text.rstrip(".")}

    @staticmethod
    def unsupported(text: str = UNSUPPORTED_TEXT) -> dict:
        return {"claim_text": text, "verdict": UNSUPPORTED, "evidence_chunk_id": None,
                "evidence_quote": None}

    @staticmethod
    def evaluation(claims, answer_relevance, context_relevance, feedback="Checked.") -> str:
        return json.dumps({"claims": claims, "answer_relevance": answer_relevance,
                           "context_relevance": context_relevance, "feedback": feedback})

    def passing(self, index: int = 2) -> str:
        return self.evaluation([self.supported(index)], 0.95, 0.9)

    def irrelevant(self) -> str:
        """Faithful and on-topic, but the passages lack the needed information (mean 0.717)."""
        return self.evaluation([self.supported(0)], 0.85, 0.3,
                               feedback="The passages do not state the allowance for item A.")

    def unsupported_claim(self, context_relevance=0.9) -> str:
        return self.evaluation([self.supported(0), self.unsupported()], 0.9, context_relevance)

    # --- helpers --------------------------------------------------------------------------

    def post(self, *, retrievals, generations, evaluations=(), rewrites=(), mode="reli",
             expected_status=200):
        with patch("app.services.similarity_gate.retrieve", side_effect=list(retrievals)) as rt, \
             patch("app.services.generator.call_claude",
                   side_effect=replies(generations)) as gen, \
             patch("app.services.evaluator.call_claude",
                   side_effect=replies(evaluations)) as ev, \
             patch("app.services.corrector.call_claude", side_effect=replies(rewrites)) as rw:
            body = {"question": QUESTION}
            if mode is not None:
                body["mode"] = mode
            response = self.client.post("/query", json=body)
        self.assertEqual(response.status_code, expected_status, response.text)
        mocks = SimpleNamespace(retrieve=rt, generator=gen, evaluator=ev, rewriter=rw)
        return response.json(), mocks

    def saved(self, query_id: int):
        with self.Session() as db:
            query = db.scalars(
                select(Query).where(Query.id == query_id).options(
                    selectinload(Query.answers).selectinload(Answer.evaluations))
            ).one()
            return query, list(query.answers)

    def logged_chunk_ids(self, answer_id: int) -> list[int]:
        with self.Session() as db:
            return list(db.scalars(select(RetrievalLog.chunk_id)
                                   .where(RetrievalLog.answer_id == answer_id)
                                   .order_by(RetrievalLog.rank)))

    def assert_final(self, body: dict, attempt_number: int, status: str, final_answer: str,
                     attempts: int):
        self.assertEqual(body["mode"], "reli")
        self.assertEqual(body["status"], status)
        self.assertEqual(body["final_attempt_number"], attempt_number)
        self.assertEqual(body["final_answer"], final_answer)
        self.assertEqual([a["attempt_number"] for a in body["attempts"]],
                         list(range(1, attempts + 1)))
        fetched = self.client.get(f"/query/{body['query_id']}")
        self.assertEqual(fetched.status_code, 200, fetched.text)
        self.assertEqual(fetched.json(), body)
        query, answers = self.saved(body["query_id"])
        self.assertEqual((query.mode, query.final_status, query.final_attempt_number),
                         ("reli", status, attempt_number))
        self.assertEqual(len(answers), attempts)

    # --- tests ----------------------------------------------------------------------------

    def test_passing_first_attempt_is_not_retried(self):
        body, mocks = self.post(retrievals=[self.retrieved([2, 0])], generations=[SECOND_ANSWER],
                                evaluations=[self.passing()])

        self.assert_final(body, 1, ANSWERED, SECOND_ANSWER, attempts=1)
        self.assertEqual((mocks.retrieve.call_count, mocks.generator.call_count,
                          mocks.evaluator.call_count), (1, 1, 1))
        mocks.rewriter.assert_not_called()
        self.assertIsNone(body["attempts"][0]["strategy"])
        self.assertTrue(body["attempts"][0]["evaluation"]["passed"])

    def test_rewrite_correction_selects_passing_second_attempt(self):
        body, mocks = self.post(
            retrievals=[self.retrieved([0, 1]), self.retrieved([2, 0, 1])],
            generations=[FIRST_ANSWER, SECOND_ANSWER],
            evaluations=[self.irrelevant(), self.passing()],
            rewrites=[REWRITTEN],
        )

        self.assert_final(body, 2, ANSWERED, SECOND_ANSWER, attempts=2)
        mocks.rewriter.assert_called_once()
        self.assertIn("The passages do not state the allowance for item A.",
                      mocks.rewriter.call_args.args[0])
        first_call, second_call = mocks.retrieve.call_args_list
        self.assertEqual((first_call.args[1], first_call.kwargs["k"]), (QUESTION, 5))
        self.assertEqual((second_call.args[1], second_call.kwargs["k"]), (REWRITTEN, RETRY_TOP_K))
        self.assertTrue(mocks.generator.call_args.args[0].endswith(f"Question: {QUESTION}"))

        first, second = body["attempts"]
        self.assertEqual((first["strategy"], first["answer"], first["retrieval_query"]),
                         (None, FIRST_ANSWER, QUESTION))
        self.assertEqual(first["evaluation"]["failure_type"], IRRELEVANT_RETRIEVAL)
        self.assertEqual((second["strategy"], second["answer"], second["retrieval_query"]),
                         (REWRITE, SECOND_ANSWER, REWRITTEN))
        self.assertTrue(second["evaluation"]["passed"])
        self.assertEqual(len(second["retrieval"]), 3)

        query, answers = self.saved(body["query_id"])
        self.assertEqual(query.options["retry_k"], RETRY_TOP_K)
        self.assertEqual([a.strategy for a in answers], [None, REWRITE])
        self.assertEqual([len(a.evaluations) for a in answers], [1, 1])

    def test_missing_info_and_weak_context_unsupported_claim_are_rewritten(self):
        for first_evaluation in (self.evaluation([self.supported(0)], 0.5, 0.9),
                                 self.unsupported_claim(context_relevance=0.4)):
            with self.subTest(first_evaluation=first_evaluation[:60]):
                body, mocks = self.post(
                    retrievals=[self.retrieved([0]), self.retrieved([2])],
                    generations=[FIRST_ANSWER, SECOND_ANSWER],
                    evaluations=[first_evaluation, self.passing()],
                    rewrites=[REWRITTEN],
                )
                self.assert_final(body, 2, ANSWERED, SECOND_ANSWER, attempts=2)
                self.assertEqual(body["attempts"][1]["strategy"], REWRITE)
                mocks.rewriter.assert_called_once()

    def test_strict_correction_reuses_first_attempt_chunks(self):
        strict_answer = SECOND_ANSWER.replace("[1]", "[2]")
        body, mocks = self.post(
            retrievals=[self.retrieved([0, 2])],
            generations=[f"{FIRST_ANSWER} {UNSUPPORTED_TEXT} [2]", strict_answer],
            evaluations=[self.unsupported_claim(context_relevance=0.9), self.passing()],
        )

        self.assert_final(body, 2, ANSWERED, strict_answer, attempts=2)
        mocks.retrieve.assert_called_once()
        mocks.rewriter.assert_not_called()
        first_call, second_call = mocks.generator.call_args_list
        self.assertEqual(second_call.args[0], first_call.args[0])
        self.assertEqual(first_call.kwargs["system"], generator.SYSTEM_PROMPT)
        self.assertTrue(second_call.kwargs["system"].startswith(generator.SYSTEM_PROMPT))
        self.assertIn(f"- {UNSUPPORTED_TEXT}", second_call.kwargs["system"])

        first, second = body["attempts"]
        self.assertEqual(first["evaluation"]["failure_type"], UNSUPPORTED_CLAIM)
        self.assertEqual((second["strategy"], second["retrieval_query"]), (STRICT, QUESTION))
        self.assertEqual(second["retrieval"], first["retrieval"])
        _, answers = self.saved(body["query_id"])
        self.assertEqual(self.logged_chunk_ids(answers[1].id), self.logged_chunk_ids(answers[0].id))
        self.assertEqual(self.logged_chunk_ids(answers[1].id),
                         [self.chunk_ids[0], self.chunk_ids[2]])

    def test_at_most_one_retry_even_if_second_attempt_fails(self):
        body, mocks = self.post(
            retrievals=[self.retrieved([0]), self.retrieved([0, 2])],
            generations=[FIRST_ANSWER, SECOND_ANSWER],
            evaluations=[self.evaluation([self.supported(0)], 0.5, 0.9),   # missing_info, 0.8
                         self.evaluation([self.supported(2)], 0.7, 0.9)],  # missing_info, 0.867
            rewrites=[REWRITTEN],
        )

        # Still failing, but better overall with equal faithfulness: attempt 2 is chosen.
        self.assert_final(body, 2, ANSWERED, SECOND_ANSWER, attempts=2)
        self.assertEqual(body["attempts"][1]["evaluation"]["failure_type"], MISSING_INFO)
        self.assertEqual((mocks.retrieve.call_count, mocks.generator.call_count,
                          mocks.evaluator.call_count, mocks.rewriter.call_count), (2, 2, 2, 1))

    def test_failing_second_attempt_that_would_qualify_for_strict_is_not_retried(self):
        body, mocks = self.post(
            retrievals=[self.retrieved([0]), self.retrieved([0, 2])],
            generations=[FIRST_ANSWER, SECOND_ANSWER],
            evaluations=[self.irrelevant(), self.unsupported_claim(context_relevance=0.9)],
            rewrites=[REWRITTEN],
        )

        self.assert_final(body, 1, ANSWERED, FIRST_ANSWER, attempts=2)
        self.assertEqual(mocks.generator.call_count, 2)

    def test_lower_scoring_second_attempt_keeps_first(self):
        body, _ = self.post(
            retrievals=[self.retrieved([0]), self.retrieved([1])],
            generations=[FIRST_ANSWER, SECOND_ANSWER],
            evaluations=[self.irrelevant(),
                         self.evaluation([self.supported(1), self.unsupported()], 0.9, 0.9)],
            rewrites=[REWRITTEN],
        )

        self.assert_final(body, 1, ANSWERED, FIRST_ANSWER, attempts=2)
        first, second = body["attempts"]
        self.assertEqual(
            (first["evaluation"]["faithfulness"], second["evaluation"]["faithfulness"]), (1.0, 0.5)
        )
        self.assertEqual((second["status"], second["answer"], second["strategy"]),
                         (ANSWERED, SECOND_ANSWER, REWRITE))

    def test_passing_second_attempt_that_scores_lower_keeps_first(self):
        partial = {"claim_text": "Item A has an allowance of 200 units per year for everyone",
                   "verdict": PARTIALLY_SUPPORTED, "evidence_chunk_id": self.chunk_ids[2],
                   "evidence_quote": "Item A has an allowance of 200 units per year"}
        body, mocks = self.post(
            retrievals=[self.retrieved([0]), self.retrieved([2])],
            generations=[FIRST_ANSWER, SECOND_ANSWER],
            evaluations=[self.evaluation([self.supported(0)], 0.75, 1.0),        # missing_info, 0.917
                         self.evaluation([self.supported(2)] * 4 + [partial], 0.85, 0.85)],  # 0.867
            rewrites=[REWRITTEN],
        )

        self.assert_final(body, 1, ANSWERED, FIRST_ANSWER, attempts=2)
        first, second = body["attempts"]
        self.assertEqual(first["evaluation"]["failure_type"], MISSING_INFO)
        self.assertTrue(second["evaluation"]["passed"])
        self.assertEqual(
            (first["evaluation"]["faithfulness"], second["evaluation"]["faithfulness"]), (1.0, 0.9)
        )
        self.assertEqual((second["status"], second["strategy"]), (ANSWERED, REWRITE))
        self.assertEqual(mocks.evaluator.call_count, 2)

    def test_first_attempt_gate_failure_is_not_retried(self):
        body, mocks = self.post(retrievals=[self.retrieved([0], similarity=0.1)], generations=[])

        self.assert_final(body, 1, INSUFFICIENT_EVIDENCE, GATE_FAILED_MESSAGE, attempts=1)
        mocks.generator.assert_not_called()
        mocks.evaluator.assert_not_called()
        mocks.rewriter.assert_not_called()
        self.assertEqual(mocks.retrieve.call_count, 1)

    def test_first_attempt_refusal_is_not_retried(self):
        body, mocks = self.post(retrievals=[self.retrieved([0])],
                                generations=[INSUFFICIENT_EVIDENCE])

        self.assert_final(body, 1, INSUFFICIENT_EVIDENCE, NOT_SUPPORTED_MESSAGE, attempts=1)
        mocks.evaluator.assert_not_called()
        mocks.rewriter.assert_not_called()

    def test_second_attempt_gate_failure_or_refusal_keeps_first(self):
        cases = {
            "gate failure": ([self.retrieved([0]), self.retrieved([1], similarity=0.1)],
                             [FIRST_ANSWER]),
            "refusal": ([self.retrieved([0]), self.retrieved([1])],
                        [FIRST_ANSWER, INSUFFICIENT_EVIDENCE]),
        }
        for name, (retrievals, generations) in cases.items():
            with self.subTest(name):
                body, mocks = self.post(retrievals=retrievals, generations=generations,
                                        evaluations=[self.irrelevant()], rewrites=[REWRITTEN])

                self.assert_final(body, 1, ANSWERED, FIRST_ANSWER, attempts=2)
                second = body["attempts"][1]
                self.assertEqual((second["status"], second["answer"], second["evaluation"]),
                                 (INSUFFICIENT_EVIDENCE, None, None))
                self.assertEqual(mocks.evaluator.call_count, 1)

    def test_second_attempt_claude_failure_keeps_first(self):
        cases = {
            STRICT: dict(retrievals=[self.retrieved([0, 2])],
                         evaluations=[self.unsupported_claim(context_relevance=0.9)]),
            REWRITE: dict(retrievals=[self.retrieved([0]), self.retrieved([2])],
                          evaluations=[self.irrelevant()], rewrites=[REWRITTEN]),
        }
        for strategy, kwargs in cases.items():
            with self.subTest(strategy):
                body, mocks = self.post(generations=[FIRST_ANSWER, LLMError("overloaded")],
                                        **kwargs)

                self.assert_final(body, 1, ANSWERED, FIRST_ANSWER, attempts=2)
                first, second = body["attempts"]
                self.assertEqual((second["status"], second["strategy"], second["evaluation"]),
                                 (ERROR, strategy, None))
                self.assertEqual((first["status"], first["answer"]), (ANSWERED, FIRST_ANSWER))
                self.assertIsNotNone(first["evaluation"])
                self.assertEqual(mocks.evaluator.call_count, 1)

    def test_unexpected_second_attempt_generation_error_is_stored_and_keeps_first(self):
        cases = {
            STRICT: dict(retrievals=[self.retrieved([0, 2])],
                         evaluations=[self.unsupported_claim(context_relevance=0.9)]),
            REWRITE: dict(retrievals=[self.retrieved([0]), self.retrieved([2])],
                          evaluations=[self.irrelevant()], rewrites=[REWRITTEN]),
        }
        for strategy, kwargs in cases.items():
            with self.subTest(strategy):
                body, mocks = self.post(
                    generations=[FIRST_ANSWER, TypeError("Could not resolve authentication")],
                    **kwargs)

                self.assert_final(body, 1, ANSWERED, FIRST_ANSWER, attempts=2)
                first, second = body["attempts"]
                self.assertEqual(
                    (second["status"], second["strategy"], second["answer"], second["evaluation"]),
                    (ERROR, strategy, None, None))
                self.assertEqual((first["status"], first["answer"]), (ANSWERED, FIRST_ANSWER))
                self.assertEqual(mocks.evaluator.call_count, 1)
                _, answers = self.saved(body["query_id"])
                self.assertEqual([a.status for a in answers], [ANSWERED, ERROR])

    def test_unexpected_second_attempt_failure_keeps_first(self):
        body, _ = self.post(
            retrievals=[self.retrieved([0]), RuntimeError("embedding service down")],
            generations=[FIRST_ANSWER], evaluations=[self.irrelevant()], rewrites=[REWRITTEN],
        )

        self.assert_final(body, 1, ANSWERED, FIRST_ANSWER, attempts=1)

    def test_first_attempt_claude_failure_is_error_without_retry(self):
        _, mocks = self.post(retrievals=[self.retrieved([0])],
                             generations=[LLMError("overloaded")], expected_status=502)

        mocks.evaluator.assert_not_called()
        mocks.rewriter.assert_not_called()
        self.assertEqual(mocks.retrieve.call_count, 1)
        with self.Session() as db:
            query = db.scalars(select(Query)).one()
            query_id = query.id
        query, answers = self.saved(query_id)
        self.assertEqual((query.mode, query.final_status, query.final_attempt_number),
                         ("reli", ERROR, 1))
        self.assertEqual([(a.attempt_number, a.status) for a in answers], [(1, ERROR)])

    def test_evaluator_error_is_not_retried(self):
        body, mocks = self.post(retrievals=[self.retrieved([0])], generations=[FIRST_ANSWER],
                                evaluations=["not json", "still not json"])

        self.assert_final(body, 1, ANSWERED, FIRST_ANSWER, attempts=1)
        self.assertEqual(body["attempts"][0]["evaluation"]["failure_type"], EVALUATOR_ERROR)
        mocks.rewriter.assert_not_called()
        self.assertEqual(mocks.generator.call_count, 1)

    def test_second_attempt_evaluator_error_keeps_first(self):
        body, _ = self.post(
            retrievals=[self.retrieved([0]), self.retrieved([2])],
            generations=[FIRST_ANSWER, SECOND_ANSWER],
            evaluations=[self.irrelevant(), "not json", "still not json"],
            rewrites=[REWRITTEN],
        )

        self.assert_final(body, 1, ANSWERED, FIRST_ANSWER, attempts=2)
        self.assertEqual(body["attempts"][1]["evaluation"]["failure_type"], EVALUATOR_ERROR)

    def test_basic_mode_is_unchanged_and_default(self):
        for mode in (None, "basic"):
            with self.subTest(mode=mode):
                body, mocks = self.post(retrievals=[self.retrieved([0])],
                                        generations=[FIRST_ANSWER],
                                        evaluations=[self.irrelevant()], mode=mode)

                self.assertEqual((body["mode"], body["status"], body["final_answer"]),
                                 ("basic", ANSWERED, FIRST_ANSWER))
                self.assertEqual(body["final_attempt_number"], 1)
                self.assertEqual(len(body["attempts"]), 1)
                self.assertIsNone(body["attempts"][0]["strategy"])
                mocks.rewriter.assert_not_called()
                self.assertEqual(mocks.generator.call_count, 1)
                query, _ = self.saved(body["query_id"])
                self.assertIsNone(query.final_attempt_number)

    def test_unknown_mode_is_rejected(self):
        response = self.client.post("/query", json={"question": QUESTION, "mode": "other"})
        self.assertEqual(response.status_code, 422, response.text)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
