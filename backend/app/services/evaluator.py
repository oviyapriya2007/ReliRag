import json
import logging
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from app.config import settings
from app.models import CLAIM_CHECK_NAMES
from app.services import answer_checks
from app.services.answer_checks import CAP_NONE, CAP_PARTIAL, normalize_text
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

_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)

# Which deterministic check changed a claim (ClaimVerdict.check, stored as Claim.check_name).
CHECK_EVIDENCE = "evidence"
CHECK_SUPPORT = "support"
CHECK_CITATION = "citation"
CHECK_UNCITED = "uncited"
CHECK_LIMITATION = "limitation"
assert {CHECK_EVIDENCE, CHECK_SUPPORT, CHECK_CITATION, CHECK_UNCITED,
        CHECK_LIMITATION} == set(CLAIM_CHECK_NAMES)

SYSTEM_PROMPT = """You are a strict evaluator for a retrieval-augmented question answering system. \
You receive a question, the retrieved passages, and an answer generated from those passages. \
Passages are numbered in the order the answer's citation markers such as [1] refer to, and each has \
a chunk_id. Judge the answer only against the passages; do not use prior knowledge.

Task 1 - claims. Split the answer into atomic claims: short, self-contained factual statements that \
can each be checked on their own. Cover every factual statement in the answer. Leave citation markers \
out of claim_text. A sentence that only says the passages do not provide, mention, or specify \
something, or that the answer is uncertain about it, is a limitation statement, not a claim: copy it \
into "limitations" instead. If a sentence states a fact and also a limitation, put the fact in \
"claims" and only the limitation part in "limitations". Never put a factual statement in \
"limitations". Give each claim a verdict:
- "supported": everything the claim states is explicitly stated in, or directly entailed by, one passage.
- "partially_supported": a passage supports part of the claim, but some detail is missing from the \
passage or the claim goes beyond what the passage states.
- "unsupported": no passage states the claim, or a passage contradicts it.
For "supported" and "partially_supported" claims, set evidence_chunk_id to the chunk_id of the passage \
that best supports the claim (the chunk_id value, not the passage number), and set evidence_quote to a \
short excerpt copied character for character from that passage: one contiguous span, no paraphrasing, \
no ellipses. For "unsupported" claims, set both to null.

Task 2 - answer_relevance, from 0 to 1: how directly and completely the answer addresses the question. \
Judge relevance and completeness only, not whether the answer is supported. A part of the question \
that the answer only says it cannot answer is unanswered.
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
"evidence_quote": "..."}], "limitations": ["..."], "answer_relevance": 0.0, \
"context_relevance": 0.0, "feedback": "..."}
"limitations" may be an empty list."""

RETRY_INSTRUCTION = """Your previous reply was rejected: {error}
Return ONLY a single valid JSON object in exactly the required shape. Do not use Markdown or code \
fences, and do not write anything before or after the JSON."""

TRUNCATION_INSTRUCTION = """Your previous reply was cut off at the output limit before the JSON \
was complete. Return the complete JSON object in exactly the required shape, keeping claim_text, \
evidence_quote, and feedback short."""

# Anthropic stop_reason when a reply hits its max_tokens budget.
MAX_TOKENS_STOP_REASON = "max_tokens"
# Ceiling for the larger budget a truncated evaluator reply is retried with; well within the
# output limits of current Claude models. Each truncation retry doubles the budget up to it.
MAX_EVALUATOR_TOKENS = 8192

Score = Annotated[float, Field(ge=0.0, le=1.0)]


class ClaimJudgement(BaseModel):
    model_config = ConfigDict(strict=True)

    claim_text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    verdict: Literal["supported", "partially_supported", "unsupported"]
    evidence_chunk_id: int | None
    evidence_quote: str | None


