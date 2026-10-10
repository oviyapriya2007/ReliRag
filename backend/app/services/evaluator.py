import logging
import re
import time
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from app.services.llm import LLMResult, call_claude
from app.services.retrieval import RetrievedChunk

logger = logging.getLogger(__name__)

SUPPORTED = "supported"
PARTIALLY_SUPPORTED = "partially_supported"
UNSUPPORTED = "unsupported"

UNSUPPORTED_CLAIM = "unsupported_claim"
MISSING_INFO = "missing_info"
IRRELEVANT_RETRIEVAL = "irrelevant_retrieval"
EVALUATOR_ERROR = "evaluator_error"

PASS_THRESHOLD = 0.80
EVALUATOR_MAX_TOKENS = 2048
MAX_PARSE_ATTEMPTS = 2

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)
_QUOTE_CHARS = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
                              "\u2013": "-", "\u2014": "-"})

SYSTEM_PROMPT = """You are a strict evaluator for a retrieval-augmented question answering system. \
You receive a question, the retrieved passages, and an answer generated from those passages. \
Passages are numbered in the order the answer's citation markers such as [1] refer to, and each has \
a chunk_id. Judge the answer only against the passages; do not use prior knowledge.

Task 1 - claims. Split the answer into atomic claims: short, self-contained factual statements that \
can each be checked on their own. Cover every factual statement in the answer. Leave citation markers \
out of claim_text. Give each claim a verdict:
- "supported": everything the claim states is explicitly stated in, or directly entailed by, one passage.
- "partially_supported": a passage supports part of the claim, but some detail is missing from the \
passage or the claim goes beyond what the passage states.
- "unsupported": no passage states the claim, or a passage contradicts it.
For "supported" and "partially_supported" claims, set evidence_chunk_id to the chunk_id of the passage \
that best supports the claim (the chunk_id value, not the passage number), and set evidence_quote to a \
short excerpt copied character for character from that passage: one contiguous span, no paraphrasing, \
no ellipses. For "unsupported" claims, set both to null.

Task 2 - answer_relevance, from 0 to 1: how directly and completely the answer addresses the question. \
Judge relevance and completeness only, not whether the answer is supported.
- 1.0: directly and completely answers every part of the question.
- 0.75: answers the main question but misses a minor part or includes some off-topic content.
- 0.5: partially answers; a significant part of the question is left unanswered.
- 0.25: mostly off-topic or evasive; little of it answers the question.
- 0.0: does not address the question.

Task 3 - context_relevance, from 0 to 1: how well the passages, taken together, contain the information \
needed to answer the question. Judge the passages alone, independently of the answer. Extra irrelevant \
passages lower the score only slightly when the needed information is present.
- 1.0: the passages contain all the information needed for a complete answer.
- 0.75: the passages contain most of the needed information; a minor detail is missing.
- 0.5: the passages contain some relevant information, but key information is missing.
- 0.25: the passages are only loosely related to the question.
- 0.0: the passages are unrelated to the question.
Intermediate values are allowed for both scores.

Task 4 - feedback: one to three sentences naming the specific problems (unsupported claims, unanswered \
parts of the question, information missing from the passages), or confirming that the answer is \
grounded and complete.

Return ONLY one JSON object, with no Markdown and no text before or after it, in exactly this shape:
{"claims": [{"claim_text": "...", "verdict": "supported", "evidence_chunk_id": 123, \
"evidence_quote": "..."}], "answer_relevance": 0.0, "context_relevance": 0.0, "feedback": "..."}"""

RETRY_INSTRUCTION = """Your previous reply was rejected: {error}
Return ONLY a single valid JSON object in exactly the required shape. Do not use Markdown or code \
fences, and do not write anything before or after the JSON."""

Score = Annotated[float, Field(ge=0.0, le=1.0)]


class ClaimJudgement(BaseModel):
    model_config = ConfigDict(strict=True)

    claim_text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    verdict: Literal["supported", "partially_supported", "unsupported"]
    evidence_chunk_id: int | None
    evidence_quote: str | None


