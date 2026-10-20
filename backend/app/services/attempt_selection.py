import math
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.evaluator import EVALUATOR_ERROR
from app.services.generator import ANSWERED

# Tolerance for float noise when comparing scores.
_EPSILON = 1e-9
# A candidate may lose at most this much answer relevance (completeness) and still be preferred,
# and only when it is clearly more faithful.
ANSWER_RELEVANCE_TOLERANCE = 0.05
# Largest faithfulness loss a candidate may have, and only alongside a meaningful completeness
# gain or a pass where the current attempt fails.
MAX_FAITHFULNESS_REGRESSION = 0.05
# Smallest answer relevance gain that counts as meaningfully more complete.
MIN_COMPLETENESS_GAIN = 0.10


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

    The candidate needs a usable evaluation. When `current` has no usable evaluation there is
    nothing to compare against, so only a passing candidate replaces it. Otherwise:

    - A candidate that fails never replaces a passing `current`.
    - Faithfulness may drop by at most MAX_FAITHFULNESS_REGRESSION, and only if the candidate
      passes where `current` fails or gains at least MIN_COMPLETENESS_GAIN answer relevance.
    - A candidate that passes where `current` fails then wins.
    - With the same pass status, answer relevance may drop by at most
      ANSWER_RELEVANCE_TOLERANCE, and only for a more faithful candidate. A more complete
      candidate wins, then a more faithful one; context relevance only breaks a tie.

    Anything else keeps `current`.
    """
    candidate_scores = valid_scores(candidate)
    if candidate_scores is None:
        return False
    current_scores = valid_scores(current)
    if current_scores is None:
        return candidate.evaluation.passed is True

    faithfulness, completeness, context = candidate_scores
    current_faithfulness, current_completeness, current_context = current_scores
    candidate_passes = candidate.evaluation.passed is True
    current_passes = current.evaluation.passed is True
    if current_passes and not candidate_passes:
        return False

    gains_pass = candidate_passes and not current_passes
    gains_completeness = completeness >= current_completeness + MIN_COMPLETENESS_GAIN - _EPSILON
    if faithfulness < current_faithfulness - MAX_FAITHFULNESS_REGRESSION - _EPSILON:
        return False
    if faithfulness < current_faithfulness - _EPSILON and not (gains_pass or gains_completeness):
        return False
    if gains_pass:
        return True

    if completeness < current_completeness - ANSWER_RELEVANCE_TOLERANCE - _EPSILON:
        return False
    if completeness > current_completeness + _EPSILON:
        return True
    if completeness < current_completeness - _EPSILON:
        return faithfulness > current_faithfulness + _EPSILON
    if faithfulness > current_faithfulness + _EPSILON:
        return True
    if faithfulness < current_faithfulness - _EPSILON:
        return False
    return context > current_context + _EPSILON


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
