import logging
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from app.config import settings
from app.services.evaluator import (
    IRRELEVANT_RETRIEVAL,
    MISSING_INFO,
    PARTIALLY_SUPPORTED,
    UNSUPPORTED,
    UNSUPPORTED_CLAIM,
)
from app.services.llm import LLMResult, call_claude

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


def choose_correction(
    evaluation: EvaluationLike | None, *, threshold: float | None = None
) -> str | None:
    """REWRITE, STRICT, or None (no correction) for a failed evaluation.

    `missing_info` and `irrelevant_retrieval` are retrieval problems: REWRITE.
    `unsupported_claim` is a generation problem when the retrieved context was adequate
    (context relevance at least `threshold`): STRICT regeneration on the same chunks;
    otherwise the retrieval is at fault too, so REWRITE. Passing evaluations,
    `evaluator_error`, and missing evaluations get no correction.
    `threshold=None` uses EVALUATOR_PASS_THRESHOLD.
    """
    if evaluation is None or evaluation.passed:
        return None
    if evaluation.failure_type in (MISSING_INFO, IRRELEVANT_RETRIEVAL):
        return REWRITE
    if evaluation.failure_type == UNSUPPORTED_CLAIM:
        if threshold is None:
            threshold = settings.evaluator_pass_threshold
        context = evaluation.context_relevance
        adequate = context is not None and math.isfinite(context) and context >= threshold
        return STRICT if adequate else REWRITE
    return None


def rejected_claim_texts(claims: Iterable[ClaimLike]) -> list[str]:
    """Texts of the unsupported and partially supported claims, in order."""
    return [claim.claim_text for claim in claims
            if claim.verdict in (UNSUPPORTED, PARTIALLY_SUPPORTED)]


def build_rewrite_prompt(question: str, feedback: str | None, failure_type: str | None) -> str:
    problem = FAILURE_DESCRIPTIONS.get(failure_type, DEFAULT_FAILURE_DESCRIPTION)
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
    failure_type: str | None = None,
    max_tokens: int | None = None,
) -> RewriteResult:
    """Rewrite `question` into a better retrieval query using the evaluator's feedback.

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
