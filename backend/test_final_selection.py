"""Offline tests: the final answer, scores, verdict, attempt number, attempt history, and
selection reason of a query all describe the same selected attempt (Basic, RELI, /compare).

Usage (from the project root or backend/):
    python backend/test_final_selection.py

Offline: retrieval and every Claude caller (generator, evaluator, query rewriter) are mocked, and
the app runs against SQLite databases created for each test, so no API calls are made and the
real database is never touched. Exits with status 0 when all tests pass, 1 otherwise.
"""

import json
import math
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
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import test_compare as compare_fixtures  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Answer, Document, DocumentChunk, Query  # noqa: E402
from app.routers.query import ERROR_MESSAGE  # noqa: E402
from app.services import query_pipeline  # noqa: E402
from app.services.attempt_selection import (  # noqa: E402
    AttemptEvaluation,
    AttemptSummary,
    choose_final_attempt,
    describe_final_selection,
    passes,
    select_final_attempt,
)
from app.services.corrector import REWRITE, STRICT  # noqa: E402
from app.services.evaluator import (  # noqa: E402
    EVALUATOR_ERROR,
    IRRELEVANT_RETRIEVAL,
    MISSING_INFO,
    SUPPORTED,
    UNSUPPORTED,
    UNSUPPORTED_CLAIM,
)
from app.services.generator import ANSWERED  # noqa: E402
from app.services.llm import LLMError, LLMResult  # noqa: E402
from app.services.query_pipeline import ERROR  # noqa: E402
from app.services.retrieval import RetrievedChunk  # noqa: E402
from app.services.similarity_gate import INSUFFICIENT_EVIDENCE  # noqa: E402

SCORE_KEYS = ("faithfulness", "answer_relevance", "context_relevance")


# --- selection rules (pure) -------------------------------------------------------------------

def scores(faithfulness, answer_relevance, context_relevance, *, failure_type=None,
           passed=None) -> AttemptEvaluation:
    return AttemptEvaluation(passed=failure_type is None if passed is None else passed,
                             failure_type=failure_type, faithfulness=faithfulness,
                             answer_relevance=answer_relevance,
                             context_relevance=context_relevance)


def attempt(number, evaluation=None, status=ANSWERED) -> AttemptSummary:
    return AttemptSummary(attempt_number=number, status=status, evaluation=evaluation)


EVALUATOR_FAILURE = AttemptEvaluation(passed=False, failure_type=EVALUATOR_ERROR,
                                      faithfulness=None, answer_relevance=None,
                                      context_relevance=None)


