"""RELI-RAG Day 5 A1: offline tests for POST /compare and the shared-retrieval pipeline hooks.

Usage (from the project root or backend/):
    python backend/test_compare.py

Offline: retrieval and every Claude caller (generator, evaluator, query rewriter) are replaced
by fakes, and the app runs against a temporary SQLite file (so the two concurrent branches get
their own connections), so no API calls are made and the real database is never touched.
Exits with status 0 when all tests pass, 1 otherwise.
"""

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

# Must be set before `app` is imported so the app never connects to the real database.
os.environ["DATABASE_URL"] = "sqlite://"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Document, DocumentChunk, Query, RetrievalLog  # noqa: E402
from app.routers.query import ERROR_MESSAGE, GATE_FAILED_MESSAGE  # noqa: E402
from app.services.corrector import RETRY_TOP_K, REWRITE  # noqa: E402
from app.services.evaluator import IRRELEVANT_RETRIEVAL, SUPPORTED  # noqa: E402
from app.services.generator import ANSWERED  # noqa: E402
from app.services.llm import LLMError, LLMResult  # noqa: E402
from app.services.query_pipeline import ERROR, run_basic_query  # noqa: E402
from app.services.retrieval import RetrievedChunk  # noqa: E402
from app.services.similarity_gate import INSUFFICIENT_EVIDENCE, retrieve_with_gate  # noqa: E402

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
]
FIRST_ANSWER = "Members may request item A after approval [1]."
SECOND_ANSWER = "Item A has an allowance of 200 units per year [1]."
BASIC_OPTION_KEYS = {"k", "document_ids", "similarity_gate"}


def llm_result(text: str) -> LLMResult:
    return LLMResult(text=text, model=MODEL, input_tokens=100, output_tokens=20,
                     latency_ms=5, stop_reason="end_turn", attempts=1)


class FakeClaude:
    """Thread-safe stand-in for one module's `call_claude`; records every prompt."""

    def __init__(self, reply):
        self.reply = reply
        self.prompts: list[str] = []
        self.threads: set[int] = set()
        self._lock = threading.Lock()

    def __call__(self, messages, **kwargs):
        with self._lock:
            self.prompts.append(messages)
            self.threads.add(threading.get_ident())
            number = len(self.prompts)
        result = self.reply(messages, number)
        if isinstance(result, Exception):
            raise result
        return llm_result(result)


