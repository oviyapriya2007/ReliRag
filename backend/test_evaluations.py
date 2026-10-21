"""RELI-RAG Day 5 A4: offline tests for GET /evaluations and GET /evaluations/export.csv.

Usage (from the project root or backend/):
    python backend/test_evaluations.py

Offline: rows are inserted directly into an in-memory SQLite database, so no Claude, embedding,
or real database call is made. Exits with status 0 when all tests pass, 1 otherwise.
"""

import csv
import io
import os
import sys
import unittest
from pathlib import Path

# Must be set before `app` is imported so the app never connects to the real database.
os.environ["DATABASE_URL"] = "sqlite://"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

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
from app.routers.evaluations import CSV_FIELDS, MAX_PAGE_SIZE  # noqa: E402
from app.services.corrector import REWRITE  # noqa: E402
from app.services.evaluator import (  # noqa: E402
    EVALUATOR_ERROR,
    IRRELEVANT_RETRIEVAL,
    PARTIALLY_SUPPORTED,
    SUPPORTED,
    UNSUPPORTED,
    UNSUPPORTED_CLAIM,
)
from app.services.generator import ANSWERED  # noqa: E402


class EvaluationsEndpointTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        self.Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

        with self.Session() as db:
            policy = Document(filename="policy.pdf", total_pages=2, total_chunks=2)
            hostile = Document(filename="=HYPERLINK(\"http://x\").pdf", total_pages=1,
                               total_chunks=1)
            chunks = [DocumentChunk(document=policy, page_number=1, chunk_index=0, content="a"),
                      DocumentChunk(document=policy, page_number=2, chunk_index=1, content="b"),
                      DocumentChunk(document=hostile, page_number=1, chunk_index=0, content="c")]
            db.add_all([policy, hostile, *chunks])
            db.commit()
            self.policy, self.hostile = policy.id, hostile.id
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

    def add_answer(self, question=None, *, mode="basic", run=None, attempt=1, final_attempt=None,
                   strategy=None, chunks=(), answer_text="Answer [1].", query_id=None):
        """Store an answer (and its query unless given); returns (query_id, answer_id)."""
        with self.Session() as db:
            if query_id is None:
                query = Query(question=question, mode=mode, final_status=ANSWERED,
                              final_attempt_number=final_attempt, benchmark_run_id=run)
                db.add(query)
                db.flush()
                query_id = query.id
            answer = Answer(query_id=query_id,
                            attempt_number=attempt, strategy=strategy, status=ANSWERED,
                            answer_text=answer_text)
            answer.retrieval_logs = [RetrievalLog(chunk_id=self.chunk_ids[index], rank=rank,
                                                  similarity=0.8)
                                     for rank, index in enumerate(chunks, start=1)]
            db.add(answer)
            db.commit()
            return answer.query_id, answer.id

    def add_evaluation(self, answer_id, *, passed, failure_type=None, scores=(0.9, 0.9, 0.9),
                       verdicts=(), feedback="Checked.") -> int:
        with self.Session() as db:
            f, a, c = scores
            evaluation = Evaluation(
                answer_id=answer_id, faithfulness=f, answer_relevance=a, context_relevance=c,
                passed=passed, failure_type=failure_type, feedback=feedback,
                model="claude-test-model", latency_ms=40, input_tokens=100, output_tokens=20,
                claims=[Claim(claim_text=f"claim {i}", verdict=verdict,
                              evidence_chunk_id=self.chunk_ids[0], evidence_quote="a")
                        for i, verdict in enumerate(verdicts)],
            )
            db.add(evaluation)
            db.commit()
            return evaluation.id

    def seed(self):
        """Five answers (six evaluations: one answer is re-evaluated); returns evaluation ids.

        Retrieval: policy.pdf holds chunks 0-1, the formula-named document chunk 2.
        """
        ids = {}
        # Basic, re-evaluated: the first (failed) evaluation is superseded by a pass.
        _, answer = self.add_answer("Allowance for item A?", chunks=[0, 2])
        ids["superseded"] = self.add_evaluation(
            answer, passed=False, failure_type=UNSUPPORTED_CLAIM, scores=(0.2, 0.9, 0.9),
            verdicts=[UNSUPPORTED])
        ids["reevaluated"] = self.add_evaluation(answer, passed=True,
                                                 verdicts=[SUPPORTED, SUPPORTED])
        # RELI attempt 1 fails (policy.pdf only), attempt 2 rewrites and passes (both docs).
        query, answer = self.add_answer("Who approves item B?", mode="reli", run="run-1",
                                        final_attempt=2, chunks=[1])
        ids["reli_first"] = self.add_evaluation(
            answer, passed=False, failure_type=IRRELEVANT_RETRIEVAL, scores=(1.0, 0.8, 0.2),
            verdicts=[SUPPORTED, PARTIALLY_SUPPORTED])
        _, answer = self.add_answer(query_id=query, attempt=2, strategy=REWRITE, chunks=[2, 1])
        ids["reli_second"] = self.add_evaluation(answer, passed=True, verdicts=[SUPPORTED])
        # Basic with an evaluator failure and no retrieval.
        _, answer = self.add_answer("Unrelated?")
        ids["error"] = self.add_evaluation(answer, passed=False, failure_type=EVALUATOR_ERROR,
                                           scores=(None, None, None),
                                           feedback="Evaluation failed: timeout")
        # Basic with spreadsheet-formula text everywhere.
        _, answer = self.add_answer("=1+2", chunks=[2], answer_text="@SUM(A1:A9)")
        ids["formula"] = self.add_evaluation(answer, passed=False,
                                             failure_type=UNSUPPORTED_CLAIM,
                                             verdicts=[UNSUPPORTED], feedback="-2+3")
        return ids

    def list_evaluations(self, **params) -> dict:
        response = self.client.get("/evaluations", params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def export(self, **params) -> list[dict]:
        response = self.client.get("/evaluations/export.csv", params=params)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        self.assertEqual(response.headers["content-disposition"],
                         'attachment; filename="evaluations.csv"')
        reader = csv.DictReader(io.StringIO(response.text))
        self.assertEqual(tuple(reader.fieldnames), CSV_FIELDS)
        return list(reader)

    def ids(self, body) -> list[int]:
        return [item["evaluation_id"] for item in body["items"]]

    # --- listing --------------------------------------------------------------------------

    def test_empty_database(self):
        self.assertEqual(self.list_evaluations(),
                         {"total": 0, "limit": 50, "offset": 0, "items": []})

    def test_default_lists_latest_evaluations_newest_first(self):
        ids = self.seed()
        body = self.list_evaluations()

        # Every attempt is listed once; only the superseded first evaluation is left out.
        self.assertEqual(body["total"], 5)
        self.assertEqual(self.ids(body), [ids["formula"], ids["error"], ids["reli_second"],
                                          ids["reli_first"], ids["reevaluated"]])
        self.assertTrue(all(item["is_latest"] for item in body["items"]))

    def test_item_joins_query_attempt_claims_and_documents(self):
        ids = self.seed()
        item = next(item for item in self.list_evaluations()["items"]
                    if item["evaluation_id"] == ids["reli_second"])

        self.assertEqual(
            {key: item[key] for key in ("question", "mode", "benchmark_run_id", "final_status",
                                        "final_attempt_number", "attempt_number", "strategy",
                                        "answer_status", "status", "passed", "failure_type",
                                        "model", "latency_ms", "is_latest")},
            {"question": "Who approves item B?", "mode": "reli", "benchmark_run_id": "run-1",
             "final_status": ANSWERED, "final_attempt_number": 2, "attempt_number": 2,
             "strategy": REWRITE, "answer_status": ANSWERED, "status": "passed", "passed": True,
             "failure_type": None, "model": "claude-test-model", "latency_ms": 40,
             "is_latest": True})
        # Ranked by the attempt's retrieval: chunk 2 (hostile) first, then chunk 1 (policy).
        self.assertEqual([d["document_id"] for d in item["documents"]],
                         [self.hostile, self.policy])
        # Claims saved without verification details (as before they were recorded) return null.
        self.assertEqual(item["claims"], [{"claim_text": "claim 0", "verdict": SUPPORTED,
                                           "evidence_chunk_id": self.chunk_ids[0],
                                           "evidence_quote": "a", "claude_verdict": None,
                                           "evidence_error": None, "check_name": None,
                                           "claude_evidence_chunk_id": None,
                                           "claude_evidence_quote": None}])

    def test_latest_only_false_includes_superseded_evaluations(self):
        ids = self.seed()
        body = self.list_evaluations(latest_only="false")

        self.assertEqual(body["total"], 6)
        latest = {item["evaluation_id"]: item["is_latest"] for item in body["items"]}
        self.assertFalse(latest[ids["superseded"]])
        self.assertTrue(latest[ids["reevaluated"]])

    def test_status_filter(self):
        ids = self.seed()
        expected = {
            "passed": [ids["reli_second"], ids["reevaluated"]],
            "failed": [ids["formula"], ids["reli_first"]],
            "evaluator_error": [ids["error"]],
        }
        for status, evaluation_ids in expected.items():
            with self.subTest(status=status):
                body = self.list_evaluations(status=status)
                self.assertEqual((body["total"], self.ids(body)),
                                 (len(evaluation_ids), evaluation_ids))
                self.assertTrue(all(item["status"] == status for item in body["items"]))

        failed_all = self.list_evaluations(status="failed", latest_only="false")
        self.assertEqual(self.ids(failed_all),
                         [ids["formula"], ids["reli_first"], ids["superseded"]])

    def test_document_filter_uses_each_attempts_retrieval(self):
        ids = self.seed()

        self.assertEqual(self.ids(self.list_evaluations(document_id=self.policy)),
                         [ids["reli_second"], ids["reli_first"], ids["reevaluated"]])
        self.assertEqual(self.ids(self.list_evaluations(document_id=self.hostile)),
                         [ids["formula"], ids["reli_second"], ids["reevaluated"]])
        all_policy = self.list_evaluations(document_id=self.policy, latest_only="false")
        self.assertEqual(self.ids(all_policy),
                         [ids["reli_second"], ids["reli_first"], ids["reevaluated"],
                          ids["superseded"]])

    def test_combined_filters_and_empty_matches(self):
        ids = self.seed()

        failed_hostile = self.list_evaluations(status="failed", document_id=self.hostile)
        self.assertEqual(self.ids(failed_hostile), [ids["formula"]])
        error_policy = self.list_evaluations(status="evaluator_error", document_id=self.policy)
        self.assertEqual(error_policy["items"], [])
        self.assertEqual(self.list_evaluations(document_id=999_999),
                         {"total": 0, "limit": 50, "offset": 0, "items": []})

    def test_pagination(self):
        ids = self.seed()
        newest_first = [ids["formula"], ids["error"], ids["reli_second"], ids["reli_first"],
                        ids["reevaluated"]]

        first = self.list_evaluations(limit=3)
        second = self.list_evaluations(limit=3, offset=3)
        self.assertEqual((first["total"], first["limit"], first["offset"], self.ids(first)),
                         (5, 3, 0, newest_first[:3]))
        self.assertEqual((second["total"], second["offset"], self.ids(second)),
                         (5, 3, newest_first[3:]))
        self.assertEqual(self.ids(self.list_evaluations(limit=1, offset=1, status="passed")),
                         [ids["reevaluated"]])
        past_end = self.list_evaluations(offset=10)
        self.assertEqual((past_end["total"], past_end["items"]), (5, []))

    def test_invalid_parameters_are_rejected(self):
        shared = ({"status": "bogus"}, {"status": "PASSED"}, {"document_id": 0},
                  {"document_id": "abc"}, {"latest_only": "maybe"})
        paging = ({"limit": 0}, {"limit": MAX_PAGE_SIZE + 1}, {"offset": -1},
                  {"limit": "ten"})
        for path, cases in (("/evaluations", shared + paging),
                            ("/evaluations/export.csv", shared)):
            for params in cases:
                with self.subTest(path=path, params=params):
                    response = self.client.get(path, params=params)
                    self.assertEqual(response.status_code, 422, response.text)

    # --- CSV export -----------------------------------------------------------------------

    def test_export_empty_database_has_only_headers(self):
        self.assertEqual(self.export(), [])

    def test_export_matches_listing_for_every_filter(self):
        self.seed()
        for params in ({}, {"latest_only": "false"}, {"status": "passed"},
                       {"status": "failed", "latest_only": "false"},
                       {"document_id": self.policy}, {"status": "evaluator_error",
                                                      "document_id": self.policy}):
            with self.subTest(params=params):
                listed = self.ids(self.list_evaluations(limit=MAX_PAGE_SIZE, **params))
                exported = [int(row["evaluation_id"]) for row in self.export(**params)]
                self.assertEqual(exported, listed)

    def test_export_row_values(self):
        ids = self.seed()
        rows = {int(row["evaluation_id"]): row for row in self.export(latest_only="false")}

        first = rows[ids["reli_first"]]
        self.assertEqual(
            {key: first[key] for key in ("mode", "benchmark_run_id", "attempt_number",
                                         "strategy", "status", "passed", "failure_type",
                                         "faithfulness", "context_relevance",
                                         "supported_claims", "partially_supported_claims",
                                         "unsupported_claims", "total_claims", "document_ids",
                                         "documents", "is_latest")},
            {"mode": "reli", "benchmark_run_id": "run-1", "attempt_number": "1",
             "strategy": "", "status": "failed", "passed": "false",
             "failure_type": IRRELEVANT_RETRIEVAL, "faithfulness": "1.0",
             "context_relevance": "0.2", "supported_claims": "1",
             "partially_supported_claims": "1", "unsupported_claims": "0",
             "total_claims": "2", "document_ids": str(self.policy), "documents": "policy.pdf",
             "is_latest": "true"})
        self.assertEqual(rows[ids["superseded"]]["is_latest"], "false")
        error = rows[ids["error"]]
        self.assertEqual((error["status"], error["faithfulness"], error["document_ids"],
                          error["total_claims"]), ("evaluator_error", "", "", "0"))

    def test_export_neutralises_formula_injection(self):
        ids = self.seed()
        rows = {int(row["evaluation_id"]): row for row in self.export()}

        formula = rows[ids["formula"]]
        self.assertEqual(formula["question"], "'=1+2")
        self.assertEqual(formula["answer"], "'@SUM(A1:A9)")
        self.assertEqual(formula["feedback"], "'-2+3")
        self.assertEqual(formula["documents"], "'=HYPERLINK(\"http://x\").pdf")
        # Numbers and safe text are written unchanged.
        self.assertEqual((formula["faithfulness"], rows[ids["error"]]["feedback"]),
                         ("0.9", "Evaluation failed: timeout"))
        for row in rows.values():
            for field, value in row.items():
                with self.subTest(evaluation=row["evaluation_id"], field=field):
                    self.assertFalse(value.startswith(("=", "+", "-", "@", "\t", "\r")), value)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
