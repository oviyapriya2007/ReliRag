"""Offline tests for the evaluator pass threshold (70%) across verdicts, correction, and modes.

Usage (from the project root or backend/):
    python backend/test_pass_threshold.py

Scores are on a 0-1 scale and a score passes when it is finite and at least the threshold.
These tests use the configured default threshold, not a pinned test value, and check that the
frontend constant and the shared boundary cases agree with the backend.

Offline: retrieval and every Claude caller (generator, evaluator, query rewriter) are mocked, and
the app runs against an in-memory SQLite database, so no API calls are made and the real
database is never touched. Exits with status 0 when all tests pass, 1 otherwise.
"""

import json
import math
import os
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# Must be set before `app` is imported so the app never connects to the real database.
os.environ["DATABASE_URL"] = "sqlite://"

BACKEND = Path(__file__).resolve().parent
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import Settings, settings  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Document, DocumentChunk  # noqa: E402
from app.services.attempt_selection import (  # noqa: E402
    AttemptEvaluation,
    AttemptSummary,
    select_final_attempt,
)
from app.services.corrector import (  # noqa: E402
    REWRITE,
    STRICT,
    choose_correction,
    failure_signals,
)
from app.services.evaluator import (  # noqa: E402
    EVALUATOR_ERROR,
    IRRELEVANT_RETRIEVAL,
    MISSING_INFO,
    PARTIALLY_SUPPORTED,
    SUPPORTED,
    UNSUPPORTED,
    UNSUPPORTED_CLAIM,
    compute_faithfulness,
    determine_failure_type,
    evaluate_answer,
)
from app.services.generator import ANSWERED  # noqa: E402
from app.services.llm import LLMError, LLMResult  # noqa: E402
from app.services.retrieval import RetrievedChunk  # noqa: E402
from app.services.similarity_gate import INSUFFICIENT_EVIDENCE  # noqa: E402

THRESHOLD = Settings.model_fields["evaluator_pass_threshold"].default
FRONTEND_MODULE = ROOT / "frontend" / "src" / "evaluationThreshold.js"
SHARED_CASES = ROOT / "frontend" / "src" / "evaluationThreshold.cases.json"
NON_FINITE = (math.nan, math.inf, -math.inf)
FAILURE_ORDER = (UNSUPPORTED_CLAIM, MISSING_INFO, IRRELEVANT_RETRIEVAL)

MODEL = "claude-test-model"
PINNED_SETTINGS = {
    "claude_model": MODEL,
    "claude_max_tokens": 1024,
    "similarity_gate": 0.30,
    "evaluator_model": None,
    "evaluator_max_tokens": 2048,
    # The configured default, so a local .env cannot change the expected results.
    "evaluator_pass_threshold": THRESHOLD,
    "evaluator_max_parse_attempts": 2,
}


def llm_result(text: str) -> LLMResult:
    return LLMResult(text=text, model=MODEL, input_tokens=100, output_tokens=20,
                     latency_ms=5, stop_reason="end_turn", attempts=1)


def replies(items) -> list:
    """Mock side effects: strings become Claude replies, exceptions are raised."""
    return [item if isinstance(item, Exception) else llm_result(item) for item in items]


def evaluator_reply(claims, answer_relevance, context_relevance, feedback="Checked.") -> str:
    return json.dumps({"claims": claims, "answer_relevance": answer_relevance,
                       "context_relevance": context_relevance, "feedback": feedback})


def claim(text: str, verdict: str, chunk_id: int | None, quote: str | None) -> dict:
    return {"claim_text": text, "verdict": verdict, "evidence_chunk_id": chunk_id,
            "evidence_quote": quote}


class PinnedSettingsTestCase(unittest.TestCase):
    def setUp(self):
        for name, value in PINNED_SETTINGS.items():
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)


