import logging
import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from app.config import settings
from app.services.evaluator import (
    IRRELEVANT_RETRIEVAL,
    MISSING_INFO,
    PARTIALLY_SUPPORTED,
    SUPPORTED,
    UNSUPPORTED,
    UNSUPPORTED_CLAIM,
)
from app.services.llm import LLMResult, call_claude
from app.services.retrieval import RetrievedChunk

logger = logging.getLogger(__name__)

REWRITE = "rewrite"
STRICT = "strict"

RETRY_TOP_K = 8
MAX_REWRITE_CHARS = 500
REWRITE_MAX_TOKENS = 256

_LABEL_RE = re.compile(r"^(?:(?:rewritten|new|search|improved)\s+)*query\s*:\s*", re.IGNORECASE)
_QUOTE_PAIRS = {('"', '"'), ("'", "'"), ("`", "`"), ("\u201c", "\u201d"), ("\u2018", "\u2019")}

FAILURE_DESCRIPTIONS = {
    MISSING_INFO: "The answer did not fully address the question.",
    IRRELEVANT_RETRIEVAL: "The retrieved passages did not contain the information needed to "
                          "answer the question.",
    UNSUPPORTED_CLAIM: "The answer made claims that the retrieved passages did not support.",
}
DEFAULT_FAILURE_DESCRIPTION = "The answer did not pass evaluation."

REWRITE_SYSTEM_PROMPT = f"""You rewrite search queries for a retrieval system that finds passages \
in a collection of documents by semantic similarity. A question was answered from the passages \
retrieved for it, and an evaluator found a problem with the result. Write one new search query that \
is more likely to retrieve the passages needed to answer the original question.

Rules:
- Keep the original question's intent and every entity, constraint, and term it names.
- Use the evaluator feedback to target the information that was missing or the topic the retrieved \
passages missed. You may add closely related terms or synonyms.
- Do not answer the question, and do not add facts, names, or numbers that appear in neither the \
question nor the feedback.
- Reply with only the query, on a single line, with no quotes, labels, or explanation, in at most \
{MAX_REWRITE_CHARS} characters."""


class EvaluationLike(Protocol):
    passed: bool | None
    failure_type: str | None
    context_relevance: float | None


class ClaimLike(Protocol):
    claim_text: str
    verdict: str | None


@dataclass(frozen=True)
class RewriteResult:
    query: str
    rewritten: bool
    fallback_reason: str | None
    llm: LLMResult | None


def retry_top_k(k: int) -> int:
    """Chunks a REWRITE retry retrieves: RETRY_TOP_K, but never fewer than the requested `k`."""
    return max(k, RETRY_TOP_K)


def _below(score: float | None, threshold: float) -> bool:
    return score is not None and math.isfinite(score) and score < threshold


def failure_signals(
    evaluation: EvaluationLike | None, *, threshold: float | None = None
) -> list[str]:
    """Every problem a failed evaluation shows, starting with its stored `failure_type`.

    The stored label names only the first failing score; this adds the failure type of each
    other score below `threshold` (faithfulness, answer relevance, context relevance), so a
    correction can address all of them. Scores the evaluation does not carry are skipped.
    Passing evaluations, `evaluator_error`, unknown labels, and missing evaluations have none.
    `threshold=None` uses EVALUATOR_PASS_THRESHOLD.
    """
    if evaluation is None or evaluation.passed:
        return []
    if evaluation.failure_type not in FAILURE_DESCRIPTIONS:
        return []
    if threshold is None:
        threshold = settings.evaluator_pass_threshold
    signals = [evaluation.failure_type]
    for score, failure_type in (
        (getattr(evaluation, "faithfulness", None), UNSUPPORTED_CLAIM),
        (getattr(evaluation, "answer_relevance", None), MISSING_INFO),
        (evaluation.context_relevance, IRRELEVANT_RETRIEVAL),
    ):
        if failure_type not in signals and _below(score, threshold):
            signals.append(failure_type)
    return signals


def choose_correction(
    evaluation: EvaluationLike | None, *, threshold: float | None = None
) -> str | None:
    """REWRITE, STRICT, or None (no correction) for a failed evaluation.

    Uses every failure signal (see `failure_signals`), not just the stored label.
    Only an unsupported-claim problem with adequate context (context relevance known and at
    least `threshold`) and no other failing score is a pure generation problem: STRICT
    regeneration on the same chunks. Any missing information or weak retrieval needs new
    evidence: REWRITE (which also rejects unsupported claims when there are any, see
    `claims_to_reject`). Passing evaluations, `evaluator_error`, and missing evaluations get
    no correction. `threshold=None` uses EVALUATOR_PASS_THRESHOLD.
    """
    if threshold is None:
        threshold = settings.evaluator_pass_threshold
    signals = failure_signals(evaluation, threshold=threshold)
    if not signals:
        return None
    if signals == [UNSUPPORTED_CLAIM]:
        context = evaluation.context_relevance
        adequate = context is not None and math.isfinite(context) and context >= threshold
        return STRICT if adequate else REWRITE
    return REWRITE


def rejected_claim_texts(claims: Iterable[ClaimLike]) -> list[str]:
    """Texts of the unsupported and partially supported claims, in order."""
    return [claim.claim_text for claim in claims
            if claim.verdict in (UNSUPPORTED, PARTIALLY_SUPPORTED)]


