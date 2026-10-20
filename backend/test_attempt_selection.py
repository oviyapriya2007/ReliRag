"""RELI-RAG Day 4: unit tests for choosing the final answer attempt.

Usage (from the project root or backend/):
    python backend/test_attempt_selection.py

Offline: pure logic only, so no database, embedding, or Claude call is used.
Exits with status 0 when all tests pass, 1 otherwise.
"""

import os
import sys
import unittest
from pathlib import Path

# Must be set before `app` is imported so the app never connects to the real database.
os.environ["DATABASE_URL"] = "sqlite://"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.services.attempt_selection import (  # noqa: E402
    AttemptEvaluation,
    AttemptSummary,
    select_final_attempt,
    valid_scores,
)
from app.services.evaluator import (  # noqa: E402
    EVALUATOR_ERROR,
    IRRELEVANT_RETRIEVAL,
    MISSING_INFO,
    UNSUPPORTED_CLAIM,
)
from app.services.generator import ANSWERED  # noqa: E402
from app.services.query_pipeline import ERROR  # noqa: E402
from app.services.similarity_gate import INSUFFICIENT_EVIDENCE  # noqa: E402


def evaluation(faithfulness=0.9, answer_relevance=0.9, context_relevance=0.9, *,
               passed=None, failure_type=None) -> AttemptEvaluation:
    if passed is None:
        passed = failure_type is None
    return AttemptEvaluation(passed=passed, failure_type=failure_type, faithfulness=faithfulness,
                             answer_relevance=answer_relevance,
                             context_relevance=context_relevance)


def failing(faithfulness, answer_relevance, context_relevance,
            failure_type=UNSUPPORTED_CLAIM) -> AttemptEvaluation:
    return evaluation(faithfulness, answer_relevance, context_relevance, failure_type=failure_type)


def attempt(number: int, status: str | None = ANSWERED,
            scores: AttemptEvaluation | None = None) -> AttemptSummary:
    return AttemptSummary(attempt_number=number, status=status, evaluation=scores)


FIRST = attempt(1, scores=failing(0.5, 0.9, 0.4))
EVALUATOR_ERROR_EVALUATION = AttemptEvaluation(
    passed=False, failure_type=EVALUATOR_ERROR,
    faithfulness=None, answer_relevance=None, context_relevance=None,
)