class EvaluatorOutput(BaseModel):
    model_config = ConfigDict(strict=True)

    claims: Annotated[list[ClaimJudgement], Field(min_length=1)]
    answer_relevance: Score
    context_relevance: Score
    feedback: str


@dataclass(frozen=True)
class ClaimVerdict:
    claim_text: str
    verdict: str
    evidence_chunk_id: int | None
    evidence_quote: str | None
    claude_verdict: str
    evidence_error: str | None


@dataclass(frozen=True)
class EvaluationResult:
    faithfulness: float | None
    answer_relevance: float | None
    context_relevance: float | None
    passed: bool
    failure_type: str | None
    feedback: str | None
    claims: list[ClaimVerdict]
    model: str | None
    input_tokens: int
    output_tokens: int
    latency_ms: int
    llm_calls: int


def build_passages(chunks: Sequence[RetrievedChunk]) -> str:
    blocks = []
    for number, chunk in enumerate(chunks, start=1):
        page = f", page {chunk.page}" if chunk.page is not None else ""
        blocks.append(f"[{number}] chunk_id={chunk.chunk_id} (source: {chunk.document}{page})\n"
                      f"{chunk.text}")
    return "\n\n".join(blocks)


def build_prompt(question: str, answer: str, chunks: Sequence[RetrievedChunk]) -> str:
    return (f"<question>\n{question}\n</question>\n\n"
            f"<passages>\n{build_passages(chunks)}\n</passages>\n\n"
            f"<answer>\n{answer}\n</answer>")


def parse_evaluator_output(text: str) -> EvaluatorOutput:
    """Validate Claude's reply as one JSON object, tolerating a surrounding code fence.

    Raises `ValidationError` for invalid JSON as well as for schema violations.
    """
    text = text.strip()
    match = _FENCE_RE.match(text)
    return EvaluatorOutput.model_validate_json(match.group(1) if match else text)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_QUOTE_CHARS)
    return " ".join(text.split()).casefold()


def verify_evidence(claim: ClaimJudgement, chunks_by_id: Mapping[int, RetrievedChunk]) -> str | None:
    """Return why the claim's evidence is invalid, or None if it checks out.

    Evidence must reference a supplied chunk and quote text that occurs in that chunk
    (ignoring case, whitespace, and typographic quote/dash differences). Unsupported
    claims may omit evidence entirely.
    """
    chunk_id, quote = claim.evidence_chunk_id, claim.evidence_quote
    if chunk_id is None and not quote:
        return None if claim.verdict == UNSUPPORTED else "no evidence given"
    if chunk_id is None:
        return "evidence_quote given without evidence_chunk_id"
    chunk = chunks_by_id.get(chunk_id)
    if chunk is None:
        return f"evidence_chunk_id {chunk_id} is not one of the retrieved chunks"
    normalized_quote = _normalize(quote or "")
    if not normalized_quote:
        return f"no evidence_quote given for chunk {chunk_id}"
    if normalized_quote not in _normalize(chunk.text):
        return f"evidence_quote does not appear in chunk {chunk_id}"
    return None


def judge_claim(claim: ClaimJudgement, chunks_by_id: Mapping[int, RetrievedChunk]) -> ClaimVerdict:
    """Apply evidence verification: a claim with invalid evidence is always unsupported."""
    error = verify_evidence(claim, chunks_by_id)
    if error is not None:
        return ClaimVerdict(claim.claim_text, UNSUPPORTED, None, None, claim.verdict, error)
    return ClaimVerdict(claim.claim_text, claim.verdict, claim.evidence_chunk_id,
                        claim.evidence_quote, claim.verdict, None)


def compute_faithfulness(verdicts: Sequence[str]) -> float:
    """(supported + 0.5 * partially_supported) / total; 0.0 when there are no claims."""
    if not verdicts:
        return 0.0
    supported = sum(v == SUPPORTED for v in verdicts)
    partial = sum(v == PARTIALLY_SUPPORTED for v in verdicts)
    return (supported + 0.5 * partial) / len(verdicts)