def claims_to_reject(evaluation: EvaluationLike | None, *,
                     threshold: float | None = None) -> list[str]:
    """Claims a correction must avoid: the rejected claims when unsupported claims are a
    failure signal, else none (so a pure retrieval failure keeps its normal generation)."""
    if UNSUPPORTED_CLAIM not in failure_signals(evaluation, threshold=threshold):
        return []
    return rejected_claim_texts(getattr(evaluation, "claims", ()))


def supporting_chunks(
    chunks: Sequence[RetrievedChunk], claims: Iterable[ClaimLike]
) -> list[RetrievedChunk]:
    """The `chunks` that verified evidence points to, in their original order, each once.

    A chunk counts when it is the main or additional evidence of a supported or partially
    supported claim, or a verified passage that contradicts one; the evaluator only keeps
    evidence whose quote was found in that chunk. Stored claims carry only main evidence.
    """
    evidence: set[int | None] = set()
    for claim in claims:
        if claim.verdict not in (SUPPORTED, PARTIALLY_SUPPORTED):
            continue
        evidence.add(getattr(claim, "evidence_chunk_id", None))
        for chunk_id, _ in (*getattr(claim, "additional_evidence", ()),
                            *getattr(claim, "conflicting_evidence", ())):
            evidence.add(chunk_id)
    return [chunk for chunk in chunks if chunk.chunk_id in evidence]


def carry_over_chunks(
    chunks: Sequence[RetrievedChunk], evaluation: EvaluationLike | None, *,
    threshold: float | None = None,
) -> list[RetrievedChunk]:
    """The attempt's chunks a REWRITE retry keeps: its verified evidence first (see
    `supporting_chunks`), then, when the evaluator judged the passages adequate (context
    relevance at least `threshold`), every other chunk in rank order.

    Adequate passages can hold a part of the question the answer left out, which the new
    retrieval might not return; weak passages are not kept unless they back a claim.
    `threshold=None` uses EVALUATOR_PASS_THRESHOLD.
    """
    if evaluation is None:
        return []
    if threshold is None:
        threshold = settings.evaluator_pass_threshold
    kept = supporting_chunks(chunks, getattr(evaluation, "claims", ()))
    context = evaluation.context_relevance
    if context is None or not math.isfinite(context) or context < threshold:
        return kept
    ids = {chunk.chunk_id for chunk in kept}
    return [*kept, *(chunk for chunk in chunks if chunk.chunk_id not in ids)]


def describe_failures(failure_types: str | Sequence[str] | None) -> str:
    """Problem descriptions for the rewrite prompt, one per known failure type."""
    if failure_types is None or isinstance(failure_types, str):
        failure_types = [failure_types]
    descriptions = [FAILURE_DESCRIPTIONS[ft] for ft in failure_types if ft in FAILURE_DESCRIPTIONS]
    return " ".join(dict.fromkeys(descriptions)) or DEFAULT_FAILURE_DESCRIPTION


def build_rewrite_prompt(
    question: str, feedback: str | None, failure_type: str | Sequence[str] | None
) -> str:
    problem = describe_failures(failure_type)
    feedback = (feedback or "").strip() or "None given."
    return (f"<question>\n{question}\n</question>\n\n"
            f"<problem>\n{problem}\n</problem>\n\n"
            f"<feedback>\n{feedback}\n</feedback>")


def _unquote(text: str) -> str:
    if len(text) >= 2 and (text[0], text[-1]) in _QUOTE_PAIRS:
        return text[1:-1].strip()
    return text


def clean_rewrite(text: str, question: str) -> tuple[str | None, str | None]:
    """(rewritten query, None) if Claude's reply is usable, else (None, reason)."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None, "empty"
    if len(lines) > 1:
        return None, "multiple lines"
    rewritten = _unquote(_LABEL_RE.sub("", _unquote(lines[0])))
    rewritten = " ".join(rewritten.split())
    if not rewritten:
        return None, "empty"
    if len(rewritten) > MAX_REWRITE_CHARS:
        return None, "too long"
    if rewritten.casefold() == " ".join(question.split()).casefold():
        return None, "unchanged"
    return rewritten, None


def rewrite_query(
    question: str,
    feedback: str | None,
    *,
    failure_type: str | Sequence[str] | None = None,
    max_tokens: int | None = None,
) -> RewriteResult:
    """Rewrite `question` into a better retrieval query using the evaluator's feedback.

    `failure_type` is one failure type or several (see `failure_signals`).

    Never raises for Claude problems: if the call fails or the reply is empty, multi-line,
    longer than MAX_REWRITE_CHARS, or unchanged, the original question is returned with
    `rewritten=False` and the reason in `fallback_reason`.
    """
    question = question.strip()
    if not question:
        raise ValueError("question must not be empty")

    llm: LLMResult | None = None
    try:
        llm = call_claude(build_rewrite_prompt(question, feedback, failure_type),
                          system=REWRITE_SYSTEM_PROMPT,
                          max_tokens=max_tokens or REWRITE_MAX_TOKENS)
    except Exception as exc:
        # Broader than LLMError: call_claude lets some SDK errors through unwrapped.
        logger.warning("Query rewrite Claude call failed: %r", exc)
        return RewriteResult(question, False, f"Claude call failed: {exc}", None)

    rewritten, reason = clean_rewrite(llm.text, question)
    if rewritten is None:
        logger.warning("Query rewrite rejected (%s): %r", reason, llm.text[:200])
        return RewriteResult(question, False, reason, llm)
    return RewriteResult(rewritten, True, None, llm)