class SelectionRulesTest(unittest.TestCase):
    def assert_selected(self, attempts, number, *reason_parts):
        selection = choose_final_attempt(attempts)
        self.assertEqual(selection.attempt.attempt_number, number)
        self.assertIs(select_final_attempt(attempts), selection.attempt)
        for part in reason_parts:
            self.assertIn(part, selection.reason)
        return selection

    def test_case_a_passing_first_attempt_beats_a_worse_second(self):
        first = attempt(1, scores(0.9, 0.9, 0.9))
        for second in (attempt(2, scores(0.8, 0.8, 0.8)),
                       attempt(2, scores(1.0, 1.0, 0.5, failure_type=IRRELEVANT_RETRIEVAL))):
            with self.subTest(second=second.evaluation):
                self.assert_selected([first, second], 1, "Attempt 1 was selected over attempt 2")
        self.assert_selected([first, attempt(2, scores(1.0, 1.0, 0.5,
                                                       failure_type=IRRELEVANT_RETRIEVAL))],
                             1, "attempt 1 passed and attempt 2 did not")

    def test_case_b_passing_second_attempt_beats_a_failing_first(self):
        self.assert_selected([attempt(1, scores(1.0, 0.5, 0.9, failure_type=MISSING_INFO)),
                              attempt(2, scores(1.0, 0.95, 0.9))],
                             2, "Attempt 2 was selected over attempt 1",
                             "attempt 2 passed and attempt 1 did not")

    def test_case_c_failed_second_attempt_keeps_a_valid_first(self):
        first = attempt(1, scores(1.0, 0.5, 0.9, failure_type=MISSING_INFO))
        for second, why in ((attempt(2, status=ERROR), "its status is ERROR"),
                            (attempt(2, status=INSUFFICIENT_EVIDENCE),
                             "its status is INSUFFICIENT_EVIDENCE"),
                            (attempt(2, None), "it has no saved evaluation")):
            with self.subTest(why):
                self.assert_selected([first, second], 1, why)

    def test_case_d_evaluator_error_first_is_replaced_only_by_a_pass(self):
        first = attempt(1, EVALUATOR_FAILURE)
        self.assertFalse(passes(first))
        self.assert_selected([first, attempt(2, scores(0.9, 0.9, 0.9))], 2,
                             "attempt 1 has no usable evaluation", "attempt 2 passed")
        self.assert_selected([first, attempt(2, scores(0.5, 0.9, 0.9,
                                                       failure_type=UNSUPPORTED_CLAIM))],
                             1, "attempt 2 did not pass")

    def test_case_e_both_failing_uses_the_existing_policy(self):
        first = attempt(1, scores(1.0, 0.5, 0.9, failure_type=MISSING_INFO))
        more_complete = attempt(2, scores(1.0, 0.65, 0.9, failure_type=MISSING_INFO))
        less_faithful = attempt(2, scores(0.5, 0.9, 0.9, failure_type=UNSUPPORTED_CLAIM))
        selection = self.assert_selected([first, more_complete], 2, "more complete")
        self.assertFalse(passes(selection.attempt))
        self.assert_selected([first, less_faithful], 1, "lost too much faithfulness")

    def test_both_evaluator_errors_keep_the_first_and_never_pass(self):
        selection = self.assert_selected([attempt(1, EVALUATOR_FAILURE),
                                          attempt(2, EVALUATOR_FAILURE)],
                                         1, "evaluator error")
        self.assertFalse(passes(selection.attempt))

    def test_case_f_single_attempt(self):
        for only in (attempt(1, scores(0.9, 0.9, 0.9)), attempt(1, EVALUATOR_FAILURE),
                     attempt(1, status=INSUFFICIENT_EVIDENCE)):
            with self.subTest(status=only.status, evaluation=only.evaluation):
                self.assert_selected([only], 1, "Attempt 1 is the only attempt.")

    def test_exact_tie_keeps_the_earlier_attempt(self):
        for evaluation in (scores(0.9, 0.9, 0.9),
                           scores(1.0, 0.5, 0.9, failure_type=MISSING_INFO)):
            with self.subTest(evaluation=evaluation):
                self.assert_selected([attempt(1, evaluation), attempt(2, evaluation)], 1,
                                     "earlier attempt is kept on a tie")

    def test_context_relevance_only_breaks_a_tie(self):
        first = attempt(1, scores(1.0, 0.5, 0.6, failure_type=MISSING_INFO))
        self.assert_selected([first, attempt(2, scores(1.0, 0.5, 0.65, failure_type=MISSING_INFO))],
                             2, "higher context relevance 0.60 to 0.65")

    def test_invalid_scores_or_contradictory_verdicts_cannot_create_a_pass(self):
        first = attempt(1, scores(0.5, 0.9, 0.4, failure_type=UNSUPPORTED_CLAIM))
        invalid = {
            "NaN": scores(math.nan, 1.0, 1.0, passed=True),
            "infinite": scores(1.0, math.inf, 1.0, passed=True),
            "above 1": scores(1.5, 1.0, 1.0, passed=True),
            "below 0": scores(1.0, 1.0, -0.1, passed=True),
            "missing": scores(None, 1.0, 1.0, passed=True),
        }
        for name, evaluation in invalid.items():
            for current in (first, attempt(1, EVALUATOR_FAILURE), attempt(1, status=ERROR)):
                with self.subTest(name, current=current.status):
                    candidate = attempt(2, evaluation)
                    self.assertFalse(passes(candidate))
                    self.assert_selected([current, candidate], 1,
                                         "missing or invalid scores")

        contradictory = attempt(2, scores(0.5, 0.9, 0.4, failure_type=UNSUPPORTED_CLAIM,
                                          passed=True))
        self.assertFalse(passes(contradictory))
        self.assert_selected([first, contradictory], 1, "tie")
        self.assert_selected([attempt(1, EVALUATOR_FAILURE), contradictory], 1,
                             "did not pass")


