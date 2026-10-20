"""RELI-RAG Day 2-4: status handling and evaluation persistence for POST /query and later attempts.

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
os.environ.update({"EVALUATOR_MODEL": "", "EVALUATOR_MAX_TOKENS": "2048",
                   "EVALUATOR_PASS_THRESHOLD": "0.80", "EVALUATOR_MAX_PARSE_ATTEMPTS": "2"})

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import selectinload, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Answer, Document, DocumentChunk, Evaluation, Query  # noqa: E402
from app.routers.query import GATE_FAILED_MESSAGE, NOT_SUPPORTED_MESSAGE  # noqa: E402
from app.services.evaluator import (  # noqa: E402
    EVALUATOR_ERROR,
    IRRELEVANT_RETRIEVAL,
    SUPPORTED,
    UNSUPPORTED,
    UNSUPPORTED_CLAIM,
    evaluate_answer,
)
from app.services.generator import ANSWERED  # noqa: E402
from app.services.llm import LLMError, LLMResult  # noqa: E402
from app.services.query_pipeline import ERROR, run_attempt  # noqa: E402
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
                "claude_verdict": SUPPORTED,
                "evidence_error": None,
                "check_name": None,
            }],
        })
        self.assertEqual((saved_claim.claude_verdict, saved_claim.evidence_error,
                          saved_claim.check_name), (SUPPORTED, None, None))
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

    def test_pipeline_passes_evaluator_settings(self):
        with patch.object(settings, "evaluator_pass_threshold", 0.95), \
             patch.object(settings, "evaluator_max_tokens", 3000), \
             patch.object(settings, "evaluator_model", "eval-model"), \
             patch("app.services.query_pipeline.evaluate_answer",
                   wraps=evaluate_answer) as spy:
            body, claude, evaluator = self.post_query(0.9, ANSWER_TEXT)

        self.assertEqual(spy.call_args.kwargs["threshold"], 0.95)
        self.assertEqual(evaluator.call_args.kwargs["model"], "eval-model")
        self.assertEqual(evaluator.call_args.kwargs["max_tokens"], 3000)
        self.assertIsNone(claude.call_args.kwargs.get("model"))
        self.assert_status_consistent(body, ANSWERED)
        [evaluation] = self.saved_evaluations(body["query_id"])
        self.assertFalse(evaluation.passed)
        self.assertEqual(evaluation.failure_type, IRRELEVANT_RETRIEVAL)
        self.assertEqual(body["attempts"][0]["evaluation"]["failure_type"], IRRELEVANT_RETRIEVAL)

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

    def test_claude_error_marks_query_and_attempt_error(self):
        with patch("app.services.similarity_gate.retrieve", return_value=self.retrieved(0.9)), \
             patch("app.services.generator.call_claude", side_effect=LLMError("overloaded")), \
             patch("app.services.evaluator.call_claude") as evaluator:
            response = self.client.post("/query", json={"question": "What is TCP?"})

        self.assertEqual(response.status_code, 502, response.text)
        evaluator.assert_not_called()
        with self.Session() as db:
            query = db.scalars(select(Query)).one()
            answers = db.scalars(select(Answer).where(Answer.query_id == query.id)).all()
            self.assertEqual(query.final_status, ERROR)
            self.assertEqual([(a.attempt_number, a.status) for a in answers], [(1, ERROR)])
        self.assertEqual(self.saved_evaluations(query.id), [])

    def test_inline_refusal_token_is_removed_from_an_answer(self):
        cases = {
            f"{ANSWER_TEXT} Its history is not covered [INSUFFICIENT_EVIDENCE].":
                f"{ANSWER_TEXT} Its history is not covered.",
            f"{ANSWER_TEXT} Its history is **INSUFFICIENT_EVIDENCE** here.":
                f"{ANSWER_TEXT} Its history is here.",
            f"{ANSWER_TEXT}\n\nHistory: (INSUFFICIENT_EVIDENCE)":
                f"{ANSWER_TEXT}\n\nHistory:",
            f"{ANSWER_TEXT} __INSUFFICIENT_EVIDENCE__":
                ANSWER_TEXT,
        }
        for claude_text, expected in cases.items():
            with self.subTest(claude_text=claude_text):
                body, _, evaluator = self.post_query(0.9, claude_text)

                self.assert_status_consistent(body, ANSWERED)
                self.assertEqual(body["final_answer"], expected)
                self.assertEqual(body["attempts"][0]["citations"], [1])
                evaluated_answer = evaluator.call_args.args[0].split("<answer>\n", 1)[1]
                self.assertNotIn(INSUFFICIENT_EVIDENCE, evaluated_answer)

    def test_reply_of_only_refusal_tokens_is_insufficient_evidence(self):
        for text in ("[INSUFFICIENT_EVIDENCE]", "(INSUFFICIENT_EVIDENCE)."):
            with self.subTest(claude_text=text):
                body, _, evaluator = self.post_query(0.9, text)

                evaluator.assert_not_called()
                self.assert_status_consistent(body, INSUFFICIENT_EVIDENCE)
                self.assertEqual(body["final_answer"], NOT_SUPPORTED_MESSAGE)

    def test_refusal_stop_reason_with_leading_token_is_still_a_refusal(self):
        with patch("app.services.similarity_gate.retrieve", return_value=self.retrieved(0.9)), \
             patch("app.services.generator.call_claude", return_value=LLMResult(
                 text="INSUFFICIENT_EVIDENCE", model=MODEL, input_tokens=100, output_tokens=5,
                 latency_ms=5, stop_reason="refusal", attempts=1)), \
             patch("app.services.evaluator.call_claude") as evaluator:
            response = self.client.post("/query", json={"question": "What is TCP?"})

        self.assertEqual(response.status_code, 200, response.text)
        evaluator.assert_not_called()
        self.assert_status_consistent(response.json(), INSUFFICIENT_EVIDENCE)

    def test_empty_or_refused_generation_is_an_error_not_an_answer(self):
        replies = {
            "empty": ("", "end_turn"),
            "whitespace": ("  \n\t ", "end_turn"),
            "punctuation only": ("...", "end_turn"),
            "classifier refusal, no text": ("", "refusal"),
            "classifier refusal, only token": ("[INSUFFICIENT_EVIDENCE]", "refusal"),
        }
        for name, (text, stop_reason) in replies.items():
            with self.subTest(name), \
                 patch("app.services.similarity_gate.retrieve", return_value=self.retrieved(0.9)), \
                 patch("app.services.generator.call_claude", return_value=LLMResult(
                     text=text, model=MODEL, input_tokens=100, output_tokens=0, latency_ms=5,
                     stop_reason=stop_reason, attempts=1)), \
                 patch("app.services.evaluator.call_claude") as evaluator:
                response = self.client.post("/query", json={"question": f"What is TCP? {name}"})

                self.assertEqual(response.status_code, 502, response.text)
                self.assertIn("no usable answer", response.json()["detail"])
                evaluator.assert_not_called()
                with self.Session() as db:
                    query = db.scalars(select(Query).order_by(Query.id.desc()).limit(1)).one()
                    answers = db.scalars(select(Answer).where(Answer.query_id == query.id)).all()
                    self.assertEqual((query.final_status, query.final_attempt_number), (ERROR, 1))
                    self.assertEqual([(a.status, a.answer_text) for a in answers], [(ERROR, None)])

    def post_generation(self, replies):
        """POST /query with the generator's Claude returning `replies` (LLMResults) in order."""
        with patch.object(settings, "claude_max_tokens", 1024), \
             patch("app.services.similarity_gate.retrieve", return_value=self.retrieved(0.9)), \
             patch("app.services.generator.call_claude", side_effect=replies) as claude, \
             patch("app.services.evaluator.call_claude") as evaluator:
            evaluator.return_value = llm_result(evaluator_reply(self.passing_claims()))
            response = self.client.post("/query", json={"question": "What is TCP?"})
        budgets = [call.kwargs["max_tokens"] for call in claude.call_args_list]
        return response, budgets, evaluator

    @staticmethod
    def generated(text: str, stop_reason: str, output_tokens: int = 20) -> LLMResult:
        return LLMResult(text=text, model=MODEL, input_tokens=100, output_tokens=output_tokens,
                         latency_ms=5, stop_reason=stop_reason, attempts=1)

    def latest_query(self) -> tuple[Query, list[Answer]]:
        with self.Session() as db:
            query = db.scalars(select(Query).order_by(Query.id.desc()).limit(1)).one()
            return query, db.scalars(select(Answer).where(Answer.query_id == query.id)).all()

    def test_truncated_answer_is_retried_with_a_larger_budget(self):
        response, budgets, evaluator = self.post_generation([
            self.generated("TCP provides a reliable, ordered", "max_tokens", 1024),
            self.generated(ANSWER_TEXT, "end_turn"),
        ])

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assert_status_consistent(body, ANSWERED)
        self.assertEqual(body["final_answer"], ANSWER_TEXT)
        self.assertEqual(budgets, [None, 2048])
        evaluator.assert_called_once()
        _, [answer] = self.latest_query()
        self.assertEqual((answer.input_tokens, answer.output_tokens), (200, 1044))

    def test_persistently_truncated_answer_is_an_error_not_an_answer(self):
        cut = self.generated("TCP provides a reliable, ordered", "max_tokens", 1024)
        response, budgets, evaluator = self.post_generation([cut, cut, cut])

        self.assertEqual(response.status_code, 502, response.text)
        self.assertIn("cut off", response.json()["detail"])
        self.assertEqual(budgets, [None, 2048, 4096])
        evaluator.assert_not_called()
        query, answers = self.latest_query()
        self.assertEqual(query.final_status, ERROR)
        self.assertEqual([(a.status, a.answer_text) for a in answers], [(ERROR, None)])

    def test_truncated_refusal_is_still_a_refusal(self):
        response, budgets, evaluator = self.post_generation([
            self.generated("INSUFFICIENT_EVIDENCE\n\nThe passages discuss TCP but", "max_tokens")])

        self.assertEqual(response.status_code, 200, response.text)
        self.assert_status_consistent(response.json(), INSUFFICIENT_EVIDENCE)
        self.assertEqual(budgets, [None])
        evaluator.assert_not_called()

    def test_context_window_overflow_is_an_error(self):
        response, budgets, _ = self.post_generation([
            self.generated("TCP provides", "model_context_window_exceeded")])

        self.assertEqual(response.status_code, 502, response.text)
        self.assertEqual(budgets, [None])
        query, answers = self.latest_query()
        self.assertEqual((query.final_status, [a.status for a in answers]), (ERROR, [ERROR]))

    def test_claim_verification_details_are_persisted(self):
        answer = ("TCP provides a reliable, ordered byte stream [1]. TCP was invented in 1974 [1]. "
                  "TCP uses sequence numbers [1]. UDP sends independent datagrams quickly. "
                  "Ordered delivery of the byte stream is guaranteed [9].")
        reply = json.dumps({
            "claims": [
                claim("TCP provides a reliable, ordered byte stream.", SUPPORTED, self.chunk_id,
                      "reliable, ordered byte stream"),
                claim("TCP was invented in 1974.", SUPPORTED, self.chunk_id, "TCP provides"),
                claim("TCP uses sequence numbers.", SUPPORTED, self.chunk_id,
                      "TCP uses sequence numbers"),
                claim("Ordered delivery of the byte stream is guaranteed.", SUPPORTED,
                      self.chunk_id, "ordered byte stream"),
            ],
            "limitations": ["TCP was standardized in 1981."],
            "answer_relevance": 0.9, "context_relevance": 0.9, "feedback": "Checked.",
        })
        body, _, _ = self.post_query(0.9, answer, [reply])

        expected = [
            ("TCP provides a reliable, ordered byte stream.", SUPPORTED, SUPPORTED, None),
            ("TCP was invented in 1974.", UNSUPPORTED, SUPPORTED, "support"),
            ("TCP uses sequence numbers.", UNSUPPORTED, SUPPORTED, "evidence"),
            ("Ordered delivery of the byte stream is guaranteed.", "partially_supported",
             SUPPORTED, "citation"),
            ("TCP was standardized in 1981.", UNSUPPORTED, None, "limitation"),
            ("UDP sends independent datagrams quickly.", UNSUPPORTED, None, "uncited"),
        ]
        api_claims = body["attempts"][0]["evaluation"]["claims"]
        self.assertEqual([(c["claim_text"], c["verdict"], c["claude_verdict"], c["check_name"])
                          for c in api_claims], expected)
        for api_claim in api_claims:
            self.assertEqual(api_claim["evidence_error"] is None, api_claim["check_name"] is None)
        self.assertIn("1974", api_claims[1]["evidence_error"])
        self.assertIn("[9]", api_claims[3]["evidence_error"])

        [evaluation] = self.saved_evaluations(body["query_id"])
        self.assertEqual([(c.claim_text, c.verdict, c.claude_verdict, c.check_name)
                          for c in evaluation.claims], expected)
        self.assertEqual([c.evidence_error for c in evaluation.claims],
                         [c["evidence_error"] for c in api_claims])
        listed = self.client.get("/evaluations").json()["items"][0]["claims"]
        self.assertEqual(listed, api_claims)

    def test_check_name_is_validated(self):
        from typing import get_args

        from app.models import CLAIM_CHECK_NAMES, Claim
        from app.schemas import ClaimCheckName
        from app.services.evaluator import ClaimVerdict, EvaluationResult
        from app.services.query_pipeline import save_evaluation

        self.assertEqual(set(get_args(ClaimCheckName)), set(CLAIM_CHECK_NAMES))
        with self.assertRaises(ValueError):
            Claim(claim_text="x", verdict=UNSUPPORTED, check_name="other")
        with self.assertRaises(ValueError):
            ClaimVerdict("x", UNSUPPORTED, None, None, None, "why", "other")

        body, _, _ = self.post_query(0.9, ANSWER_TEXT)
        bad_claim = type("BadClaim", (), {"claim_text": "x", "verdict": UNSUPPORTED,
                                          "evidence_chunk_id": None, "evidence_quote": None,
                                          "claude_verdict": None, "evidence_error": "why",
                                          "check": "other"})()
        result = EvaluationResult(faithfulness=0.0, answer_relevance=0.9, context_relevance=0.9,
                                  passed=False, failure_type=UNSUPPORTED_CLAIM, feedback="x",
                                  claims=[bad_claim], model=MODEL, input_tokens=1,
                                  output_tokens=1, latency_ms=1, llm_calls=1)
        with self.Session() as db:
            answer = db.scalars(select(Answer).where(Answer.query_id == body["query_id"])).one()
            self.assertIsNone(save_evaluation(db, answer, result))
        self.assertEqual(len(self.saved_evaluations(body["query_id"])), 1)

    def test_basic_query_stores_the_final_attempt_it_reports(self):
        expected_keys = {"query_id", "question", "mode", "created_at", "status", "final_answer",
                         "final_attempt_number", "attempts"}
        for similarity, claude_text, status in ((0.9, ANSWER_TEXT, ANSWERED),
                                                (0.9, INSUFFICIENT_EVIDENCE, INSUFFICIENT_EVIDENCE),
                                                (0.05, None, INSUFFICIENT_EVIDENCE)):
            with self.subTest(status=status, similarity=similarity):
                body, _, _ = self.post_query(similarity, claude_text)

                self.assertEqual(set(body), expected_keys)
                self.assertEqual(body["final_attempt_number"], 1)
                with self.Session() as db:
                    query = db.get(Query, body["query_id"])
                    self.assertEqual((query.final_status, query.final_attempt_number), (status, 1))

    def run_later_attempt(self, query_id: int, attempt_number: int, similarity: float,
                          claude_error: LLMError | None = None):
        """Run `run_attempt` for an existing query with mocked retrieval and Claude.

        Returns the generator Claude mock.
        """
        with self.Session() as db, \
             patch("app.services.similarity_gate.retrieve",
                   return_value=self.retrieved(similarity)), \
             patch("app.services.generator.call_claude", side_effect=claude_error) as claude:
            query = db.get(Query, query_id)
            if claude_error is None:
                result = run_attempt(db, query, attempt_number=attempt_number,
                                     retrieval_query="rewritten question")
                self.assertEqual(result.answer.attempt_number, attempt_number)
            else:
                with self.assertRaises(LLMError):
                    run_attempt(db, query, attempt_number=attempt_number,
                                retrieval_query="rewritten question")
        return claude

    def assert_first_attempt_kept(self, query_id: int, later_status: str) -> None:
        with self.Session() as db:
            query = db.get(Query, query_id)
            answers = db.scalars(
                select(Answer).where(Answer.query_id == query_id).order_by(Answer.attempt_number)
            ).all()
            self.assertEqual(query.final_status, ANSWERED)
            first, second = answers
            self.assertEqual((first.attempt_number, first.status, first.answer_text,
                              first.retrieval_query, first.model),
                             (1, ANSWERED, ANSWER_TEXT, "What is TCP?", MODEL))
            self.assertEqual((second.attempt_number, second.status, second.answer_text,
                              second.retrieval_query),
                             (2, later_status, None, "rewritten question"))
        [evaluation] = self.saved_evaluations(query_id)
        self.assertEqual(evaluation.answer_id, first.id)

    def test_later_gate_rejection_keeps_first_attempt_and_final_status(self):
        body, _, _ = self.post_query(0.9, ANSWER_TEXT)

        claude = self.run_later_attempt(body["query_id"], 2, similarity=0.05)

        claude.assert_not_called()
        self.assert_first_attempt_kept(body["query_id"], INSUFFICIENT_EVIDENCE)

    def test_later_claude_error_keeps_first_attempt_and_final_status(self):
        body, _, _ = self.post_query(0.9, ANSWER_TEXT)

        claude = self.run_later_attempt(body["query_id"], 2, similarity=0.9,
                                        claude_error=LLMError("overloaded"))

        claude.assert_called_once()
        self.assert_first_attempt_kept(body["query_id"], ERROR)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