class ThresholdConfigurationTest(unittest.TestCase):
    def test_default_threshold_is_70_percent_on_a_0_to_1_scale(self):
        self.assertEqual(THRESHOLD, 0.70)
        base = {k: v for k, v in os.environ.items() if k != "EVALUATOR_PASS_THRESHOLD"}
        with patch.dict(os.environ, base, clear=True):
            self.assertEqual(Settings(_env_file=None).evaluator_pass_threshold, 0.70)

    def test_env_example_matches_the_default(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        values = re.findall(r"^EVALUATOR_PASS_THRESHOLD=(.*)$", text, re.MULTILINE)
        self.assertEqual([float(value) for value in values], [THRESHOLD])

    def test_frontend_constant_matches_the_backend_default(self):
        text = FRONTEND_MODULE.read_text(encoding="utf-8")
        values = re.findall(r"export const EVALUATOR_PASS_THRESHOLD = ([0-9.]+)", text)
        self.assertEqual([float(value) for value in values], [THRESHOLD])


class VerdictBoundaryTest(PinnedSettingsTestCase):
    """determine_failure_type with the configured threshold, score by score."""

    def assert_only_score_decides(self, value, passes: bool):
        for position, failure_type in enumerate(FAILURE_ORDER):
            scores = [1.0, 1.0, 1.0]
            scores[position] = value
            with self.subTest(value=value, failing=failure_type):
                self.assertEqual(determine_failure_type(*scores),
                                 None if passes else failure_type)

    def test_score_below_threshold_fails(self):
        for value in (0.69, 0.6999999, 0.5, 0.0):
            self.assert_only_score_decides(value, passes=False)

    def test_score_exactly_at_threshold_passes(self):
        self.assertIsNone(determine_failure_type(0.70, 0.70, 0.70))
        self.assert_only_score_decides(0.70, passes=True)

    def test_score_above_threshold_passes(self):
        for value in (0.7000001, 0.71, 0.75, 0.79, 0.80, 1.0):
            self.assert_only_score_decides(value, passes=True)

    def test_faithfulness_computed_as_exactly_70_percent_passes(self):
        verdicts = [SUPPORTED, SUPPORTED, SUPPORTED, PARTIALLY_SUPPORTED, UNSUPPORTED]
        faithfulness = compute_faithfulness(verdicts)
        self.assertEqual(faithfulness, 0.70)
        self.assertIsNone(determine_failure_type(faithfulness, 0.70, 0.70))
        self.assertEqual(determine_failure_type(compute_faithfulness([SUPPORTED, UNSUPPORTED]),
                                                1.0, 1.0), UNSUPPORTED_CLAIM)

    def test_non_finite_scores_never_pass(self):
        for value in NON_FINITE:
            self.assert_only_score_decides(value, passes=False)

    def test_verdict_is_the_conjunction_of_the_individual_scores(self):
        values = (0.0, 0.69, 0.70, 0.71, 1.0)
        for faithfulness in values:
            for answer_relevance in values:
                for context_relevance in values:
                    scores = (faithfulness, answer_relevance, context_relevance)
                    failing = [failure for score, failure in zip(scores, FAILURE_ORDER)
                               if score < THRESHOLD]
                    with self.subTest(scores=scores):
                        self.assertEqual(determine_failure_type(*scores),
                                         failing[0] if failing else None)

    def test_shared_frontend_cases(self):
        cases = json.loads(SHARED_CASES.read_text(encoding="utf-8"))
        self.assertEqual(cases["threshold"], THRESHOLD)
        for case in cases["cases"]:
            scores = (case["faithfulness"], case["answer_relevance"], case["context_relevance"])
            with self.subTest(case=case["name"]):
                self.assertEqual(determine_failure_type(*scores), case["failure_type"])
                self.assertEqual(determine_failure_type(*scores) is None, case["passed"])


QUESTION = "What does TCP provide?"
ANSWER = "TCP provides a reliable, ordered byte stream [1]. It uses a three-way handshake [2]."
CHUNKS = [
    RetrievedChunk(chunk_id=41, document_id=1, document="net.pdf", page=4,
                   text="TCP provides a reliable,\nordered byte stream between applications.",
                   similarity=0.9),
    RetrievedChunk(chunk_id=57, document_id=1, document="net.pdf", page=5,
                   text="TCP connections are opened with a three-way handshake (SYN, SYN-ACK, "
                        "ACK).",
                   similarity=0.8),
]
GOOD_CLAIMS = [
    claim("TCP provides a reliable, ordered byte stream.", SUPPORTED, 41,
          "TCP provides a reliable, ordered byte stream"),
    claim("TCP uses a three-way handshake.", SUPPORTED, 57, "three-way handshake"),
]


class EvaluateAnswerThresholdTest(PinnedSettingsTestCase):
    """evaluate_answer end to end with a mocked Claude reply."""

    @staticmethod
    def evaluate(*texts, answer=ANSWER):
        with patch("app.services.evaluator.call_claude",
                   side_effect=replies(texts)) as claude:
            return evaluate_answer(QUESTION, answer, CHUNKS), claude

    def test_relevance_scores_at_threshold_pass_and_below_fail(self):
        cases = {
            (0.70, 0.70): None,
            (0.71, 0.95): None,
            (0.69, 0.95): MISSING_INFO,
            (0.95, 0.69): IRRELEVANT_RETRIEVAL,
        }
        for (answer_relevance, context_relevance), failure_type in cases.items():
            with self.subTest(answer_relevance=answer_relevance,
                              context_relevance=context_relevance):
                result, _ = self.evaluate(
                    evaluator_reply(GOOD_CLAIMS, answer_relevance, context_relevance))
                self.assertEqual(result.faithfulness, 1.0)
                self.assertEqual(result.failure_type, failure_type)
                self.assertEqual(result.passed, failure_type is None)

    def test_faithfulness_above_threshold_passes_and_below_fails(self):
        partial = claim("TCP handshakes take three seconds.", PARTIALLY_SUPPORTED, 57,
                        "three-way handshake")
        result, _ = self.evaluate(evaluator_reply([GOOD_CLAIMS[0], partial], 0.9, 0.9))
        self.assertEqual(result.faithfulness, 0.75)
        self.assertTrue(result.passed)

        unsupported = claim("TCP was invented in 1999.", UNSUPPORTED, None, None)
        result, _ = self.evaluate(evaluator_reply([GOOD_CLAIMS[0], unsupported], 0.9, 0.9))
        self.assertEqual(result.faithfulness, 0.5)
        self.assertFalse(result.passed)
        self.assertEqual(result.failure_type, UNSUPPORTED_CLAIM)

    def test_overall_verdict_matches_the_individual_scores(self):
        for answer_relevance in (0.0, 0.69, 0.70, 1.0):
            for context_relevance in (0.0, 0.69, 0.70, 1.0):
                with self.subTest(answer_relevance=answer_relevance,
                                  context_relevance=context_relevance):
                    result, _ = self.evaluate(
                        evaluator_reply(GOOD_CLAIMS, answer_relevance, context_relevance))
                    scores = (result.faithfulness, result.answer_relevance,
                              result.context_relevance)
                    self.assertEqual(result.passed,
                                     all(score >= THRESHOLD for score in scores))
                    self.assertEqual(result.failure_type, determine_failure_type(*scores))

    def test_evaluator_error_cannot_pass(self):
        cases = {
            "invalid replies": ("not json", "still not json"),
            "Claude failure": (LLMError("overloaded"),),
            "non-finite relevance": (evaluator_reply(GOOD_CLAIMS, math.nan, 0.9),
                                     evaluator_reply(GOOD_CLAIMS, 0.9, math.inf)),
            "out-of-range relevance": (evaluator_reply(GOOD_CLAIMS, 1.5, 0.9),
                                       evaluator_reply(GOOD_CLAIMS, 0.9, -0.1)),
        }
        for name, texts in cases.items():
            with self.subTest(name):
                result, _ = self.evaluate(*texts)
                self.assertFalse(result.passed)
                self.assertEqual(result.failure_type, EVALUATOR_ERROR)
                self.assertIsNone(result.faithfulness)
                self.assertIsNone(result.answer_relevance)
                self.assertIsNone(result.context_relevance)

    def test_invalid_evidence_still_fails_with_high_relevance(self):
        cases = {
            "quote not in chunk": claim("TCP uses a three-way handshake.", SUPPORTED, 57,
                                        "four-way handshake"),
            "chunk not retrieved": claim("TCP uses a three-way handshake.", SUPPORTED, 99,
                                         "three-way handshake"),
            "no evidence": claim("TCP uses a three-way handshake.", SUPPORTED, None, None),
        }
        for name, bad in cases.items():
            with self.subTest(name):
                result, _ = self.evaluate(evaluator_reply([GOOD_CLAIMS[0], bad], 1.0, 1.0))
                self.assertEqual(result.faithfulness, 0.5)
                self.assertEqual(result.claims[1].verdict, UNSUPPORTED)
                self.assertFalse(result.passed)
                self.assertEqual(result.failure_type, UNSUPPORTED_CLAIM)

    def test_answer_that_only_states_missing_evidence_cannot_pass(self):
        limitation = "The passages do not say how fast TCP is."
        body = {"claims": [], "limitations": [limitation], "answer_relevance": 1.0,
                "context_relevance": 1.0, "feedback": "Checked."}
        result, _ = self.evaluate(json.dumps(body), answer=limitation)
        self.assertEqual((result.faithfulness, result.answer_relevance), (1.0, 0.0))
        self.assertFalse(result.passed)
        self.assertEqual(result.failure_type, MISSING_INFO)


def stored(failure_type, faithfulness, answer_relevance, context_relevance):
    return SimpleNamespace(passed=failure_type is None, failure_type=failure_type,
                           faithfulness=faithfulness, answer_relevance=answer_relevance,
                           context_relevance=context_relevance, claims=[])


class CorrectionThresholdTest(PinnedSettingsTestCase):
    def test_strict_needs_context_relevance_at_least_the_threshold(self):
        self.assertEqual(choose_correction(stored(UNSUPPORTED_CLAIM, 0.5, 0.9, 0.70)), STRICT)
        self.assertEqual(choose_correction(stored(UNSUPPORTED_CLAIM, 0.5, 0.9, 0.75)), STRICT)
        for context in (0.69, *NON_FINITE, None):
            with self.subTest(context=context):
                self.assertEqual(choose_correction(stored(UNSUPPORTED_CLAIM, 0.5, 0.9, context)),
                                 REWRITE)

    def test_scores_at_threshold_are_not_failure_signals(self):
        self.assertEqual(failure_signals(stored(UNSUPPORTED_CLAIM, 0.5, 0.70, 0.70)),
                         [UNSUPPORTED_CLAIM])
        self.assertEqual(failure_signals(stored(UNSUPPORTED_CLAIM, 0.5, 0.69, 0.69)),
                         [UNSUPPORTED_CLAIM, MISSING_INFO, IRRELEVANT_RETRIEVAL])
        self.assertEqual(choose_correction(stored(UNSUPPORTED_CLAIM, 0.5, 0.69, 0.9)), REWRITE)

    def test_no_correction_for_passing_or_evaluator_error(self):
        self.assertIsNone(choose_correction(stored(None, 0.70, 0.70, 0.70)))
        error = SimpleNamespace(passed=False, failure_type=EVALUATOR_ERROR, faithfulness=None,
                                answer_relevance=None, context_relevance=None, claims=[])
        self.assertIsNone(choose_correction(error))
        self.assertEqual(failure_signals(error), [])

    def test_attempt_selection_prefers_a_pass_at_the_threshold_and_skips_errors(self):
        def summary(number, passed, failure_type, scores):
            return AttemptSummary(number, ANSWERED,
                                  AttemptEvaluation(passed, failure_type, *scores))

        first = summary(1, False, MISSING_INFO, (1.0, 0.69, 0.9))
        at_threshold = summary(2, True, None, (1.0, 0.70, 0.9))
        self.assertIs(select_final_attempt([first, at_threshold]), at_threshold)

        error = summary(2, False, EVALUATOR_ERROR, (None, None, None))
        self.assertIs(select_final_attempt([first, error]), first)
        non_finite = summary(2, True, None, (1.0, math.nan, 0.9))
        self.assertIs(select_final_attempt([first, non_finite]), first)


CHUNK_TEXTS = [
    "Policy 1. Members may request item A after approval.",
    "Policy 2. Item B has an allowance of 50 units per year.",
    "Policy 3. Item A has an allowance of 200 units per year.",
]
POLICY_QUESTION = "What is the allowance for item A?"
FIRST_ANSWER = "Members may request item A after approval [1]."
SECOND_ANSWER = "Item A has an allowance of 200 units per year [1]."
UNSUPPORTED_TEXT = "Item A has an allowance of 100 units."
REWRITTEN = "item A allowance amount per year"


class ModeConsistencyTest(PinnedSettingsTestCase):
    """POST /query in Basic and RELI (Attest) mode against an in-memory database."""

    def setUp(self):
        super().setUp()
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

        with Session() as db:
            document = Document(filename="policies.pdf", total_pages=3, total_chunks=3)
            chunks = [DocumentChunk(document=document, page_number=i + 1, chunk_index=i,
                                    content=text) for i, text in enumerate(CHUNK_TEXTS)]
            db.add_all([document, *chunks])
            db.commit()
            self.document_id = document.id
            self.chunk_ids = [chunk.id for chunk in chunks]

        def override_get_db():
            db = Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def retrieved(self, indexes, similarity=0.8):
        return [RetrievedChunk(chunk_id=self.chunk_ids[i], document_id=self.document_id,
                               document="policies.pdf", page=i + 1, text=CHUNK_TEXTS[i],
                               similarity=similarity - 0.01 * rank)
                for rank, i in enumerate(indexes)]

    def supported(self, index):
        text = CHUNK_TEXTS[index].split(". ", 1)[1]
        return claim(text, SUPPORTED, self.chunk_ids[index], text.rstrip("."))

    def post(self, mode, *, retrievals, generations, evaluations=(), rewrites=()):
        with patch("app.services.similarity_gate.retrieve", side_effect=list(retrievals)), \
             patch("app.services.generator.call_claude", side_effect=replies(generations)), \
             patch("app.services.evaluator.call_claude",
                   side_effect=replies(evaluations)) as evaluator, \
             patch("app.services.corrector.call_claude",
                   side_effect=replies(rewrites)) as rewriter:
            response = self.client.post("/query", json={"question": POLICY_QUESTION,
                                                        "mode": mode})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), SimpleNamespace(evaluator=evaluator, rewriter=rewriter)

    def first_evaluation(self, body):
        return body["attempts"][0]["evaluation"]

    def test_scores_at_threshold_pass_in_both_modes_without_correction(self):
        for mode in ("basic", "reli"):
            with self.subTest(mode=mode):
                body, mocks = self.post(
                    mode, retrievals=[self.retrieved([0])], generations=[FIRST_ANSWER],
                    evaluations=[evaluator_reply([self.supported(0)], 0.70, 0.70)])
                self.assertEqual((body["status"], body["final_attempt_number"],
                                  len(body["attempts"])), (ANSWERED, 1, 1))
                evaluation = self.first_evaluation(body)
                self.assertEqual((evaluation["passed"], evaluation["failure_type"]), (True, None))
                mocks.rewriter.assert_not_called()

    def test_scores_below_threshold_fail_in_both_modes_and_trigger_correction_in_reli(self):
        first_reply = evaluator_reply([self.supported(0)], 0.69, 0.9)
        basic, _ = self.post("basic", retrievals=[self.retrieved([0])],
                             generations=[FIRST_ANSWER], evaluations=[first_reply])
        self.assertEqual(len(basic["attempts"]), 1)
        self.assertEqual((self.first_evaluation(basic)["passed"],
                          self.first_evaluation(basic)["failure_type"]), (False, MISSING_INFO))

        reli, mocks = self.post(
            "reli", retrievals=[self.retrieved([0]), self.retrieved([2])],
            generations=[FIRST_ANSWER, SECOND_ANSWER],
            evaluations=[first_reply, evaluator_reply([self.supported(2)], 0.70, 0.70)],
            rewrites=[REWRITTEN])
        self.assertEqual(self.first_evaluation(reli), self.first_evaluation(basic))
        self.assertEqual([a["strategy"] for a in reli["attempts"]], [None, REWRITE])
        self.assertEqual(reli["final_attempt_number"], 2)
        self.assertTrue(reli["attempts"][1]["evaluation"]["passed"])
        mocks.rewriter.assert_called_once()

    def test_context_relevance_at_threshold_selects_strict_correction(self):
        def unsupported(context_relevance):
            return evaluator_reply(
                [self.supported(0), claim(UNSUPPORTED_TEXT, UNSUPPORTED, None, None)],
                0.9, context_relevance)

        strict_answer = SECOND_ANSWER.replace("[1]", "[2]")
        body, mocks = self.post(
            "reli", retrievals=[self.retrieved([0, 2])],
            generations=[f"{FIRST_ANSWER} {UNSUPPORTED_TEXT} [2]", strict_answer],
            evaluations=[unsupported(0.70), evaluator_reply([self.supported(2)], 0.9, 0.9)])
        self.assertEqual([a["strategy"] for a in body["attempts"]], [None, STRICT])
        mocks.rewriter.assert_not_called()

        body, mocks = self.post(
            "reli", retrievals=[self.retrieved([0, 2]), self.retrieved([2])],
            generations=[f"{FIRST_ANSWER} {UNSUPPORTED_TEXT} [2]", SECOND_ANSWER],
            evaluations=[unsupported(0.69), evaluator_reply([self.supported(2)], 0.9, 0.9)],
            rewrites=[REWRITTEN])
        self.assertEqual([a["strategy"] for a in body["attempts"]], [None, REWRITE])

    def test_evaluator_error_fails_in_both_modes_and_is_not_corrected(self):
        for mode in ("basic", "reli"):
            with self.subTest(mode=mode):
                body, mocks = self.post(mode, retrievals=[self.retrieved([0])],
                                        generations=[FIRST_ANSWER],
                                        evaluations=["not json", "still not json"])
                evaluation = self.first_evaluation(body)
                self.assertEqual((evaluation["passed"], evaluation["failure_type"]),
                                 (False, EVALUATOR_ERROR))
                self.assertEqual(len(body["attempts"]), 1)
                mocks.rewriter.assert_not_called()

    def test_insufficient_evidence_stays_insufficient_in_both_modes(self):
        cases = {
            "similarity gate": ([self.retrieved([0], similarity=0.1)], []),
            "generator refusal": ([self.retrieved([0])], [INSUFFICIENT_EVIDENCE]),
        }
        for mode in ("basic", "reli"):
            for name, (retrievals, generations) in cases.items():
                with self.subTest(mode=mode, case=name):
                    body, mocks = self.post(mode, retrievals=retrievals,
                                            generations=generations)
                    self.assertEqual(body["status"], INSUFFICIENT_EVIDENCE)
                    self.assertEqual(len(body["attempts"]), 1)
                    self.assertIsNone(self.first_evaluation(body))
                    mocks.evaluator.assert_not_called()
                    mocks.rewriter.assert_not_called()

    def test_analytics_counts_the_backend_verdict(self):
        for evaluations in ([evaluator_reply([self.supported(0)], 0.70, 0.70)],
                            [evaluator_reply([self.supported(0)], 0.69, 0.70)],
                            ["not json", "still not json"]):
            self.post("basic", retrievals=[self.retrieved([0])], generations=[FIRST_ANSWER],
                      evaluations=evaluations)
        response = self.client.get("/analytics/summary")
        self.assertEqual(response.status_code, 200, response.text)
        # The evaluator_error query has no usable evaluation, so it is not counted.
        self.assertEqual(response.json()["by_mode"]["basic"]["first_pass"],
                         {"count": 1, "total": 2, "rate": 0.5})


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