class KeepFirstAttemptTest(unittest.TestCase):
    def assert_keeps_first(self, second: AttemptSummary, first: AttemptSummary = FIRST):
        self.assertIs(select_final_attempt([first, second]), first)

    def test_second_attempt_without_evaluation(self):
        self.assert_keeps_first(attempt(2, scores=None))

    def test_second_attempt_with_evaluator_error(self):
        self.assert_keeps_first(attempt(2, scores=EVALUATOR_ERROR_EVALUATION))

    def test_evaluator_error_is_ignored_even_when_marked_passed(self):
        self.assert_keeps_first(attempt(2, scores=evaluation(
            1.0, 1.0, 1.0, passed=True, failure_type=EVALUATOR_ERROR)))

    def test_second_attempt_not_answered(self):
        for status in (INSUFFICIENT_EVIDENCE, ERROR, None):
            with self.subTest(status=status):
                self.assert_keeps_first(attempt(2, status=status, scores=evaluation(1.0, 1.0, 1.0)))

    def test_second_attempt_with_missing_or_invalid_scores(self):
        cases = {
            "missing faithfulness": evaluation(None, 1.0, 1.0),
            "missing answer relevance": evaluation(1.0, None, 1.0),
            "missing context relevance": evaluation(1.0, 1.0, None),
            "NaN score": evaluation(float("nan"), 1.0, 1.0),
            "infinite score": evaluation(1.0, float("inf"), 1.0),
        }
        for name, scores in cases.items():
            with self.subTest(name):
                self.assert_keeps_first(attempt(2, scores=scores))

    def test_faithfulness_regression_beyond_the_limit_is_rejected(self):
        cases = {
            "more complete, failing": (FIRST, failing(0.44, 1.0, 1.0)),
            "passing where first fails": (attempt(1, scores=failing(1.0, 0.75, 1.0, MISSING_INFO)),
                                          evaluation(0.94, 0.9, 0.9)),
            "much more complete, failing": (
                attempt(1, scores=failing(1.0, 0.5, 0.3, MISSING_INFO)),
                failing(0.93, 0.85, 0.65, IRRELEVANT_RETRIEVAL)),
        }
        for name, (first, second_scores) in cases.items():
            with self.subTest(name):
                self.assert_keeps_first(attempt(2, scores=second_scores), first)

    def test_small_faithfulness_regression_needs_a_meaningful_gain(self):
        # Only 0.05 more complete: below MIN_COMPLETENESS_GAIN, so lower faithfulness loses.
        self.assert_keeps_first(attempt(2, scores=failing(0.47, 0.95, 1.0)))

    def test_less_complete_answer_with_higher_context_relevance_is_rejected(self):
        first = attempt(1, scores=failing(1.0, 0.75, 0.5, MISSING_INFO))
        cases = {
            "beyond tolerance": failing(1.0, 0.5, 1.0, MISSING_INFO),
            "within tolerance, equally faithful": failing(1.0, 0.72, 1.0, MISSING_INFO),
        }
        for name, scores in cases.items():
            with self.subTest(name):
                self.assert_keeps_first(attempt(2, scores=scores), first)

    def test_failing_attempt_never_replaces_a_passing_one(self):
        first = attempt(1, scores=evaluation(0.85, 0.85, 0.85))
        self.assert_keeps_first(attempt(2, scores=failing(1.0, 1.0, 0.79, IRRELEVANT_RETRIEVAL)),
                                first)

    def test_passing_attempt_with_invalid_scores_never_replaces_first(self):
        for first in (FIRST, attempt(1, status=ERROR)):
            with self.subTest(first=first.status):
                self.assert_keeps_first(attempt(2, scores=evaluation(
                    float("nan"), 1.0, 1.0, passed=True)), first)

    def test_no_overall_improvement_is_rejected(self):
        cases = {
            "equal scores": failing(0.5, 0.9, 0.4),
            "equal overall": failing(0.6, 0.8, 0.4, MISSING_INFO),
            "lower overall": failing(0.5, 0.7, 0.4),
        }
        for name, scores in cases.items():
            with self.subTest(name):
                self.assert_keeps_first(attempt(2, scores=scores))

    def test_passing_second_attempt_with_lower_faithfulness_and_average_is_rejected(self):
        first = attempt(1, scores=failing(1.0, 0.75, 1.0, MISSING_INFO))
        self.assert_keeps_first(attempt(2, scores=evaluation(0.85, 0.85, 0.85)), first)

    def test_unevaluated_first_attempt_is_only_replaced_by_a_pass(self):
        firsts = {
            "gate rejected": attempt(1, status=INSUFFICIENT_EVIDENCE),
            "Claude error": attempt(1, status=ERROR),
            "evaluator error": attempt(1, scores=EVALUATOR_ERROR_EVALUATION),
            "missing scores": attempt(1, scores=evaluation(None, None, None, passed=False,
                                                           failure_type=UNSUPPORTED_CLAIM)),
        }
        for name, first in firsts.items():
            with self.subTest(name):
                self.assert_keeps_first(attempt(2, scores=failing(0.7, 0.9, 0.9)), first)


