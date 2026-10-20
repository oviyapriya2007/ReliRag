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


@dataclass(frozen=True)
class FinalSelection:
    attempt: AttemptSummary
    reason: str


def valid_scores(attempt: AttemptSummary) -> tuple[float, float, float] | None:
    """(faithfulness, answer_relevance, context_relevance), or None if the attempt has no
    usable evaluation: not ANSWERED, never evaluated, `evaluator_error`, or a missing,
    non-finite, or out-of-range (not 0-1) score."""
    return None if unusable_reason(attempt) else (
        attempt.evaluation.faithfulness,
        attempt.evaluation.answer_relevance,
        attempt.evaluation.context_relevance,
    )


def unusable_reason(attempt: AttemptSummary) -> str | None:
    """Why `attempt` has no usable evaluation, or None if it has one."""
    evaluation = attempt.evaluation
    if attempt.status != ANSWERED:
        return f"its status is {attempt.status or 'unknown'}"
    if evaluation is None:
        return "it has no saved evaluation"
    if evaluation.failure_type == EVALUATOR_ERROR:
        return "its evaluation is an evaluator error"
    scores = (evaluation.faithfulness, evaluation.answer_relevance, evaluation.context_relevance)
    if any(score is None or not math.isfinite(score) or not 0.0 <= score <= 1.0
           for score in scores):
        return "its evaluation has missing or invalid scores"
    return None


def passes(attempt: AttemptSummary) -> bool:
    """True only for a usable evaluation that passed with no failure type."""
    return (valid_scores(attempt) is not None and attempt.evaluation.passed is True
            and attempt.evaluation.failure_type is None)


def overall_score(scores: Sequence[float]) -> float:
    """Unweighted mean of the evaluation scores."""
    return sum(scores) / len(scores)


def compare_attempts(candidate: AttemptSummary, current: AttemptSummary) -> tuple[bool, str]:
    """(whether `candidate` should replace `current` as the final attempt, why).

    The candidate needs a usable evaluation. When `current` has no usable evaluation there is
    nothing to compare against, so only a passing candidate replaces it. Otherwise:

    - A candidate that fails never replaces a passing `current`.
    - Faithfulness may drop by at most MAX_FAITHFULNESS_REGRESSION, and only if the candidate
      passes where `current` fails or gains at least MIN_COMPLETENESS_GAIN answer relevance.
    - A candidate that passes where `current` fails then wins.
    - With the same pass status, answer relevance may drop by at most
      ANSWER_RELEVANCE_TOLERANCE, and only for a more faithful candidate. A more complete
      candidate wins, then a more faithful one; context relevance only breaks a tie.

    Anything else, including an exact tie, keeps `current`.
    """
    new, old = f"attempt {candidate.attempt_number}", f"attempt {current.attempt_number}"
    candidate_unusable = unusable_reason(candidate)
    if candidate_unusable:
        return False, f"{new} has no usable evaluation ({candidate_unusable})"
    current_unusable = unusable_reason(current)
    candidate_passes = passes(candidate)
    if current_unusable:
        if candidate_passes:
            return True, f"{old} has no usable evaluation ({current_unusable}) and {new} passed"
        return False, (f"{old} has no usable evaluation ({current_unusable}) and {new} did "
                       f"not pass, so the earlier attempt is kept")

    faithfulness, completeness, context = valid_scores(candidate)
    current_faithfulness, current_completeness, current_context = valid_scores(current)
    current_passes = passes(current)
    if current_passes and not candidate_passes:
        return False, f"{old} passed and {new} did not"

    def change(name: str, before: float, after: float) -> str:
        return f"{name} {before:.2f} to {after:.2f}"

    faithfulness_change = change("faithfulness", current_faithfulness, faithfulness)
    completeness_change = change("answer relevance", current_completeness, completeness)
    gains_pass = candidate_passes and not current_passes
    gains_completeness = completeness >= current_completeness + MIN_COMPLETENESS_GAIN - _EPSILON
    if faithfulness < current_faithfulness - MAX_FAITHFULNESS_REGRESSION - _EPSILON:
        return False, f"{new} lost too much faithfulness ({faithfulness_change})"
    if faithfulness < current_faithfulness - _EPSILON and not (gains_pass or gains_completeness):
        return False, (f"{new} was less faithful ({faithfulness_change}) without passing or "
                       f"becoming meaningfully more complete")
    if gains_pass:
        return True, f"{new} passed and {old} did not"

    if completeness < current_completeness - ANSWER_RELEVANCE_TOLERANCE - _EPSILON:
        return False, f"{new} was less complete ({completeness_change})"
    if completeness > current_completeness + _EPSILON:
        return True, f"{new} was more complete ({completeness_change})"
    if completeness < current_completeness - _EPSILON:
        if faithfulness > current_faithfulness + _EPSILON:
            return True, (f"{new} was more faithful ({faithfulness_change}) and at most "
                          f"slightly less complete ({completeness_change})")
        return False, f"{new} was less complete ({completeness_change}) and not more faithful"
    if faithfulness > current_faithfulness + _EPSILON:
        return True, f"{new} was equally complete and more faithful ({faithfulness_change})"
    if faithfulness < current_faithfulness - _EPSILON:
        return False, f"{new} was equally complete and less faithful ({faithfulness_change})"
    if context > current_context + _EPSILON:
        return True, (f"{new} tied on faithfulness and answer relevance and had higher "
                      f"{change('context relevance', current_context, context)}")
    return False, (f"{new} did not score higher than {old} on faithfulness, answer relevance, "
                   f"or context relevance, so the earlier attempt is kept on a tie")


