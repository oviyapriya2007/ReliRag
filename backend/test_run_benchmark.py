"""RELI-RAG Day 5 A3: offline tests for scripts/run_benchmark.py and benchmark_run_id on /compare.

Usage (from the project root or backend/):
    python backend/test_run_benchmark.py

Offline: the script talks to an httpx.MockTransport (canned /compare responses), or to the
FastAPI app in-process with retrieval and every Claude caller replaced by fakes and a
temporary SQLite file as the database. No API calls are made and the real database is never
touched. Exits with status 0 when all tests pass, 1 otherwise.
"""

import contextlib
import csv
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

# Must be set before `app` is imported so the app never connects to the real database.
os.environ["DATABASE_URL"] = "sqlite://"

BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND.parent / "scripts"))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import run_benchmark as rb  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Document, DocumentChunk, Query  # noqa: E402
from app.services.evaluator import SUPPORTED  # noqa: E402
from app.services.llm import LLMResult  # noqa: E402
from app.services.retrieval import RetrievedChunk  # noqa: E402

RUN_ID = "bench-test-run"
QUESTIONS = [
    rb.BenchmarkQuestion("Q01", "What does policy one allow?", "clearly_covered", True),
    rb.BenchmarkQuestion("Q02", "What is the allowance for item A?", "partial", True),
    rb.BenchmarkQuestion("Q03", "Who won the 1998 final?", "out_of_scope", False),
]


# --- canned API responses -------------------------------------------------------------------


def evaluation(passed, scores=(0.9, 0.9, 0.9), verdicts=("supported",), failure_type=None):
    f, a, c = scores
    return {"faithfulness": f, "answer_relevance": a, "context_relevance": c, "passed": passed,
            "failure_type": failure_type, "feedback": "Checked.",
            "claims": [{"claim_text": "c", "verdict": v, "evidence_chunk_id": None,
                        "evidence_quote": None} for v in verdicts]}


def attempt(number, status="ANSWERED", *, answer="An answer [1].", strategy=None,
            evaluation=None, generate_ms=None, evaluate_ms=None):
    return {"attempt_number": number, "answer": answer, "retrieval_query": "q",
            "strategy": strategy, "status": status, "model": "m", "citations": [1],
            "retrieval": [], "evaluation": evaluation,
            "timings": {"retrieve_ms": None, "generate_ms": generate_ms,
                        "evaluate_ms": evaluate_ms, "input_tokens": None, "output_tokens": None}}


def branch(query_id, mode, attempts, *, status="ANSWERED", final_answer="An answer [1].",
           final_attempt_number=1):
    return {"query_id": query_id, "question": "q", "mode": mode,
            "created_at": "2026-10-15T05:00:00Z", "status": status,
            "final_answer": final_answer, "final_attempt_number": final_attempt_number,
            "attempts": attempts}


def compare_body(question, run_id, basic, reli, compare_id="c1"):
    return {"compare_id": compare_id, "benchmark_run_id": run_id, "question": question,
            "basic": basic, "reli": reli}


def corrected_body(question, run_id):
    """Basic fails; RELI-RAG's rewrite correction is reported and passes."""
    failing = evaluation(False, (1.0, 0.85, 0.3), ("supported", "unsupported"),
                         "irrelevant_retrieval")
    return compare_body(
        question, run_id,
        branch(1, "basic", [attempt(1, evaluation=failing, generate_ms=100, evaluate_ms=40)],
               final_answer="=SUM(A1) is the answer [1]."),
        branch(2, "reli", [
            attempt(1, evaluation=failing, generate_ms=110, evaluate_ms=50),
            attempt(2, answer="Better [1].", strategy="rewrite",
                    evaluation=evaluation(True, (1.0, 0.95, 0.9),
                                          ("supported", "partially_supported")),
                    generate_ms=120, evaluate_ms=60),
        ], final_answer="Better [1].", final_attempt_number=2),
        compare_id="c-corrected",
    )


def first_pass_body(question, run_id):
    passing = evaluation(True, (1.0, 0.9, 0.85))
    return compare_body(
        question, run_id,
        branch(3, "basic", [attempt(1, evaluation=passing, generate_ms=90, evaluate_ms=30)]),
        branch(4, "reli", [attempt(1, evaluation=passing, generate_ms=95, evaluate_ms=35)]),
        compare_id="c-first-pass",
    )


