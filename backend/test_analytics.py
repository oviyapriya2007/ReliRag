"""RELI-RAG Day 5 A2: offline tests for GET /analytics/summary.

Usage (from the project root or backend/):
    python backend/test_analytics.py

Offline: rows are inserted directly (or written by POST /query with every Claude caller and
retrieval mocked) into an in-memory SQLite database, so no API calls are made and the real
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

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Answer,
    Claim,
    Document,
    DocumentChunk,
    Evaluation,
    Query,
    RetrievalLog,
)
from app.services.analytics import build_summary  # noqa: E402
from app.services.corrector import REWRITE, STRICT  # noqa: E402
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
from app.services.llm import LLMResult  # noqa: E402
from app.services.query_pipeline import ERROR  # noqa: E402
from app.services.retrieval import RetrievedChunk  # noqa: E402
from app.services.similarity_gate import INSUFFICIENT_EVIDENCE  # noqa: E402

PINNED_SETTINGS = {
    "claude_model": "claude-test-model",
    "similarity_gate": 0.30,
    "evaluator_model": None,
    "evaluator_pass_threshold": 0.80,
    "evaluator_max_parse_attempts": 2,
}


def evaluation(scores=None, *, passed=True, failure_type=None, latency=None, claims=()):
    """Evaluation spec; `scores` is (faithfulness, answer_relevance, context_relevance)."""
    return {"scores": scores, "passed": passed, "failure_type": failure_type,
            "latency": latency, "claims": claims}


def attempt(status=ANSWERED, *, latency=None, strategy=None, chunks=(), evaluations=()):
    return {"status": status, "latency": latency, "strategy": strategy, "chunks": chunks,
            "evaluations": evaluations}


class AnalyticsTest(unittest.TestCase):
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
            first = Document(filename="first.pdf", total_pages=2, total_chunks=2)
            second = Document(filename="second.pdf", total_pages=1, total_chunks=1)
            chunks = [DocumentChunk(document=first, page_number=1, chunk_index=0,
                                    content="Item A is allowed after approval."),
                      DocumentChunk(document=first, page_number=2, chunk_index=1,
                                    content="Item A has an allowance of 200 units per year."),
                      DocumentChunk(document=second, page_number=1, chunk_index=0,
                                    content="Item B has an allowance of 50 units per year.")]
            db.add_all([first, second, *chunks])
            db.commit()
            self.documents = {"first": first.id, "second": second.id}
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

    def add_query(self, mode, final_status, attempts, *, final_attempt=None, run=None):
        with self.Session() as db:
            query = Query(question="q", mode=mode, final_status=final_status,
                          final_attempt_number=final_attempt, benchmark_run_id=run)
            for number, spec in enumerate(attempts, start=1):
                answer = Answer(query=query, attempt_number=number, status=spec["status"],
                                strategy=spec["strategy"], latency_ms=spec["latency"])
                answer.retrieval_logs = [
                    RetrievalLog(chunk_id=self.chunk_ids[index], rank=rank, similarity=0.8)
                    for rank, index in enumerate(spec["chunks"], start=1)
                ]
                for ev in spec["evaluations"]:
                    f, a, c = ev["scores"] or (None, None, None)
                    answer.evaluations.append(Evaluation(
                        faithfulness=f, answer_relevance=a, context_relevance=c,
                        passed=ev["passed"], failure_type=ev["failure_type"],
                        latency_ms=ev["latency"],
                        claims=[Claim(claim_text="c", verdict=v) for v in ev["claims"]],
                    ))
                db.add(answer)
            db.add(query)
            db.commit()

    def seed(self):
        """Seven queries covering every outcome; expected values are derived in the tests."""
        # 1. Basic, answered; re-evaluated: only the latest (passing) evaluation counts.
        self.add_query("basic", ANSWERED, [attempt(latency=100, chunks=[0, 2], evaluations=[
            evaluation((0.2, 0.2, 0.2), passed=False, failure_type=UNSUPPORTED_CLAIM,
                       latency=999, claims=[UNSUPPORTED, UNSUPPORTED]),
            evaluation((0.9, 0.9, 0.9), latency=50, claims=[SUPPORTED]),
        ])])
        # 2. Basic, rejected by the similarity gate: no Claude call.
        self.add_query("basic", INSUFFICIENT_EVIDENCE,
                       [attempt(INSUFFICIENT_EVIDENCE, chunks=[0])])
        # 3. RELI, attempt 1 passes: no correction.
        self.add_query("reli", ANSWERED, [attempt(latency=120, chunks=[0, 1], evaluations=[
            evaluation((1.0, 0.9, 0.8), latency=60)])], final_attempt=1, run="run-1")
        # 4. RELI, rewrite correction selected and passing.
        self.add_query("reli", ANSWERED, [
            attempt(latency=100, chunks=[2], evaluations=[evaluation(
                (1.0, 0.85, 0.3), passed=False, failure_type=IRRELEVANT_RETRIEVAL, latency=40,
                claims=[SUPPORTED])]),
            attempt(latency=110, strategy=REWRITE, chunks=[1, 2], evaluations=[
                evaluation((1.0, 0.95, 0.9), latency=45)]),
        ], final_attempt=2, run="run-1")
        # 5. RELI, strict correction rejected by the selector: attempt 1 kept.
        self.add_query("reli", ANSWERED, [
            attempt(latency=90, chunks=[0], evaluations=[evaluation(
                (0.5, 0.9, 0.9), passed=False, failure_type=UNSUPPORTED_CLAIM, latency=30,
                claims=[SUPPORTED, UNSUPPORTED])]),
            attempt(latency=80, strategy=STRICT, chunks=[0], evaluations=[evaluation(
                (0.4, 0.9, 0.9), passed=False, failure_type=UNSUPPORTED_CLAIM, latency=25,
                claims=[UNSUPPORTED, PARTIALLY_SUPPORTED])]),
        ], final_attempt=1)
        # 6. RELI, attempt 1 evaluator_error: unscored, so not eligible for correction.
        self.add_query("reli", ANSWERED, [attempt(latency=70, evaluations=[
            evaluation(passed=False, failure_type=EVALUATOR_ERROR, latency=20)])],
            final_attempt=1)
        # 7. RELI, correction triggered but its Claude call failed: attempt 1 kept.
        self.add_query("reli", ANSWERED, [
            attempt(latency=100, evaluations=[evaluation(
                (1.0, 0.5, 0.9), passed=False, failure_type=MISSING_INFO, latency=35)]),
            attempt(ERROR, strategy=REWRITE),
        ], final_attempt=1)

    def summary(self, **params) -> dict:
        response = self.client.get("/analytics/summary", params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def assert_scores(self, actual: dict, evaluations: int, expected):
        self.assertEqual(actual["evaluations"], evaluations)
        for name, value in zip(("faithfulness", "answer_relevance", "context_relevance",
                                "overall"), expected):
            if value is None:
                self.assertIsNone(actual[name], name)
            else:
                self.assertAlmostEqual(actual[name], value, places=9, msg=name)

    # --- empty data -----------------------------------------------------------------------

    def test_empty_database_returns_zeros_and_null_rates(self):
        body = self.summary()

        self.assertEqual((body["total_questions"], body["insufficient_evidence"],
                          body["unsupported_claims"], body["top_documents"]), (0, 0, 0, []))
        self.assertEqual(body["first_pass"], {"count": 0, "total": 0, "rate": None})
        self.assertEqual(body["corrections"], {
            "eligible": 0, "triggered": 0, "successful": 0, "failed_after_correction": 0,
            "trigger_rate": None, "success_rate": None})
        for mode in ("basic", "reli"):
            summary = body["by_mode"][mode]
            self.assertEqual(summary["questions"], 0)
            self.assert_scores(summary["first_attempt_scores"], 0, (None,) * 4)
            self.assert_scores(summary["final_scores"], 0, (None,) * 4)
            self.assertEqual(summary["latency"], {"queries": 0, "avg_generation_ms": None,
                                                  "avg_evaluation_ms": None,
                                                  "avg_total_ms": None})

    # --- seeded data ----------------------------------------------------------------------

    def test_question_counts_first_pass_and_insufficient_evidence(self):
        self.seed()
        body = self.summary()
        basic, reli = body["by_mode"]["basic"], body["by_mode"]["reli"]

        self.assertEqual((body["total_questions"], basic["questions"], reli["questions"]),
                         (7, 2, 5))
        # Usable attempt-1 evaluations: queries 1, 3, 4, 5, 7 (2 is unanswered, 6 errored).
        self.assertEqual(body["first_pass"], {"count": 2, "total": 5, "rate": 0.4})
        self.assertEqual(basic["first_pass"], {"count": 1, "total": 1, "rate": 1.0})
        self.assertEqual(reli["first_pass"], {"count": 1, "total": 4, "rate": 0.25})
        self.assertEqual((body["insufficient_evidence"], basic["insufficient_evidence"],
                          reli["insufficient_evidence"]), (1, 1, 0))

    def test_corrections(self):
        self.seed()
        corrections = self.summary()["corrections"]

        # Eligible: 4, 5, 7 failed attempt 1. Triggered: the same three have an attempt 2.
        # Successful: only query 4 reports a passing attempt 2.
        self.assertEqual(
            {key: corrections[key] for key in ("eligible", "triggered", "successful",
                                               "failed_after_correction", "trigger_rate")},
            {"eligible": 3, "triggered": 3, "successful": 1, "failed_after_correction": 2,
             "trigger_rate": 1.0})
        self.assertAlmostEqual(corrections["success_rate"], 1 / 3)

    def test_first_attempt_and_final_scores(self):
        self.seed()
        by_mode = self.summary()["by_mode"]

        basic_scores = (0.9, 0.9, 0.9, 0.9)
        self.assert_scores(by_mode["basic"]["first_attempt_scores"], 1, basic_scores)
        self.assert_scores(by_mode["basic"]["final_scores"], 1, basic_scores)
        # First attempts of 3, 4, 5, 7.
        first = [(1.0, 0.9, 0.8), (1.0, 0.85, 0.3), (0.5, 0.9, 0.9), (1.0, 0.5, 0.9)]
        # Reported attempts: 3 (1), 4 (2), 5 (1), 7 (1); 6 has no usable evaluation.
        final = [(1.0, 0.9, 0.8), (1.0, 0.95, 0.9), (0.5, 0.9, 0.9), (1.0, 0.5, 0.9)]
        for name, rows in (("first_attempt_scores", first), ("final_scores", final)):
            expected = [sum(column) / 4 for column in zip(*rows)]
            expected.append(sum(sum(row) / 3 for row in rows) / 4)
            self.assert_scores(by_mode["reli"][name], 4, expected)

    def test_unsupported_claims_use_latest_evaluations(self):
        self.seed()
        body = self.summary()

        # Query 1's older evaluation (2 unsupported) is superseded; query 5 has one per attempt.
        self.assertEqual(body["by_mode"]["basic"]["unsupported_claims"], 0)
        self.assertEqual((body["by_mode"]["reli"]["unsupported_claims"],
                          body["by_mode"]["reli"]["partially_supported_claims"]), (2, 1))
        self.assertEqual(body["unsupported_claims"], 2)

    def test_most_used_documents(self):
        self.seed()

        # first.pdf: q1 1, q2 1, q3 2, q4 1, q5 2 rows; second.pdf: q1 1, q4 2 rows.
        self.assertEqual(self.summary()["top_documents"], [
            {"document_id": self.documents["first"], "filename": "first.pdf",
             "retrievals": 7, "queries": 5},
            {"document_id": self.documents["second"], "filename": "second.pdf",
             "retrievals": 3, "queries": 2},
        ])
        self.assertEqual([d["filename"] for d in self.summary(top_documents=1)["top_documents"]],
                         ["first.pdf"])

    def test_latency_by_mode(self):
        self.seed()
        by_mode = self.summary()["by_mode"]

        # Basic: only query 1 called Claude (100 + latest evaluation 50; the old 999 is ignored).
        self.assertEqual(by_mode["basic"]["latency"], {
            "queries": 1, "avg_generation_ms": 100.0, "avg_evaluation_ms": 50.0,
            "avg_total_ms": 150.0})
        # RELI generation per query: 120, 210, 170, 70, 100; evaluation: 60, 85, 55, 20, 35.
        self.assertEqual(by_mode["reli"]["latency"], {
            "queries": 5, "avg_generation_ms": 134.0, "avg_evaluation_ms": 51.0,
            "avg_total_ms": 185.0})

    def test_benchmark_run_filter(self):
        self.seed()
        body = self.summary(benchmark_run_id="run-1")

        self.assertEqual((body["benchmark_run_id"], body["total_questions"],
                          body["by_mode"]["basic"]["questions"]), ("run-1", 2, 0))
        self.assertEqual(body["first_pass"], {"count": 1, "total": 2, "rate": 0.5})
        self.assertEqual((body["corrections"]["triggered"], body["corrections"]["successful"]),
                         (1, 1))
        self.assertEqual([(d["filename"], d["retrievals"], d["queries"])
                          for d in body["top_documents"]],
                         [("first.pdf", 3, 2), ("second.pdf", 2, 1)])
        self.assertEqual(self.summary(benchmark_run_id="missing")["total_questions"], 0)

    def test_invalid_parameters_are_rejected(self):
        for params in ({"top_documents": 0}, {"top_documents": 51},
                       {"benchmark_run_id": "x" * 65}):
            with self.subTest(params=params):
                response = self.client.get("/analytics/summary", params=params)
                self.assertEqual(response.status_code, 422, response.text)

    def test_service_matches_endpoint(self):
        self.seed()
        with self.Session() as db:
            self.assertEqual(build_summary(db).model_dump(mode="json"), self.summary())

    # --- rows written by the real pipeline ------------------------------------------------

    def test_summary_of_pipeline_written_queries(self):
        def retrieved(indexes, similarity=0.8):
            return [RetrievedChunk(chunk_id=self.chunk_ids[i], document_id=self.documents[
                "second" if i == 2 else "first"], document="doc.pdf", page=1, text=text,
                similarity=similarity) for i, text in indexes]

        def judged(index, quote, answer_relevance, context_relevance):
            claim = {"claim_text": quote, "verdict": SUPPORTED,
                     "evidence_chunk_id": self.chunk_ids[index], "evidence_quote": quote}
            return json.dumps({"claims": [claim], "answer_relevance": answer_relevance,
                               "context_relevance": context_relevance, "feedback": "Checked."})

        def llm(text):
            return LLMResult(text=text, model="claude-test-model", input_tokens=10,
                             output_tokens=5, latency_ms=7, stop_reason="end_turn", attempts=1)

        approval = (0, "Item A is allowed after approval.")
        allowance = (1, "Item A has an allowance of 200 units per year.")
        with patch("app.services.similarity_gate.retrieve", side_effect=[
                 retrieved([approval], similarity=0.1),          # basic: gate rejection
                 retrieved([approval]), retrieved([allowance])]), \
             patch("app.services.generator.call_claude", side_effect=[
                 llm("Item A is allowed after approval [1]."),
                 llm("Item A has an allowance of 200 units per year [1].")]), \
             patch("app.services.evaluator.call_claude", side_effect=[
                 llm(judged(0, approval[1], 0.85, 0.3)),         # irrelevant -> rewrite
                 llm(judged(1, allowance[1], 0.95, 0.9))]), \
             patch("app.services.corrector.call_claude",
                   return_value=llm("item A allowance per year")):
            for mode in ("basic", "reli"):
                response = self.client.post("/query", json={"question": "Item A allowance?",
                                                            "mode": mode})
                self.assertEqual(response.status_code, 200, response.text)

        body = self.summary()
        self.assertEqual((body["total_questions"], body["insufficient_evidence"]), (2, 1))
        self.assertEqual(body["first_pass"], {"count": 0, "total": 1, "rate": 0.0})
        self.assertEqual((body["corrections"]["triggered"], body["corrections"]["successful"],
                          body["corrections"]["success_rate"]), (1, 1, 1.0))
        reli = body["by_mode"]["reli"]
        self.assertAlmostEqual(reli["final_scores"]["context_relevance"], 0.9)
        self.assertAlmostEqual(reli["first_attempt_scores"]["context_relevance"], 0.3)
        self.assertEqual(reli["latency"]["avg_generation_ms"], 14.0)
        self.assertEqual(body["by_mode"]["basic"]["latency"]["queries"], 0)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