def is_better_attempt(candidate: AttemptSummary, current: AttemptSummary) -> bool:
    """True if `candidate` should replace `current` as the final attempt (see
    `compare_attempts`)."""
    return compare_attempts(candidate, current)[0]


def choose_final_attempt(attempts: Sequence[AttemptSummary]) -> FinalSelection:
    """The attempt the query should report, and why.

    Attempts are considered in `attempt_number` order; the first is kept unless a later one
    is better by `compare_attempts`. Raises `ValueError` if `attempts` is empty.
    """
    if not attempts:
        raise ValueError("attempts must not be empty")
    ordered = sorted(attempts, key=lambda attempt: attempt.attempt_number)
    selected = ordered[0]
    if len(ordered) == 1:
        return FinalSelection(selected, f"Attempt {selected.attempt_number} is the only attempt.")
    reasons = []
    for candidate in ordered[1:]:
        better, why = compare_attempts(candidate, selected)
        winner, loser = (candidate, selected) if better else (selected, candidate)
        reasons.append(f"Attempt {winner.attempt_number} was selected over attempt "
                       f"{loser.attempt_number}: {why}.")
        selected = winner
    return FinalSelection(selected, " ".join(reasons))


def select_final_attempt(attempts: Sequence[AttemptSummary]) -> AttemptSummary:
    """Pick the attempt whose answer the query should report (see `choose_final_attempt`)."""
    return choose_final_attempt(attempts).attempt


def describe_final_selection(
    mode: str, attempts: Sequence[AttemptSummary], final_attempt_number: int | None
) -> str | None:
    """Why the query reports attempt `final_attempt_number`, from its recorded attempts.

    The selection is replayed with `choose_final_attempt`; if the recorded final attempt is not
    the one the rules pick (e.g. a run interrupted before it recorded its choice), that is
    stated instead of a reason. None when there are no attempts or no recorded final attempt.
    """
    if not attempts or final_attempt_number is None:
        return None
    ordered = sorted(attempts, key=lambda attempt: attempt.attempt_number)
    if len(ordered) == 1:
        only = ordered[0]
        if only.attempt_number != final_attempt_number:
            return (f"The recorded final attempt {final_attempt_number} is not among the "
                    f"recorded attempts.")
        if mode == "basic":
            return f"Basic mode runs a single attempt; attempt {only.attempt_number} is reported."
        return f"Attempt {only.attempt_number} is the only attempt: {_no_correction(only)}."
    selection = choose_final_attempt(ordered)
    if selection.attempt.attempt_number != final_attempt_number:
        return (f"Attempt {final_attempt_number} is the recorded final attempt, but the selection "
                f"rules choose attempt {selection.attempt.attempt_number} from the recorded "
                f"attempts; the run may have stopped before recording its choice.")
    return selection.reason


def _no_correction(attempt: AttemptSummary) -> str:
    if attempt.status != ANSWERED:
        return f"it was not answered ({attempt.status or 'unknown status'}), so no correction runs"
    if passes(attempt):
        return "it passed its evaluation, so no correction was needed"
    if attempt.evaluation is None:
        return "it has no saved evaluation, so no correction was attempted"
    if attempt.evaluation.failure_type == EVALUATOR_ERROR:
        return "its evaluation is an evaluator error, so no correction was attempted"
    return "it did not pass its evaluation and no correction attempt was recorded"