class DescribeSelectionTest(unittest.TestCase):
    def test_single_attempt_reasons(self):
        cases = {
            ("basic", attempt(1, scores(0.5, 0.5, 0.5, failure_type=UNSUPPORTED_CLAIM))):
                "Basic mode runs a single attempt; attempt 1 is reported.",
            ("reli", attempt(1, scores(0.9, 0.9, 0.9))):
                "Attempt 1 is the only attempt: it passed its evaluation, so no correction was "
                "needed.",
            ("reli", attempt(1, EVALUATOR_FAILURE)):
                "Attempt 1 is the only attempt: its evaluation is an evaluator error, so no "
                "correction was attempted.",
            ("reli", attempt(1, None)):
                "Attempt 1 is the only attempt: it has no saved evaluation, so no correction was "
                "attempted.",
            ("reli", attempt(1, status=INSUFFICIENT_EVIDENCE)):
                "Attempt 1 is the only attempt: it was not answered (INSUFFICIENT_EVIDENCE), so "
                "no correction runs.",
            ("reli", attempt(1, scores(1.0, 0.5, 0.9, failure_type=MISSING_INFO))):
                "Attempt 1 is the only attempt: it did not pass its evaluation and no correction "
                "attempt was recorded.",
        }
        for (mode, only), reason in cases.items():
            with self.subTest(reason):
                self.assertEqual(describe_final_selection(mode, [only], 1), reason)

    def test_no_reason_without_a_recorded_final_attempt(self):
        self.assertIsNone(describe_final_selection("reli", [attempt(1)], None))
        self.assertIsNone(describe_final_selection("reli", [], 1))

    def test_recorded_choice_that_differs_from_the_rules_is_reported_not_explained(self):
        attempts = [attempt(1, scores(1.0, 0.5, 0.9, failure_type=MISSING_INFO)),
                    attempt(2, scores(1.0, 0.95, 0.9))]
        reason = describe_final_selection("reli", attempts, 1)
        self.assertIn("Attempt 1 is the recorded final attempt", reason)
        self.assertIn("choose attempt 2", reason)
        self.assertEqual(describe_final_selection("reli", attempts, 2),
                         choose_final_attempt(attempts).reason)
        self.assertIn("not among the recorded attempts",
                      describe_final_selection("reli", attempts[:1], 2))


# --- POST /query: Basic and RELI ----------------------------------------------------------------