class EvaluatorOutput(BaseModel):
    model_config = ConfigDict(strict=True)

    claims: list[ClaimJudgement]
    limitations: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]] = []
    answer_relevance: Score
    context_relevance: Score
    feedback: str

    @model_validator(mode="after")
    def _has_statements(self) -> "EvaluatorOutput":
        if not self.claims and not self.limitations:
            raise ValueError("claims and limitations must not both be empty")
        return self


@dataclass(frozen=True)
class ClaimVerdict:
    """A scored claim. `claude_verdict` is Claude's verdict (None for a claim added by a check),
    `evidence_error` why a check changed it, and `check` which check that was."""

    claim_text: str
    verdict: str
    evidence_chunk_id: int | None
    evidence_quote: str | None
    claude_verdict: str | None
    evidence_error: str | None
    check: str | None = None

    def __post_init__(self) -> None:
        if self.check is not None and self.check not in CLAIM_CHECK_NAMES:
            raise ValueError(f"check must be one of {CLAIM_CHECK_NAMES} or None, not {self.check!r}")


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


def _single_json_object(text: str) -> str | None:
    """The only top-level JSON object embedded in `text`, or None if there is none or several."""
    decoder = json.JSONDecoder()
    found = []
    position = 0
    while (start := text.find("{", position)) != -1:
        try:
            value, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            position = start + 1
            continue
        if isinstance(value, dict):
            found.append(text[start:end])
        position = end
    return found[0] if len(found) == 1 else None


def parse_evaluator_output(text: str) -> EvaluatorOutput:
    """Validate Claude's reply as one JSON object, tolerating a surrounding code fence.

    If the reply is not valid as a whole but contains exactly one JSON object amid ordinary
    prose, that object is validated instead; several objects are ambiguous and rejected.
    Raises `ValidationError` for invalid JSON as well as for schema violations.
    """
    text = text.strip()
    match = _FENCE_RE.match(text)
    candidate = match.group(1) if match else text
    try:
        return EvaluatorOutput.model_validate_json(candidate)
    except ValidationError:
        embedded = _single_json_object(text)
        if embedded is None or embedded == candidate:
            raise
        return EvaluatorOutput.model_validate_json(embedded)


_normalize = normalize_text


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


def _lower_verdict(verdict: str, cap: str | None) -> str:
    """`verdict` lowered to at most `cap`; never raised."""
    if cap == CAP_NONE:
        return UNSUPPORTED
    if cap == CAP_PARTIAL and verdict == SUPPORTED:
        return PARTIALLY_SUPPORTED
    return verdict


def judge_claim(claim: ClaimJudgement, chunks_by_id: Mapping[int, RetrievedChunk]) -> ClaimVerdict:
    """Apply evidence verification: a claim with invalid evidence is always unsupported.

    Valid evidence must also support the claim (see `answer_checks.support_cap`): a quote that
    occurs in the chunk but does not state the claim lowers the verdict, never raises it.
    """
    error = verify_evidence(claim, chunks_by_id)
    if error is not None:
        return ClaimVerdict(claim.claim_text, UNSUPPORTED, None, None, claim.verdict, error,
                            CHECK_EVIDENCE)
    if claim.verdict == UNSUPPORTED:
        return ClaimVerdict(claim.claim_text, claim.verdict, claim.evidence_chunk_id,
                            claim.evidence_quote, claim.verdict, None)
    cap, reason = answer_checks.support_cap(claim.claim_text, claim.evidence_quote or "",
                                            chunks_by_id[claim.evidence_chunk_id].text)
    verdict = _lower_verdict(claim.verdict, cap)
    if verdict == UNSUPPORTED:
        return ClaimVerdict(claim.claim_text, UNSUPPORTED, None, None, claim.verdict, reason,
                            CHECK_SUPPORT)
    return ClaimVerdict(claim.claim_text, verdict, claim.evidence_chunk_id, claim.evidence_quote,
                        claim.verdict, reason if verdict != claim.verdict else None,
                        CHECK_SUPPORT if verdict != claim.verdict else None)