class CompareTest(unittest.TestCase):
    def setUp(self):
        for name, value in PINNED_SETTINGS.items():
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        # A file (not :memory:) so each concurrent branch session gets its own connection.
        # pysqlite only opens a transaction right before a write, and the pipeline commits
        # each write at once, so branches never hold a lock across a (fake) Claude call.
        engine = create_engine(f"sqlite:///{Path(tmpdir.name) / 'compare.db'}",
                               connect_args={"check_same_thread": False, "timeout": 30})
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        self.Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

        with self.Session() as db:
            document = Document(filename="policies.pdf", total_pages=3, total_chunks=3)
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

    def evaluation(self, index: int, answer_relevance: float, context_relevance: float) -> str:
        text = CHUNK_TEXTS[index].split(". ", 1)[1]
        claim = {"claim_text": text, "verdict": SUPPORTED,
                 "evidence_chunk_id": self.chunk_ids[index], "evidence_quote": text.rstrip(".")}
        return json.dumps({"claims": [claim], "answer_relevance": answer_relevance,
                           "context_relevance": context_relevance, "feedback": "Checked."})

    def evaluator_for(self, verdicts: dict[str, str]) -> FakeClaude:
        """Evaluator replies keyed by the answer being evaluated."""
        def reply(prompt, _):
            for answer, evaluation in verdicts.items():
                if f"<answer>\n{answer}\n</answer>" in prompt:
                    return evaluation
            raise AssertionError(f"unexpected answer evaluated: {prompt[-200:]}")
        return FakeClaude(reply)

    @staticmethod
    def answers_by_context(prompt, _):
        """Generator reply: the chunk-3 answer once the passages contain chunk 3."""
        return SECOND_ANSWER if CHUNK_TEXTS[2] in prompt else FIRST_ANSWER

    # --- helpers --------------------------------------------------------------------------

    def post_compare(self, *, shared, generator, evaluator, rewrite_retrievals=(),
                     expected_status=200, **body):
        rewriter = FakeClaude(lambda *_: REWRITTEN)
        with patch("app.services.compare.retrieve", return_value=shared) as shared_retrieve, \
             patch("app.services.similarity_gate.retrieve",
                   side_effect=list(rewrite_retrievals)) as gate_retrieve, \
             patch("app.services.generator.call_claude", new=generator), \
             patch("app.services.evaluator.call_claude", new=evaluator), \
             patch("app.services.corrector.call_claude", new=rewriter):
            response = self.client.post("/compare", json={"question": QUESTION, **body})
        self.assertEqual(response.status_code, expected_status, response.text)
        return response.json(), shared_retrieve, gate_retrieve, rewriter

    def compare_queries(self) -> list[Query]:
        with self.Session() as db:
            return list(db.scalars(select(Query).order_by(Query.id)))

    def logged(self, query_id: int, attempt_number: int = 1) -> list[tuple[int, float]]:
        with self.Session() as db:
            query = db.get(Query, query_id)
            answer = next(a for a in query.answers if a.attempt_number == attempt_number)
            return [(log.chunk_id, log.similarity) for log in db.scalars(
                select(RetrievalLog).where(RetrievalLog.answer_id == answer.id)
                .order_by(RetrievalLog.rank))]

    # --- shared retrieval -----------------------------------------------------------------

    def test_shared_retrieval_feeds_both_independently_evaluated_branches(self):
        generator = FakeClaude(self.answers_by_context)
        evaluator = self.evaluator_for({FIRST_ANSWER: self.evaluation(0, 0.85, 0.3),
                                        SECOND_ANSWER: self.evaluation(2, 0.95, 0.9)})
        body, shared_retrieve, gate_retrieve, rewriter = self.post_compare(
            shared=self.retrieved([0, 1]), generator=generator, evaluator=evaluator,
            rewrite_retrievals=[self.retrieved([2, 0, 1])], k=4,
        )

        shared_retrieve.assert_called_once()
        self.assertEqual(shared_retrieve.call_args.args[1], QUESTION)
        self.assertEqual(shared_retrieve.call_args.kwargs, {"k": 4, "document_ids": None})
        # Only RELI-RAG's rewrite correction retrieves again.
        gate_retrieve.assert_called_once()
        self.assertEqual((gate_retrieve.call_args.args[1], gate_retrieve.call_args.kwargs["k"]),
                         (REWRITTEN, RETRY_TOP_K))
        self.assertEqual(len(rewriter.prompts), 1)

        basic, reli = body["basic"], body["reli"]
        self.assertEqual(body["question"], QUESTION)
        self.assertEqual((basic["mode"], basic["status"], basic["final_answer"]),
                         ("basic", ANSWERED, FIRST_ANSWER))
        self.assertEqual(len(basic["attempts"]), 1)
        self.assertEqual(basic["attempts"][0]["evaluation"]["failure_type"], IRRELEVANT_RETRIEVAL)
        self.assertEqual((reli["mode"], reli["status"], reli["final_answer"],
                          reli["final_attempt_number"]), ("reli", ANSWERED, SECOND_ANSWER, 2))
        self.assertEqual([a["strategy"] for a in reli["attempts"]], [None, REWRITE])
        self.assertEqual(basic["attempts"][0]["retrieval"], reli["attempts"][0]["retrieval"])

        # Independent generation and evaluation: one attempt-1 call per branch, same prompt.
        attempt_one_prompts = [p for p in generator.prompts if CHUNK_TEXTS[2] not in p]
        self.assertEqual(len(attempt_one_prompts), 2)
        self.assertEqual(attempt_one_prompts[0], attempt_one_prompts[1])
        self.assertEqual(len(generator.prompts), 3)
        self.assertEqual(len(evaluator.prompts), 3)

        basic_query, reli_query = self.compare_queries()
        self.assertEqual((basic_query.id, reli_query.id), (basic["query_id"], reli["query_id"]))
        for query in (basic_query, reli_query):
            self.assertEqual(query.options["compare_id"], body["compare_id"])
            self.assertIs(query.options["shared_retrieval"], True)
            self.assertEqual((query.options["k"], query.options["document_ids"]), (4, None))
        self.assertEqual(reli_query.options["retry_k"], RETRY_TOP_K)
        self.assertEqual(reli_query.final_attempt_number, 2)
        shared_log = [(chunk.chunk_id, chunk.similarity) for chunk in self.retrieved([0, 1])]
        self.assertEqual(self.logged(basic_query.id), shared_log)
        self.assertEqual(self.logged(reli_query.id), shared_log)

        for branch in (basic, reli):
            fetched = self.client.get(f"/query/{branch['query_id']}")
            self.assertEqual(fetched.json(), branch)

    def test_shared_gate_rejection_skips_claude_in_both_branches(self):
        generator = FakeClaude(self.answers_by_context)
        evaluator = self.evaluator_for({})
        body, shared_retrieve, gate_retrieve, _ = self.post_compare(
            shared=self.retrieved([0], similarity=0.1), generator=generator, evaluator=evaluator,
            document_ids=[self.document_id],
        )

        shared_retrieve.assert_called_once()
        self.assertEqual(shared_retrieve.call_args.kwargs["document_ids"], [self.document_id])
        gate_retrieve.assert_not_called()
        self.assertEqual((generator.prompts, evaluator.prompts), ([], []))
        for branch in (body["basic"], body["reli"]):
            self.assertEqual((branch["status"], branch["final_answer"], len(branch["attempts"])),
                             (INSUFFICIENT_EVIDENCE, GATE_FAILED_MESSAGE, 1))

    # --- concurrency ----------------------------------------------------------------------

    def test_branches_generate_concurrently(self):
        barrier = threading.Barrier(2, timeout=10)

        def reply(prompt, _):
            barrier.wait()  # Breaks (and fails the test) unless both branches are inside at once.
            return FIRST_ANSWER

        generator = FakeClaude(reply)
        body, *_ = self.post_compare(
            shared=self.retrieved([0, 1]), generator=generator,
            evaluator=self.evaluator_for({FIRST_ANSWER: self.evaluation(0, 0.95, 0.9)}),
        )

        self.assertFalse(barrier.broken)
        self.assertEqual(len(generator.threads), 2)
        for branch in (body["basic"], body["reli"]):
            self.assertEqual((branch["status"], branch["final_answer"], len(branch["attempts"])),
                             (ANSWERED, FIRST_ANSWER, 1))
            self.assertTrue(branch["attempts"][0]["evaluation"]["passed"])

    def test_failing_branch_does_not_affect_the_other(self):
        for error in (LLMError("overloaded"), TypeError("Could not resolve authentication")):
            with self.subTest(error=type(error).__name__):
                generator = FakeClaude(lambda _, number: error if number == 1 else FIRST_ANSWER)
                body, *_ = self.post_compare(
                    shared=self.retrieved([0, 1]), generator=generator,
                    evaluator=self.evaluator_for({FIRST_ANSWER: self.evaluation(0, 0.95, 0.9)}),
                )

                branches = sorted((body["basic"], body["reli"]), key=lambda b: b["status"])
                answered, failed = branches
                self.assertEqual((answered["status"], answered["final_answer"]),
                                 (ANSWERED, FIRST_ANSWER))
                self.assertTrue(answered["attempts"][0]["evaluation"]["passed"])
                self.assertEqual((failed["status"], failed["final_answer"]), (ERROR, ERROR_MESSAGE))
                self.assertEqual([(a["status"], a["evaluation"]) for a in failed["attempts"]],
                                 [(ERROR, None)])
                with self.Session() as db:
                    self.assertEqual(db.get(Query, failed["query_id"]).final_status, ERROR)

    def test_both_branches_failing_returns_502_and_records_both(self):
        generator = FakeClaude(lambda *_: LLMError("overloaded"))
        body, *_ = self.post_compare(shared=self.retrieved([0, 1]), generator=generator,
                                     evaluator=self.evaluator_for({}), expected_status=502)

        self.assertIn("Both comparison branches failed", body["detail"])
        queries = self.compare_queries()
        self.assertEqual([(q.mode, q.final_status) for q in queries],
                         [("basic", ERROR), ("reli", ERROR)])
        self.assertEqual(queries[0].options["compare_id"], queries[1].options["compare_id"])

    def test_invalid_request_is_rejected(self):
        for body in ({"question": "   "}, {"question": QUESTION, "k": 0}, {}):
            with self.subTest(body=body):
                response = self.client.post("/compare", json=body)
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.compare_queries(), [])

    # --- backward compatibility -----------------------------------------------------------

    def test_query_endpoint_still_retrieves_per_query_with_unchanged_options(self):
        for mode, keys in (("basic", BASIC_OPTION_KEYS), ("reli", BASIC_OPTION_KEYS | {"retry_k"})):
            with self.subTest(mode=mode):
                with patch("app.services.compare.retrieve") as shared_retrieve, \
                     patch("app.services.similarity_gate.retrieve",
                           return_value=self.retrieved([0, 1])) as gate_retrieve, \
                     patch("app.services.generator.call_claude",
                           new=FakeClaude(lambda *_: FIRST_ANSWER)), \
                     patch("app.services.evaluator.call_claude",
                           new=self.evaluator_for({FIRST_ANSWER: self.evaluation(0, 0.95, 0.9)})):
                    response = self.client.post("/query", json={"question": QUESTION,
                                                                "mode": mode})
                self.assertEqual(response.status_code, 200, response.text)
                shared_retrieve.assert_not_called()
                gate_retrieve.assert_called_once()
                with self.Session() as db:
                    query = db.get(Query, response.json()["query_id"])
                    self.assertEqual(set(query.options), keys)

    def test_injected_chunks_skip_retrieval_and_are_logged(self):
        with self.Session() as db, \
             patch("app.services.similarity_gate.retrieve") as retrieve:
            query = Query(question=QUESTION, mode="basic")
            db.add(query)
            db.commit()
            result = retrieve_with_gate(db, query, chunks=self.retrieved([1, 0]))
            retrieve.assert_not_called()
            self.assertTrue(result.passed)
            self.assertEqual([c.chunk_id for c in result.chunks],
                             [self.chunk_ids[1], self.chunk_ids[0]])
        self.assertEqual([chunk_id for chunk_id, _ in self.logged(query.id)],
                         [self.chunk_ids[1], self.chunk_ids[0]])

    def test_run_basic_query_defaults_to_its_own_retrieval(self):
        with self.Session() as db, \
             patch("app.services.similarity_gate.retrieve",
                   return_value=self.retrieved([0])) as retrieve, \
             patch("app.services.generator.call_claude", new=FakeClaude(lambda *_: FIRST_ANSWER)), \
             patch("app.services.evaluator.call_claude",
                   new=self.evaluator_for({FIRST_ANSWER: self.evaluation(0, 0.95, 0.9)})):
            query = run_basic_query(db, QUESTION, k=3)
            retrieve.assert_called_once()
            self.assertEqual(retrieve.call_args.kwargs, {"k": 3, "document_ids": None})
            self.assertEqual((query.final_status, query.final_attempt_number), (ANSWERED, None))


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