MODEL = "claude-test-model"
PINNED_SETTINGS = {
    "claude_model": MODEL,
    "claude_max_tokens": 1024,
    "similarity_gate": 0.30,
    "evaluator_model": None,
    "evaluator_max_tokens": 2048,
    "evaluator_pass_threshold": 0.70,
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
UNSUPPORTED_TEXT = "Item A has an allowance of 100 units."
INVALID = ("not json", "still not json")


def llm_result(text: str) -> LLMResult:
    return LLMResult(text=text, model=MODEL, input_tokens=100, output_tokens=20,
                     latency_ms=5, stop_reason="end_turn", attempts=1)


def replies(items) -> list:
    return [item if isinstance(item, Exception) else llm_result(item) for item in items]


def summaries(body) -> list[AttemptSummary]:
    """Selection view of the attempts exactly as the API returned them."""
    return [AttemptSummary(
        attempt_number=item["attempt_number"], status=item["status"],
        evaluation=AttemptEvaluation(**{key: item["evaluation"][key] for key in
                                        ("passed", "failure_type", *SCORE_KEYS)})
        if item["evaluation"] is not None else None,
    ) for item in body["attempts"]]


class PipelineSelectionTest(unittest.TestCase):
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
        self.server_client = TestClient(app, raise_server_exceptions=False)

    # --- fixtures ---

    def retrieved(self, indexes, similarity=0.8):
        return [RetrievedChunk(chunk_id=self.chunk_ids[i], document_id=self.document_id,
                               document="policies.pdf", page=i + 1, text=CHUNK_TEXTS[i],
                               similarity=similarity - 0.01 * rank)
                for rank, i in enumerate(indexes)]

    def supported(self, index):
        text = CHUNK_TEXTS[index].split(". ", 1)[1]
        return {"claim_text": text, "verdict": SUPPORTED, "evidence_chunk_id": self.chunk_ids[index],
                "evidence_quote": text.rstrip(".")}

    @staticmethod
    def unsupported():
        return {"claim_text": UNSUPPORTED_TEXT, "verdict": UNSUPPORTED, "evidence_chunk_id": None,
                "evidence_quote": None}

    @staticmethod
    def evaluation(claims, answer_relevance, context_relevance):
        return json.dumps({"claims": claims, "answer_relevance": answer_relevance,
                           "context_relevance": context_relevance, "feedback": "Checked."})

    def first_fails(self):
        """Attempt 1 on chunk 0: faithful but incomplete (missing_info)."""
        return self.evaluation([self.supported(0)], 0.5, 0.9)

    def second_passes(self):
        return self.evaluation([self.supported(2)], 0.95, 0.9)

    # --- helpers ---

    def post(self, *, retrievals, generations, evaluations=(), rewrites=(), mode="reli",
             expected_status=200):
        with patch("app.services.similarity_gate.retrieve", side_effect=list(retrievals)), \
             patch("app.services.generator.call_claude", side_effect=replies(generations)) as gen, \
             patch("app.services.evaluator.call_claude",
                   side_effect=replies(evaluations)) as ev, \
             patch("app.services.corrector.call_claude", side_effect=replies(rewrites)) as rw:
            client = self.server_client if expected_status == 500 else self.client
            response = client.post("/query", json={"question": QUESTION, "mode": mode})
        self.assertEqual(response.status_code, expected_status, response.text)
        mocks = SimpleNamespace(generator=gen, evaluator=ev, rewriter=rw)
        return (response.json() if expected_status == 200 else None), mocks

    def latest_query_id(self) -> int:
        with self.Session() as db:
            return db.scalars(select(Query.id).order_by(Query.id.desc()).limit(1)).one()

    def assert_consistent(self, body, *, mode="reli", final, attempts, status=ANSWERED,
                          strategies=None):
        """Final answer, verdict, scores, number, history, reason, and storage all agree."""
        self.assertEqual(body["mode"], mode)
        self.assertEqual([a["attempt_number"] for a in body["attempts"]],
                         list(range(1, attempts + 1)))
        if strategies is not None:
            self.assertEqual([a["strategy"] for a in body["attempts"]], strategies)
        self.assertEqual((body["status"], body["final_attempt_number"]), (status, final))
        selected = body["attempts"][final - 1]
        if status == ANSWERED:
            self.assertEqual(selected["status"], ANSWERED)
            self.assertEqual(body["final_answer"], selected["answer"])
        # The reported attempt is the one the selection rules pick from the returned history,
        # and the reason explains exactly that choice.
        if mode == "reli" and status == ANSWERED:
            selection = choose_final_attempt(summaries(body))
            self.assertEqual(selection.attempt.attempt_number, final)
            if attempts > 1:
                self.assertEqual(body["selection_reason"], selection.reason)
        self.assertIsNotNone(body["selection_reason"])
        self.assertNotIn("recorded final attempt", body["selection_reason"])

        fetched = self.client.get(f"/query/{body['query_id']}")
        self.assertEqual(fetched.status_code, 200, fetched.text)
        self.assertEqual(fetched.json(), body)
        with self.Session() as db:
            query = db.get(Query, body["query_id"])
            self.assertEqual((query.final_status, query.final_attempt_number), (status, final))
            stored = {a.attempt_number: a for a in query.answers}
            self.assertEqual(len(stored), attempts)
            for item in body["attempts"]:
                answer = stored[item["attempt_number"]]
                self.assertEqual((answer.status, answer.answer_text, answer.strategy),
                                 (item["status"], item["answer"], item["strategy"]))
                latest = answer.evaluations[-1] if answer.evaluations else None
                if latest is None:
                    self.assertIsNone(item["evaluation"])
                else:
                    self.assertEqual(
                        (latest.passed, latest.failure_type,
                         *(getattr(latest, key) for key in SCORE_KEYS)),
                        (item["evaluation"]["passed"], item["evaluation"]["failure_type"],
                         *(item["evaluation"][key] for key in SCORE_KEYS)))
        return selected

    # --- cases ---

    def test_single_attempt_basic_and_reli(self):
        for mode, evaluation, passed in (("basic", self.first_fails(), False),
                                         ("basic", self.evaluation([self.supported(0)], 0.95, 0.9),
                                          True),
                                         ("reli", self.evaluation([self.supported(0)], 0.9, 0.9),
                                          True)):
            with self.subTest(mode=mode, passed=passed):
                body, mocks = self.post(mode=mode, retrievals=[self.retrieved([0, 2])],
                                        generations=[FIRST_ANSWER], evaluations=[evaluation])
                selected = self.assert_consistent(body, mode=mode, final=1, attempts=1,
                                                  strategies=[None])
                self.assertEqual(selected["evaluation"]["passed"], passed)
                mocks.rewriter.assert_not_called()
                expected = ("Basic mode runs a single attempt" if mode == "basic"
                            else "it passed its evaluation, so no correction was needed")
                self.assertIn(expected, body["selection_reason"])

    def test_failing_first_and_passing_second_selects_the_second(self):
        body, _ = self.post(retrievals=[self.retrieved([0]), self.retrieved([2])],
                            generations=[FIRST_ANSWER, SECOND_ANSWER],
                            evaluations=[self.first_fails(), self.second_passes()],
                            rewrites=[REWRITTEN])

        selected = self.assert_consistent(body, final=2, attempts=2, strategies=[None, REWRITE])
        self.assertEqual(body["final_answer"], SECOND_ANSWER)
        self.assertEqual((selected["evaluation"]["passed"],
                          selected["evaluation"]["answer_relevance"]), (True, 0.95))
        first = body["attempts"][0]
        self.assertEqual((first["answer"], first["evaluation"]["passed"],
                          first["evaluation"]["failure_type"]), (FIRST_ANSWER, False, MISSING_INFO))
        self.assertEqual(body["selection_reason"],
                         "Attempt 2 was selected over attempt 1: attempt 2 passed and attempt 1 "
                         "did not.")

    def test_worse_second_attempt_keeps_the_first_with_its_own_scores(self):
        cases = {
            "failing, less faithful": self.evaluation([self.supported(2), self.unsupported()],
                                                      0.9, 0.9),
            "failing, less complete": self.evaluation([self.supported(2)], 0.3, 0.9),
        }
        for name, second_evaluation in cases.items():
            with self.subTest(name):
                body, _ = self.post(retrievals=[self.retrieved([0]), self.retrieved([2])],
                                    generations=[FIRST_ANSWER, SECOND_ANSWER],
                                    evaluations=[self.first_fails(), second_evaluation],
                                    rewrites=[REWRITTEN])
                selected = self.assert_consistent(body, final=1, attempts=2,
                                                  strategies=[None, REWRITE])
                self.assertEqual((body["final_answer"], selected["evaluation"]["faithfulness"],
                                  selected["evaluation"]["answer_relevance"]),
                                 (FIRST_ANSWER, 1.0, 0.5))
                self.assertEqual(body["attempts"][1]["answer"], SECOND_ANSWER)
                self.assertTrue(body["selection_reason"].startswith(
                    "Attempt 1 was selected over attempt 2: "))

    def test_both_failing_reports_the_better_failing_attempt_as_failed(self):
        body, _ = self.post(retrievals=[self.retrieved([0]), self.retrieved([2])],
                            generations=[FIRST_ANSWER, SECOND_ANSWER],
                            evaluations=[self.first_fails(),
                                         self.evaluation([self.supported(2)], 0.65, 0.9)],
                            rewrites=[REWRITTEN])

        selected = self.assert_consistent(body, final=2, attempts=2)
        self.assertEqual((selected["evaluation"]["passed"], selected["evaluation"]["failure_type"]),
                         (False, MISSING_INFO))
        self.assertIn("attempt 2 was more complete", body["selection_reason"])

    def test_equal_scores_keep_the_first_attempt(self):
        body, _ = self.post(retrievals=[self.retrieved([0]), self.retrieved([0])],
                            generations=[FIRST_ANSWER, FIRST_ANSWER],
                            evaluations=[self.first_fails(), self.first_fails()],
                            rewrites=[REWRITTEN])

        self.assert_consistent(body, final=1, attempts=2)
        self.assertIn("earlier attempt is kept on a tie", body["selection_reason"])

    def test_second_attempt_failures_keep_a_valid_first(self):
        second_failures = {
            "Claude error": dict(generations=[FIRST_ANSWER, LLMError("overloaded")],
                                 evaluations=[self.first_fails()]),
            "evaluator error": dict(generations=[FIRST_ANSWER, SECOND_ANSWER],
                                    evaluations=[self.first_fails(), *INVALID]),
            "refusal": dict(generations=[FIRST_ANSWER, INSUFFICIENT_EVIDENCE],
                            evaluations=[self.first_fails()]),
        }
        expected = {"Claude error": (ERROR, "its status is ERROR"),
                    "evaluator error": (ANSWERED, "its evaluation is an evaluator error"),
                    "refusal": (INSUFFICIENT_EVIDENCE, "its status is INSUFFICIENT_EVIDENCE")}
        for name, kwargs in second_failures.items():
            with self.subTest(name):
                body, _ = self.post(retrievals=[self.retrieved([0]), self.retrieved([2])],
                                    rewrites=[REWRITTEN], **kwargs)
                selected = self.assert_consistent(body, final=1, attempts=2,
                                                  strategies=[None, REWRITE])
                self.assertEqual((body["final_answer"], selected["evaluation"]["failure_type"]),
                                 (FIRST_ANSWER, MISSING_INFO))
                status, why = expected[name]
                self.assertEqual(body["attempts"][1]["status"], status)
                self.assertIn(f"attempt 2 has no usable evaluation ({why})",
                              body["selection_reason"])

    def test_unexpected_second_attempt_error_is_recorded_as_error(self):
        real_generate_into = query_pipeline.generate_into
        calls = []

        def generate_into(db, answer, *args, **kwargs):
            calls.append(answer.attempt_number)
            if answer.attempt_number == 2:
                raise RuntimeError("unexpected failure before the row was finished")
            return real_generate_into(db, answer, *args, **kwargs)

        with patch("app.services.query_pipeline.generate_into", side_effect=generate_into):
            body, _ = self.post(retrievals=[self.retrieved([0]), self.retrieved([2])],
                                generations=[FIRST_ANSWER], evaluations=[self.first_fails()],
                                rewrites=[REWRITTEN])

        self.assertEqual(calls, [1, 2])
        self.assert_consistent(body, final=1, attempts=2, strategies=[None, REWRITE])
        second = body["attempts"][1]
        self.assertEqual((second["status"], second["answer"], second["evaluation"]),
                         (ERROR, None, None))

    def test_second_attempt_that_never_stored_a_row_is_not_claimed(self):
        body, _ = self.post(retrievals=[self.retrieved([0]), RuntimeError("embedding down")],
                            generations=[FIRST_ANSWER], evaluations=[self.first_fails()],
                            rewrites=[REWRITTEN])

        self.assert_consistent(body, final=1, attempts=1)
        self.assertEqual(body["selection_reason"],
                         "Attempt 1 is the only attempt: it did not pass its evaluation and no "
                         "correction attempt was recorded.")

    def test_evaluator_error_first_attempt_is_not_passed_or_retried(self):
        for mode in ("basic", "reli"):
            with self.subTest(mode=mode):
                body, mocks = self.post(mode=mode, retrievals=[self.retrieved([0])],
                                        generations=[FIRST_ANSWER], evaluations=list(INVALID))
                selected = self.assert_consistent(body, mode=mode, final=1, attempts=1)
                self.assertEqual((selected["evaluation"]["passed"],
                                  selected["evaluation"]["failure_type"]), (False, EVALUATOR_ERROR))
                mocks.rewriter.assert_not_called()

    def test_strict_correction_selection_is_consistent(self):
        strict_answer = SECOND_ANSWER.replace("[1]", "[2]")
        body, _ = self.post(
            retrievals=[self.retrieved([0, 2])],
            generations=[f"{FIRST_ANSWER} {UNSUPPORTED_TEXT} [2]", strict_answer],
            evaluations=[self.evaluation([self.supported(0), self.unsupported()], 0.9, 0.9),
                         self.evaluation([self.supported(2)], 0.95, 0.9)])

        self.assert_consistent(body, final=2, attempts=2, strategies=[None, STRICT])
        self.assertEqual(body["final_answer"], strict_answer)

    def test_insufficient_evidence_and_error_keep_their_semantics(self):
        for mode in ("basic", "reli"):
            with self.subTest(mode=mode, case="gate"):
                body, _ = self.post(mode=mode, retrievals=[self.retrieved([0], similarity=0.1)],
                                    generations=[])
                self.assert_consistent(body, mode=mode, final=1, attempts=1,
                                       status=INSUFFICIENT_EVIDENCE)
            with self.subTest(mode=mode, case="Claude error"):
                self.post(mode=mode, retrievals=[self.retrieved([0])],
                          generations=[TypeError("no API key")], expected_status=500)
                fetched = self.client.get(f"/query/{self.latest_query_id()}").json()
                self.assertEqual((fetched["status"], fetched["final_answer"],
                                  fetched["final_attempt_number"], len(fetched["attempts"])),
                                 (ERROR, ERROR_MESSAGE, 1, 1))

    def test_failed_evaluation_save_does_not_promote_the_unsaved_attempt(self):
        real_save = query_pipeline.save_evaluation

        def save_evaluation(db, answer, result):
            if answer.attempt_number == 2:
                return None  # As after a failed commit: rolled back and logged.
            return real_save(db, answer, result)

        with patch("app.services.query_pipeline.save_evaluation", side_effect=save_evaluation):
            body, _ = self.post(retrievals=[self.retrieved([0]), self.retrieved([2])],
                                generations=[FIRST_ANSWER, SECOND_ANSWER],
                                evaluations=[self.first_fails(), self.second_passes()],
                                rewrites=[REWRITTEN])

        self.assert_consistent(body, final=1, attempts=2)
        self.assertIsNone(body["attempts"][1]["evaluation"])
        self.assertIn("attempt 2 has no usable evaluation (it has no saved evaluation)",
                      body["selection_reason"])

    def test_failed_final_selection_commit_leaves_a_consistent_earlier_result(self):
        real_set_final = query_pipeline.set_final_attempt
        calls = []

        def set_final_attempt(db, query, attempt_number, status):
            calls.append(attempt_number)
            if len(calls) == 2:
                raise RuntimeError("database unavailable")
            return real_set_final(db, query, attempt_number, status)

        with patch("app.services.query_pipeline.set_final_attempt",
                   side_effect=set_final_attempt):
            self.post(retrievals=[self.retrieved([0]), self.retrieved([2])],
                      generations=[FIRST_ANSWER, SECOND_ANSWER],
                      evaluations=[self.first_fails(), self.second_passes()],
                      rewrites=[REWRITTEN], expected_status=500)

        self.assertEqual(calls, [1, 2])
        body = self.client.get(f"/query/{self.latest_query_id()}").json()
        # Still attempt 1 as committed, with attempt 1's own answer and failing verdict.
        self.assertEqual((body["status"], body["final_attempt_number"], body["final_answer"]),
                         (ANSWERED, 1, FIRST_ANSWER))
        self.assertEqual(body["attempts"][0]["evaluation"]["passed"], False)
        self.assertTrue(body["attempts"][1]["evaluation"]["passed"])
        self.assertIn("Attempt 1 is the recorded final attempt, but the selection rules choose "
                      "attempt 2", body["selection_reason"])


# --- /compare --------------------------------------------------------------------------------

class CompareSelectionTest(unittest.TestCase):
    setUp = compare_fixtures.CompareTest.setUp
    retrieved = compare_fixtures.CompareTest.retrieved
    evaluation = compare_fixtures.CompareTest.evaluation
    evaluator_for = compare_fixtures.CompareTest.evaluator_for
    answers_by_context = staticmethod(compare_fixtures.CompareTest.answers_by_context)
    post_compare = compare_fixtures.CompareTest.post_compare

    def assert_branch_consistent(self, branch, final, attempts):
        self.assertEqual((branch["final_attempt_number"], len(branch["attempts"])),
                         (final, attempts))
        selected = branch["attempts"][final - 1]
        self.assertEqual(branch["final_answer"], selected["answer"])
        self.assertEqual(choose_final_attempt(summaries(branch)).attempt.attempt_number, final)
        self.assertIsNotNone(branch["selection_reason"])
        self.assertEqual(self.client.get(f"/query/{branch['query_id']}").json(), branch)
        with self.Session() as db:
            self.assertEqual(db.get(Query, branch["query_id"]).final_attempt_number, final)
        return selected

    def test_both_branches_report_their_own_selected_attempt(self):
        first_answer = compare_fixtures.FIRST_ANSWER
        second_answer = compare_fixtures.SECOND_ANSWER
        for second_relevance, reli_final in ((0.95, 2), (0.3, 1)):
            with self.subTest(second_relevance=second_relevance):
                evaluator = self.evaluator_for({
                    first_answer: self.evaluation(0, 0.5, 0.9),
                    second_answer: self.evaluation(2, second_relevance, 0.9)})
                body, *_ = self.post_compare(
                    shared=self.retrieved([0, 1]),
                    generator=compare_fixtures.FakeClaude(self.answers_by_context),
                    evaluator=evaluator, rewrite_retrievals=[self.retrieved([2, 0, 1])])

                basic = self.assert_branch_consistent(body["basic"], 1, 1)
                self.assertEqual((body["basic"]["final_answer"], basic["evaluation"]["passed"]),
                                 (first_answer, False))
                self.assertIn("Basic mode", body["basic"]["selection_reason"])
                reli = self.assert_branch_consistent(body["reli"], reli_final, 2)
                self.assertEqual(reli["evaluation"]["answer_relevance"],
                                 0.5 if reli_final == 1 else second_relevance)
                self.assertTrue(body["reli"]["selection_reason"].startswith(
                    f"Attempt {reli_final} was selected over attempt {3 - reli_final}"))

    def test_failed_branch_records_its_final_attempt(self):
        real_set_final = query_pipeline.set_final_attempt

        def set_final_attempt(db, query, attempt_number, status):
            if query.mode == "basic":
                raise RuntimeError("database unavailable")
            return real_set_final(db, query, attempt_number, status)

        first_answer = compare_fixtures.FIRST_ANSWER
        with patch("app.services.query_pipeline.set_final_attempt",
                   side_effect=set_final_attempt):
            body, *_ = self.post_compare(
                shared=self.retrieved([0, 1]),
                generator=compare_fixtures.FakeClaude(lambda *_: first_answer),
                evaluator=self.evaluator_for({first_answer: self.evaluation(0, 0.95, 0.9)}))

        basic = body["basic"]
        self.assertEqual((basic["status"], basic["final_answer"], basic["final_attempt_number"]),
                         (ERROR, ERROR_MESSAGE, 1))
        with self.Session() as db:
            query = db.get(Query, basic["query_id"])
            self.assertEqual((query.final_status, query.final_attempt_number), (ERROR, 1))
            self.assertEqual([a.attempt_number for a in db.scalars(
                select(Answer).where(Answer.query_id == query.id))], [1])
        self.assert_branch_consistent(body["reli"], 1, 1)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