def judge_limitations(statements: Sequence[str]) -> tuple[list[str], list[ClaimVerdict]]:
    """(limitation statements, unsupported claims for statements that assert facts).

    A statement counts as a limitation only if it says what is missing or uncertain and
    asserts nothing else; anything else labeled a limitation is scored as an unsupported claim,
    so a factual claim cannot avoid the faithfulness check by being called a limitation.
    """
    limitations, mislabeled = [], []
    for statement in statements:
        if answer_checks.is_pure_limitation(statement):
            limitations.append(statement)
        else:
            mislabeled.append(ClaimVerdict(
                statement, UNSUPPORTED, None, None, None,
                "labeled a limitation but asserts something", CHECK_LIMITATION))
    return limitations, mislabeled


def check_citations(
    answer: str, claims: Sequence[ClaimVerdict], chunks: Sequence[RetrievedChunk]
) -> tuple[list[ClaimVerdict], list[int]]:
    """Apply citation checks to `claims`; also returns the non-existent passage numbers cited.

    Each claim is matched to the answer sentence restating it. A supported claim whose sentence
    cites no passage, cites a passage number that does not exist, or cites only passages that
    do not contain its evidence is lowered to partially supported. A factual sentence that no
    claim covers and that has no valid citation is added as an unsupported claim. Limitation
    statements need no citation.
    """
    sentences = answer_checks.split_sentences(answer)
    covered: set[int] = set()
    checked = []
    for claim in claims:
        index = answer_checks.match_sentence(claim.claim_text, sentences)
        if index is not None:
            covered.add(index)
        if index is None or claim.verdict == UNSUPPORTED or claim.evidence_chunk_id is None:
            checked.append(claim)
            continue
        problem = answer_checks.citation_problem(claim.claim_text, claim.evidence_quote,
                                                 sentences[index], chunks)
        if problem is not None and claim.verdict == SUPPORTED:
            claim = replace(claim, verdict=PARTIALLY_SUPPORTED, evidence_error=problem,
                            check=CHECK_CITATION)
        checked.append(claim)

    for index, sentence in enumerate(sentences):
        if index in covered or not answer_checks.is_factual_sentence(sentence):
            continue
        invalid = answer_checks.invalid_citations(sentence, len(chunks))
        if sentence.citations and not invalid:
            continue
        problem = (f"cites passage number(s) {invalid} that do not exist" if invalid
                   else "factual statement without a citation")
        checked.append(ClaimVerdict(answer_checks.strip_citations(sentence.text).strip(),
                                    UNSUPPORTED, None, None, None, problem, CHECK_UNCITED))

    nonexistent = sorted({number for sentence in sentences
                          for number in answer_checks.invalid_citations(sentence, len(chunks))})
    return checked, nonexistent


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
    threshold: float | None = None,
) -> str | None:
    """None if every score meets `threshold`, else the failure type of the first failing score.

    Scores are checked in the order faithfulness, answer relevance, context relevance.
    `threshold=None` uses EVALUATOR_PASS_THRESHOLD.
    """
    if threshold is None:
        threshold = settings.evaluator_pass_threshold
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
    threshold: float | None = None,
    max_tokens: int | None = None,
    model: str | None = None,
) -> EvaluationResult:
    """Verify `answer` claim by claim against `chunks` and score it via Claude.

    Faithfulness is computed here from the verified verdicts; Claude only scores answer and
    context relevance. An invalid reply is retried until EVALUATOR_MAX_PARSE_ATTEMPTS invalid
    replies in total. A reply cut off at its token budget is not parsed: it is retried with
    double the budget, up to MAX_EVALUATOR_TOKENS, and these retries do not count as parse
    attempts; a reply truncated at that ceiling is not retried again. If Claude fails, every
    reply is invalid, or the reply stays truncated, the result has `passed=False` and
    `failure_type=EVALUATOR_ERROR` instead of raising. Unset `threshold`, `max_tokens` and
    `model` use the EVALUATOR_* settings (the model falls back to CLAUDE_MODEL).
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
    budget = max_tokens or settings.evaluator_max_tokens
    calls: list[LLMResult] = []
    output: EvaluatorOutput | None = None
    error: str | None = None
    invalid_replies = 0
    started = time.perf_counter()
    try:
        while True:
            llm = call_claude(request, system=SYSTEM_PROMPT, max_tokens=budget,
                              model=model or settings.evaluator_model or None)
            calls.append(llm)
            if llm.stop_reason == MAX_TOKENS_STOP_REASON:
                error = f"reply was truncated at the {budget}-token output limit"
                larger = min(budget * 2, MAX_EVALUATOR_TOKENS)
                logger.warning("Evaluator reply truncated: call=%d max_tokens=%d retry=%s",
                               len(calls), budget, larger > budget)
                if larger <= budget:
                    break
                budget = larger
                request = f"{prompt}\n\n{TRUNCATION_INSTRUCTION}"
                continue
            try:
                output = parse_evaluator_output(llm.text)
                break
            except ValidationError as exc:
                invalid_replies += 1
                error = _summarize(exc)
                logger.warning("Evaluator reply invalid: attempt=%d stop_reason=%s error=%s",
                               invalid_replies, llm.stop_reason, error)
                if invalid_replies >= settings.evaluator_max_parse_attempts:
                    break
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
    limitations, mislabeled = judge_limitations(output.limitations)
    claims, nonexistent = check_citations(answer, claims + mislabeled, chunks)
    answer_relevance = output.answer_relevance
    if claims:
        faithfulness = compute_faithfulness([c.verdict for c in claims])
    else:
        # Only limitation statements: nothing is unfaithful, but no part of the question is
        # answered, so the answer cannot count as complete.
        faithfulness, answer_relevance = 1.0, 0.0
    failure_type = determine_failure_type(
        faithfulness, answer_relevance, output.context_relevance, threshold
    )

    return EvaluationResult(
        faithfulness=faithfulness,
        answer_relevance=answer_relevance,
        context_relevance=output.context_relevance,
        passed=failure_type is None,
        failure_type=failure_type,
        feedback=_feedback(output.feedback, claims, limitations, nonexistent) or None,
        claims=claims,
        **usage,
    )


def _feedback(feedback: str, claims: Sequence[ClaimVerdict], limitations: Sequence[str],
              nonexistent: Sequence[int]) -> str:
    """Claude's feedback followed by a note for each deterministic check that changed a score."""
    def count(check: str) -> int:
        return sum(c.check == check for c in claims)

    notes = [feedback.strip()]
    invalid = sum(c.check == CHECK_EVIDENCE and c.claude_verdict != UNSUPPORTED for c in claims)
    if invalid:
        notes.append(f"{invalid} claim(s) cited evidence that could not be verified against the "
                     f"retrieved chunks and were marked unsupported.")
    if count(CHECK_SUPPORT):
        notes.append(f"{count(CHECK_SUPPORT)} claim(s) quoted evidence that does not fully "
                     f"support them and were downgraded.")
    if count(CHECK_CITATION):
        notes.append(f"{count(CHECK_CITATION)} claim(s) were downgraded for a missing, invalid, "
                     f"or unrelated citation.")
    if count(CHECK_UNCITED):
        notes.append(f"{count(CHECK_UNCITED)} factual statement(s) without a valid citation "
                     f"were scored unsupported.")
    if nonexistent:
        notes.append(f"The answer cites passage number(s) {list(nonexistent)} that do not exist.")
    if count(CHECK_LIMITATION):
        notes.append(f"{count(CHECK_LIMITATION)} statement(s) labeled as limitations assert "
                     f"facts and were scored unsupported.")
    if limitations:
        notes.append(f"{len(limitations)} limitation statement(s) were not scored as factual "
                     f"claims.")
    return " ".join(note for note in notes if note)