def determine_failure_type(
    faithfulness: float,
    answer_relevance: float,
    context_relevance: float,
    threshold: float = PASS_THRESHOLD,
) -> str | None:
    """None if every score meets `threshold`, else the failure type of the first failing score.

    Scores are checked in the order faithfulness, answer relevance, context relevance.
    """
    for score, failure_type in (
        (faithfulness, UNSUPPORTED_CLAIM),
        (answer_relevance, MISSING_INFO),
        (context_relevance, IRRELEVANT_RETRIEVAL),
    ):
        if score < threshold:
            return failure_type
    return None


def _summarize(exc: ValidationError, limit: int = 3) -> str:
    errors = exc.errors(include_url=False)
    parts = [f"{'.'.join(map(str, e['loc'])) or 'reply'}: {e['msg']}" for e in errors[:limit]]
    if len(errors) > limit:
        parts.append(f"and {len(errors) - limit} more error(s)")
    return "; ".join(parts)


def evaluate_answer(
    question: str,
    answer: str,
    chunks: Sequence[RetrievedChunk],
    *,
    threshold: float = PASS_THRESHOLD,
    max_tokens: int | None = None,
) -> EvaluationResult:
    """Verify `answer` claim by claim against `chunks` and score it via Claude (temperature 0).

    Faithfulness is computed here from the verified verdicts; Claude only scores answer and
    context relevance. An invalid reply is retried once; if Claude fails or the retry is also
    invalid, the result has `passed=False` and `failure_type=EVALUATOR_ERROR` instead of raising.
    """
    question, answer = question.strip(), answer.strip()
    if not question:
        raise ValueError("question must not be empty")
    if not answer:
        raise ValueError("answer must not be empty")
    if not chunks:
        raise ValueError("chunks must not be empty")

    prompt = build_prompt(question, answer, chunks)
    request = prompt
    calls: list[LLMResult] = []
    output: EvaluatorOutput | None = None
    error: str | None = None
    started = time.perf_counter()
    try:
        for attempt in range(1, MAX_PARSE_ATTEMPTS + 1):
            llm = call_claude(request, system=SYSTEM_PROMPT, temperature=0,
                              max_tokens=max_tokens or EVALUATOR_MAX_TOKENS)
            calls.append(llm)
            try:
                output = parse_evaluator_output(llm.text)
                break
            except ValidationError as exc:
                error = _summarize(exc)
                logger.warning("Evaluator reply invalid: attempt=%d stop_reason=%s error=%s",
                               attempt, llm.stop_reason, error)
                request = f"{prompt}\n\n{RETRY_INSTRUCTION.format(error=error)}"
    except Exception as exc:
        # Broader than LLMError: call_claude lets some SDK errors through unwrapped, e.g. the
        # TypeError raised when no API key is configured.
        error = str(exc) or type(exc).__name__
        logger.warning("Evaluator Claude call failed: %r", exc)

    usage = {
        "model": calls[-1].model if calls else None,
        "input_tokens": sum(c.input_tokens for c in calls),
        "output_tokens": sum(c.output_tokens for c in calls),
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "llm_calls": len(calls),
    }
    if output is None:
        return EvaluationResult(
            faithfulness=None, answer_relevance=None, context_relevance=None,
            passed=False, failure_type=EVALUATOR_ERROR,
            feedback=f"Evaluation failed: {error}", claims=[], **usage,
        )

    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    claims = [judge_claim(claim, chunks_by_id) for claim in output.claims]
    faithfulness = compute_faithfulness([c.verdict for c in claims])
    failure_type = determine_failure_type(
        faithfulness, output.answer_relevance, output.context_relevance, threshold
    )

    feedback = output.feedback.strip()
    invalid = sum(c.evidence_error is not None and c.claude_verdict != UNSUPPORTED for c in claims)
    if invalid:
        feedback = (f"{feedback} {invalid} claim(s) cited evidence that could not be verified "
                    f"against the retrieved chunks and were marked unsupported.").strip()

    return EvaluationResult(
        faithfulness=faithfulness,
        answer_relevance=output.answer_relevance,
        context_relevance=output.context_relevance,
        passed=failure_type is None,
        failure_type=failure_type,
        feedback=feedback or None,
        claims=claims,
        **usage,
    )