def gate_rejected_body(question, run_id):
    message = "I couldn't find enough evidence in the uploaded documents to answer this question."
    return compare_body(
        question, run_id,
        branch(5, "basic", [attempt(1, "INSUFFICIENT_EVIDENCE", answer=None)],
               status="INSUFFICIENT_EVIDENCE", final_answer=message),
        branch(6, "reli", [attempt(1, "INSUFFICIENT_EVIDENCE", answer=None)],
               status="INSUFFICIENT_EVIDENCE", final_answer=message),
        compare_id="c-gate",
    )


class MockApi:
    """httpx transport answering POST /compare per question text; records request payloads."""

    def __init__(self, responder):
        self.responder = responder
        self.payloads: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert (request.method, request.url.path) == ("POST", "/compare"), request.url
        payload = json.loads(request.content)
        self.payloads.append(payload)
        return self.responder(payload)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler),
                            base_url="http://benchmark.test")


def ok(body) -> httpx.Response:
    return httpx.Response(200, json=body)


def by_question(payload, run_id=RUN_ID):
    builders = {QUESTIONS[0].question: corrected_body, QUESTIONS[1].question: first_pass_body,
                QUESTIONS[2].question: gate_rejected_body}
    return ok(builders[payload["question"]](payload["question"], run_id))


# --- script tests with mocked HTTP ----------------------------------------------------------