class SelectSecondAttemptTest(unittest.TestCase):
    def assert_selects_second(self, second: AttemptSummary, first: AttemptSummary = FIRST):
        self.assertIs(select_final_attempt([first, second]), second)

    def test_passing_second_attempt(self):
        self.assert_selects_second(attempt(2, scores=evaluation(1.0, 0.95, 0.86)))

    def test_passing_second_attempt_replaces_unevaluated_first_attempt(self):
        for first in (attempt(1, status=INSUFFICIENT_EVIDENCE), attempt(1, status=ERROR),
                      attempt(1, scores=EVALUATOR_ERROR_EVALUATION), attempt(1, scores=None)):
            with self.subTest(status=first.status, evaluation=first.evaluation):
                self.assert_selects_second(attempt(2, scores=evaluation(0.9, 0.9, 0.9)), first)

    def test_improvement_with_equal_faithfulness(self):
        self.assert_selects_second(
            attempt(2, scores=failing(0.5, 0.9, 0.7)))

    def test_improvement_with_higher_faithfulness(self):
        self.assert_selects_second(
            attempt(2, scores=failing(0.75, 0.9, 0.5, IRRELEVANT_RETRIEVAL)))

    def test_float_noise_does_not_count_as_lower_faithfulness(self):
        first = attempt(1, scores=failing(0.1 + 0.2, 0.9, 0.4))
        self.assert_selects_second(attempt(2, scores=failing(0.3, 0.9, 0.6)), first)

    def test_passing_attempt_beats_failing_attempt(self):
        cases = {
            # Lower average than the failing first attempt, but it passes and is more faithful.
            "equal average": (failing(0.85, 0.79, 0.96, MISSING_INFO), evaluation(0.9, 0.85, 0.85)),
            "lower average": (failing(0.8, 0.7, 1.0, MISSING_INFO), evaluation(0.85, 0.8, 0.8)),
            # Less complete, slightly less faithful, but passes where the first attempt fails.
            "small faithfulness loss": (failing(1.0, 1.0, 0.7, IRRELEVANT_RETRIEVAL),
                                        evaluation(0.96, 0.85, 0.9)),
        }
        for name, (first_scores, second_scores) in cases.items():
            with self.subTest(name):
                self.assert_selects_second(attempt(2, scores=second_scores),
                                           attempt(1, scores=first_scores))

    def test_more_complete_answer_with_small_faithfulness_regression(self):
        first = attempt(1, scores=failing(1.0, 0.5, 0.3, MISSING_INFO))
        for scores in (failing(0.96, 0.6, 0.4, MISSING_INFO),
                       failing(0.95, 0.75, 0.2, MISSING_INFO)):
            with self.subTest(scores=scores):
                self.assert_selects_second(attempt(2, scores=scores), first)

    def test_slightly_less_complete_but_more_faithful_answer(self):
        self.assert_selects_second(attempt(2, scores=failing(0.7, 0.87, 0.4)))

    def test_more_complete_answer_with_lower_context_relevance(self):
        self.assert_selects_second(attempt(2, scores=failing(0.5, 1.0, 0.1)))


class SelectFinalAttemptTest(unittest.TestCase):
    def test_single_attempt_is_selected(self):
        for only in (FIRST, attempt(1, status=INSUFFICIENT_EVIDENCE), attempt(1, status=ERROR)):
            with self.subTest(status=only.status):
                self.assertIs(select_final_attempt([only]), only)

    def test_attempts_are_ordered_by_attempt_number(self):
        worse_second = attempt(2, scores=failing(0.4, 0.5, 0.4))
        self.assertIs(select_final_attempt([worse_second, FIRST]), FIRST)

    def test_empty_attempts_are_rejected(self):
        with self.assertRaises(ValueError):
            select_final_attempt([])

    def test_valid_scores(self):
        self.assertEqual(valid_scores(FIRST), (0.5, 0.9, 0.4))
        self.assertIsNone(valid_scores(attempt(1, scores=None)))
        self.assertIsNone(valid_scores(attempt(1, scores=EVALUATOR_ERROR_EVALUATION)))
        self.assertIsNone(valid_scores(attempt(1, status=INSUFFICIENT_EVIDENCE,
                                                scores=evaluation(1.0, 1.0, 1.0))))


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
