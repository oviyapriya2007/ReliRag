import math
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.evaluator import EVALUATOR_ERROR
from app.services.generator import ANSWERED

# Tolerance for float noise when comparing scores.
_EPSILON = 1e-9


@dataclass(frozen=True)
class AttemptEvaluation:
    passed: bool | None
    failure_type: str | None
    faithfulness: float | None
    answer_relevance: float | None
    context_relevance: float | None


@dataclass(frozen=True)
class AttemptSummary:
    attempt_number: int
    status: str | None
    evaluation: AttemptEvaluation | None = None


def valid_scores(attempt: AttemptSummary) -> tuple[float, float, float] | None:
    """(faithfulness, answer_relevance, context_relevance), or None if the attempt has no
    usable evaluation: not ANSWERED, never evaluated, `evaluator_error`, or a missing or
    non-finite score."""
    evaluation = attempt.evaluation
    if attempt.status != ANSWERED or evaluation is None:
        return None
    if evaluation.failure_type == EVALUATOR_ERROR:
        return None
    scores = (evaluation.faithfulness, evaluation.answer_relevance, evaluation.context_relevance)
    if any(score is None or not math.isfinite(score) for score in scores):
        return None
    return scores


def overall_score(scores: Sequence[float]) -> float:
    """Unweighted mean of the evaluation scores."""
    return sum(scores) / len(scores)


def is_better_attempt(candidate: AttemptSummary, current: AttemptSummary) -> bool:
    """True if `candidate` should replace `current` as the final attempt.

    The candidate needs a usable evaluation. When `current` has one too, the candidate must
    raise the overall score without lowering faithfulness, even if the candidate passes.
    When `current` has no usable evaluation there is nothing to compare against, so only a
    passing candidate replaces it.
    """
    candidate_scores = valid_scores(candidate)
    if candidate_scores is None:
        return False
    current_scores = valid_scores(current)
    if current_scores is None:
        return candidate.evaluation.passed is True
    return (
        candidate_scores[0] >= current_scores[0] - _EPSILON
        and overall_score(candidate_scores) > overall_score(current_scores) + _EPSILON
    )


def select_final_attempt(attempts: Sequence[AttemptSummary]) -> AttemptSummary:
    """Pick the attempt whose answer the query should report.

    Attempts are considered in `attempt_number` order; the first is kept unless a later one
    is better by `is_better_attempt`. Raises `ValueError` if `attempts` is empty.
    """
    if not attempts:
        raise ValueError("attempts must not be empty")
    ordered = sorted(attempts, key=lambda attempt: attempt.attempt_number)
    selected = ordered[0]
    for candidate in ordered[1:]:
        if is_better_attempt(candidate, selected):
            selected = candidate
    return selected