class RunBenchmarkScriptTest(unittest.TestCase):
    def setUp(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.tmp = Path(tmpdir.name)
        self.questions_file = self.tmp / "benchmark.json"
        self.questions_file.write_text(json.dumps({"questions": [
            {"id": q.id, "category": q.category, "question": q.question,
             "answerable": q.answerable, "topics": ["t"]} for q in QUESTIONS]}), encoding="utf-8")

    def run_main(self, *args, api=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        client = api.client() if api else None
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = rb.main(["--questions", str(self.questions_file), *args], client=client)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_repository_benchmark_file_loads(self):
        questions = rb.load_questions(rb.DEFAULT_QUESTIONS)
        self.assertEqual(len(questions), 20)
        self.assertEqual(len({q.id for q in questions}), 20)
        self.assertTrue(all(q.question and q.category for q in questions))

    def test_invalid_benchmark_files_are_rejected(self):
        cases = {
            "not json": "{",
            "no questions": json.dumps({"questions": []}),
            "missing question": json.dumps({"questions": [{"id": "Q1"}]}),
            "duplicate id": json.dumps({"questions": [{"id": "Q1", "question": "a"},
                                                      {"id": "Q1", "question": "b"}]}),
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.questions_file.write_text(text, encoding="utf-8")
                with self.assertRaises(rb.BenchmarkFileError):
                    rb.load_questions(self.questions_file)
                code, _, stderr = self.run_main("--yes")
                self.assertEqual(code, 2)
                self.assertIn("error:", stderr)

    def test_successful_run_rows(self):
        api = MockApi(by_question)
        with api.client() as client:
            rows = rb.run_benchmark(client, QUESTIONS, RUN_ID, k=4, document_ids=[8])

        self.assertEqual([p["benchmark_run_id"] for p in api.payloads], [RUN_ID] * 3)
        self.assertEqual(api.payloads[0], {"question": QUESTIONS[0].question,
                                           "benchmark_run_id": RUN_ID, "k": 4,
                                           "document_ids": [8]})
        corrected, first_pass, gate = rows
        for row in rows:
            self.assertEqual((row["http_status"], row["error"], row["benchmark_run_id"]),
                             (200, None, RUN_ID))
        self.assertEqual((corrected["question_id"], corrected["category"],
                          corrected["answerable"], corrected["compare_id"]),
                         ("Q01", "clearly_covered", True, "c-corrected"))
        self.assertEqual(
            {k: corrected[k] for k in ("basic_status", "basic_faithfulness",
                                       "basic_context_relevance", "basic_passed",
                                       "basic_failure_type", "basic_supported_claims",
                                       "basic_unsupported_claims", "basic_latency_ms")},
            {"basic_status": "ANSWERED", "basic_faithfulness": 1.0,
             "basic_context_relevance": 0.3, "basic_passed": False,
             "basic_failure_type": "irrelevant_retrieval", "basic_supported_claims": 1,
             "basic_unsupported_claims": 1, "basic_latency_ms": 140})
        # RELI scores and claims are the reported (final) attempt's; latency covers both.
        self.assertEqual(
            {k: corrected[k] for k in ("reli_answer", "reli_final_attempt", "reli_attempts",
                                       "reli_answer_relevance", "reli_passed",
                                       "reli_partially_supported_claims",
                                       "reli_unsupported_claims", "reli_latency_ms",
                                       "reli_correction_strategy", "reli_correction_outcome")},
            {"reli_answer": "Better [1].", "reli_final_attempt": 2, "reli_attempts": 2,
             "reli_answer_relevance": 0.95, "reli_passed": True,
             "reli_partially_supported_claims": 1, "reli_unsupported_claims": 0,
             "reli_latency_ms": 340, "reli_correction_strategy": "rewrite",
             "reli_correction_outcome": "successful"})
        self.assertEqual((first_pass["reli_correction_outcome"], first_pass["basic_passed"]),
                         ("not_needed", True))
        self.assertEqual((gate["basic_status"], gate["reli_status"], gate["basic_passed"],
                          gate["basic_latency_ms"], gate["reli_correction_outcome"]),
                         ("INSUFFICIENT_EVIDENCE", "INSUFFICIENT_EVIDENCE", None, None,
                          "not_triggered"))

    def test_correction_outcomes(self):
        failing = evaluation(False, failure_type="missing_info")
        kept = branch(1, "reli", [attempt(1, evaluation=failing),
                                  attempt(2, strategy="strict", evaluation=failing)])
        improved = branch(1, "reli", [attempt(1, evaluation=failing),
                                      attempt(2, strategy="rewrite", evaluation=failing)],
                          final_attempt_number=2)
        errored = branch(1, "reli", [attempt(1, "ERROR", answer=None)], status="ERROR")
        self.assertEqual(rb.correction_outcome(kept), ("strict", "failed"))
        self.assertEqual(rb.correction_outcome(improved), ("rewrite", "improved"))
        self.assertEqual(rb.correction_outcome(errored), (None, "not_triggered"))
        self.assertEqual(rb.correction_outcome(None), (None, None))

    def test_api_errors_are_recorded_and_the_run_continues(self):
        def responder(payload):
            question = payload["question"]
            if question == QUESTIONS[0].question:
                return httpx.Response(502, json={"detail": "Both comparison branches failed: x"})
            if question == QUESTIONS[1].question:
                raise httpx.ConnectError("connection refused")
            return httpx.Response(422, json={"detail": [{"loc": ["body", "k"], "msg": "bad"}]})

        api = MockApi(responder)
        code, stdout, _ = self.run_main("--yes", "--run-id", RUN_ID,
                                        "--output", str(self.tmp / "r.csv"), api=api)

        self.assertEqual(code, 1)
        self.assertEqual(len(api.payloads), 3)
        with (self.tmp / "r.csv").open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([(r["question_id"], r["http_status"]) for r in rows],
                         [("Q01", "502"), ("Q02", ""), ("Q03", "422")])
        self.assertEqual(rows[0]["error"], "HTTP 502: Both comparison branches failed: x")
        self.assertEqual(rows[1]["error"], "ConnectError: connection refused")
        self.assertIn("HTTP 422", rows[2]["error"])
        for row in rows:
            self.assertEqual((row["basic_status"], row["reli_status"]), ("", ""))
        self.assertIn("0/3 questions compared, 3 error(s)", stdout)

    def test_malformed_or_unconfirmed_responses_are_errors(self):
        responses = {QUESTIONS[0].question: httpx.Response(200, json=["not", "an", "object"]),
                     QUESTIONS[1].question: httpx.Response(200, text="not json"),
                     QUESTIONS[2].question: ok(gate_rejected_body("q", None))}
        api = MockApi(lambda payload: responses[payload["question"]])
        with api.client() as client:
            rows = rb.run_benchmark(client, QUESTIONS, RUN_ID)

        self.assertEqual(rows[0]["error"], "Unexpected response: not a JSON object")
        self.assertTrue(rows[1]["error"].startswith("Invalid JSON response"))
        # An API that ignores benchmark_run_id would not tag the queries for analytics.
        self.assertIn("did not confirm benchmark_run_id", rows[2]["error"])

    def test_csv_output_and_printed_summary(self):
        output = self.tmp / "out" / "results.csv"
        api = MockApi(by_question)
        code, stdout, _ = self.run_main("--yes", "--run-id", RUN_ID, "--output", str(output),
                                        api=api)

        self.assertEqual(code, 0)
        with output.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(tuple(reader.fieldnames), rb.CSV_FIELDS)
            rows = list(reader)
        self.assertEqual([r["question_id"] for r in rows], ["Q01", "Q02", "Q03"])
        corrected = rows[0]
        self.assertEqual((corrected["benchmark_run_id"], corrected["category"],
                          corrected["answerable"], corrected["reli_answer"],
                          corrected["reli_faithfulness"], corrected["reli_correction_outcome"],
                          corrected["error"]),
                         (RUN_ID, "clearly_covered", "True", "Better [1].", "1.0",
                          "successful", ""))
        # Answers that look like spreadsheet formulas are neutralized.
        self.assertEqual(corrected["basic_answer"], "'=SUM(A1) is the answer [1].")
        self.assertEqual(rows[2]["basic_faithfulness"], "")

        self.assertIn("ID      Category", stdout)
        self.assertIn("3/3 questions compared, 0 error(s)", stdout)
        self.assertIn("Basic RAG: 1/2 final answers passed; avg Claude latency 130 ms", stdout)
        self.assertIn("RELI-RAG:  2/2 final answers passed; avg Claude latency 235 ms", stdout)
        self.assertIn("Corrections: 1 triggered, 1 successful", stdout)
        self.assertIn(f"/analytics/summary?benchmark_run_id={RUN_ID}", stdout)

    def test_question_selection(self):
        api = MockApi(by_question)
        code, _, _ = self.run_main("--yes", "--ids", "Q03", "Q01", "--run-id", RUN_ID,
                                   "--output", str(self.tmp / "r.csv"), api=api)
        self.assertEqual(code, 0)
        self.assertEqual([p["question"] for p in api.payloads],
                         [QUESTIONS[0].question, QUESTIONS[2].question])

        api = MockApi(by_question)
        self.run_main("--yes", "--limit", "1", "--run-id", RUN_ID,
                      "--output", str(self.tmp / "r.csv"), api=api)
        self.assertEqual(len(api.payloads), 1)
        self.assertEqual(self.run_main("--yes", "--ids", "Q99")[0], 2)

    def test_plan_only_without_yes_makes_no_requests(self):
        api = MockApi(by_question)
        output = self.tmp / "results.csv"
        code, stdout, _ = self.run_main("--output", str(output), api=api)

        self.assertEqual(code, 0)
        self.assertEqual(api.payloads, [])
        self.assertFalse(output.exists())
        self.assertIn("Re-run with --yes", stdout)

    def test_run_ids(self):
        run_id = rb.new_run_id(datetime(2026, 10, 15, 5, 30, tzinfo=timezone.utc))
        self.assertTrue(run_id.startswith("bench-20261015-053000-"))
        self.assertRegex(run_id, rb.RUN_ID_RE)
        self.assertNotEqual(rb.new_run_id(), rb.new_run_id())
        code, _, stderr = self.run_main("--yes", "--run-id", "bad id!")
        self.assertEqual(code, 2)
        self.assertIn("--run-id", stderr)


# --- run-ID propagation through the real API ------------------------------------------------


def llm(text: str) -> LLMResult:
    return LLMResult(text=text, model="claude-test-model", input_tokens=10, output_tokens=5,
                     latency_ms=7, stop_reason="end_turn", attempts=1)


class RunIdPropagationTest(unittest.TestCase):
    CHUNK = "Members may request item A after approval."
    ANSWER = "Members may request item A after approval [1]."

    def setUp(self):
        for name, value in {"claude_model": "claude-test-model", "similarity_gate": 0.30,
                            "evaluator_model": None, "evaluator_pass_threshold": 0.80,
                            "evaluator_max_parse_attempts": 2}.items():
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.tmp = Path(tmpdir.name)
        # A file, so /compare's concurrent branch sessions get their own connections.
        engine = create_engine(f"sqlite:///{self.tmp / 'bench.db'}",
                               connect_args={"check_same_thread": False, "timeout": 30})
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        self.Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with self.Session() as db:
            document = Document(filename="policies.pdf", total_pages=1, total_chunks=1)
            chunk = DocumentChunk(document=document, page_number=1, chunk_index=0,
                                  content=self.CHUNK)
            db.add_all([document, chunk])
            db.commit()
            self.chunk = RetrievedChunk(chunk_id=chunk.id, document_id=document.id,
                                        document="policies.pdf", page=1, text=self.CHUNK,
                                        similarity=0.8)

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

        judged = json.dumps({"claims": [{"claim_text": self.CHUNK, "verdict": SUPPORTED,
                                         "evidence_chunk_id": self.chunk.chunk_id,
                                         "evidence_quote": self.CHUNK}],
                             "answer_relevance": 0.95, "context_relevance": 0.9,
                             "feedback": "Checked."})
        for target, replacement in (
            ("app.services.compare.retrieve", lambda *a, **k: [self.chunk]),
            ("app.services.similarity_gate.retrieve", lambda *a, **k: [self.chunk]),
            ("app.services.generator.call_claude", lambda *a, **k: llm(self.ANSWER)),
            ("app.services.evaluator.call_claude", lambda *a, **k: llm(judged)),
        ):
            patcher = patch(target, new=replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_script_run_id_is_stored_and_filters_analytics(self):
        questions_file = self.tmp / "benchmark.json"
        questions_file.write_text(json.dumps({"questions": [
            {"id": "Q01", "question": "What may members request?"},
            {"id": "Q02", "question": "When may item A be requested?"}]}), encoding="utf-8")
        # Earlier, unrelated traffic that the run's analytics must not include.
        self.assertEqual(self.client.post("/query", json={"question": "Other?"}).status_code, 200)
        self.assertEqual(self.client.post("/compare", json={"question": "Other?"}).status_code,
                         200)

        output = self.tmp / "results.csv"
        with contextlib.redirect_stdout(io.StringIO()):
            code = rb.main(["--questions", str(questions_file), "--yes", "--run-id", RUN_ID,
                            "--output", str(output)], client=self.client)
        self.assertEqual(code, 0)

        with self.Session() as db:
            tagged = [(q.mode, q.question, q.benchmark_run_id)
                      for q in db.scalars(select(Query).order_by(Query.id))]
        self.assertEqual(tagged, [
            ("basic", "Other?", None), ("basic", "Other?", None), ("reli", "Other?", None),
            ("basic", "What may members request?", RUN_ID),
            ("reli", "What may members request?", RUN_ID),
            ("basic", "When may item A be requested?", RUN_ID),
            ("reli", "When may item A be requested?", RUN_ID),
        ])

        run = self.client.get("/analytics/summary", params={"benchmark_run_id": RUN_ID}).json()
        self.assertEqual((run["benchmark_run_id"], run["total_questions"],
                          run["by_mode"]["basic"]["questions"],
                          run["by_mode"]["reli"]["questions"]), (RUN_ID, 4, 2, 2))
        self.assertEqual(run["first_pass"], {"count": 4, "total": 4, "rate": 1.0})
        self.assertEqual(self.client.get("/analytics/summary").json()["total_questions"], 7)

        with output.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([(r["question_id"], r["benchmark_run_id"], r["basic_status"],
                           r["reli_status"], r["reli_correction_outcome"]) for r in rows],
                         [("Q01", RUN_ID, "ANSWERED", "ANSWERED", "not_needed"),
                          ("Q02", RUN_ID, "ANSWERED", "ANSWERED", "not_needed")])

    def test_compare_without_run_id_is_unchanged_and_invalid_ids_are_rejected(self):
        response = self.client.post("/compare", json={"question": "Other?"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["benchmark_run_id"])

        for bad in ("", "has space", "x" * 65):
            with self.subTest(bad=bad):
                response = self.client.post("/compare", json={"question": "Other?",
                                                              "benchmark_run_id": bad})
                self.assertEqual(response.status_code, 422, response.text)
        with self.Session() as db:
            self.assertEqual([q.benchmark_run_id for q in db.scalars(select(Query))],
                             [None, None])


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
