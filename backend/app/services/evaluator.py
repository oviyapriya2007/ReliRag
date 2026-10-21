import json
import logging
import math
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
CHECK_CONTRADICTION = "contradiction"
assert {CHECK_EVIDENCE, CHECK_SUPPORT, CHECK_CITATION, CHECK_UNCITED,
        CHECK_LIMITATION, CHECK_CONTRADICTION} == set(CLAIM_CHECK_NAMES)

# Fewest characters two chunks must share at their boundary to be joined without a recorded
# chunk index (the chunker's windows overlap); see `join_adjacent`.
MIN_CHUNK_OVERLAP = 10

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
Judge meaning, not wording. A paraphrase that says the same thing as a passage is supported. A claim \
that changes the subject or another named entity, reverses a relationship, changes a quantity, or \
changes a qualifier (for example adds "always", "all", or "only", or drops "may" or "some") is not \
supported as written, even when most of its words match a passage.
For "supported" and "partially_supported" claims, set evidence_chunk_id to the chunk_id of the passage \
that best supports the claim (the chunk_id value, not the passage number), and set evidence_quote to a \
short excerpt copied character for character from that passage: one contiguous span, no paraphrasing, \
no ellipses. For "unsupported" claims, set both to null. If the claim is only supported by several \
passages together, list the other passages in "additional_evidence", each as {"evidence_chunk_id": ..., \
"evidence_quote": ...} with the same quoting rules.
If another passage states something incompatible with the claim about the same subject under the same \
conditions (time, place, version, scope), list it in "conflicting_evidence" in the same form, even if a \
passage also supports the claim. Passages about a different subject, period, scope, or condition do not \
conflict with the claim; do not list them. Leave both lists empty when there is nothing to list.

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
grounded and complete. For each unanswered part, say whether the passages contain the information \
(the answer left it out) or not (the passages lack it). Do not describe what the missing information \
might be beyond what the passages state.

Return ONLY one JSON object, with no Markdown and no text before or after it, in exactly this shape:
{"claims": [{"claim_text": "...", "verdict": "supported", "evidence_chunk_id": 123, \
"evidence_quote": "...", "additional_evidence": [], "conflicting_evidence": []}], \
"limitations": ["..."], "answer_relevance": 0.0, \
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


class EvidenceItem(BaseModel):
    model_config = ConfigDict(strict=True)

    evidence_chunk_id: int
    evidence_quote: str


class ClaimJudgement(BaseModel):
    model_config = ConfigDict(strict=True)

    claim_text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    verdict: Literal["supported", "partially_supported", "unsupported"]
    evidence_chunk_id: int | None
    evidence_quote: str | None
    additional_evidence: list[EvidenceItem] = []
    conflicting_evidence: list[EvidenceItem] = []


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
    `evidence_error` why a check changed it, and `check` which check that was.

    `additional_evidence` and `conflicting_evidence` are verified (chunk_id, quote) pairs from
    other passages that support or contradict the claim; they are used for scoring and
    correction but only the main evidence, and a downgrade's reason, are stored.

    `claude_evidence_chunk_id` and `claude_evidence_quote` are the main evidence exactly as
    Claude gave it (None for a claim added by a check), kept for debugging even when a check
    rejected it. They are never support: only `evidence_chunk_id`/`evidence_quote` are, and
    those are None for an unsupported claim whose evidence failed a check.
    """

    claim_text: str
    verdict: str
    evidence_chunk_id: int | None
    evidence_quote: str | None
    claude_verdict: str | None
    evidence_error: str | None
    check: str | None = None
    additional_evidence: tuple[tuple[int, str], ...] = ()
    conflicting_evidence: tuple[tuple[int, str], ...] = ()
    claude_evidence_chunk_id: int | None = None
    claude_evidence_quote: str | None = None

    @property
    def evidence(self) -> list[tuple[int, str]]:
        """Every verified supporting (chunk_id, quote), main evidence first."""
        main = ([(self.evidence_chunk_id, self.evidence_quote)]
                if self.evidence_chunk_id is not None and self.evidence_quote else [])
        return [*main, *self.additional_evidence]

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


Joins = Mapping[int, Sequence[tuple[int, str]]]


def _follows(first: RetrievedChunk, second: RetrievedChunk) -> bool:
    """True if `second` is the chunk right after `first` in the same document: by recorded
    chunk index, or, when either index is unknown, by consecutive chunk ID on the same page."""
    if first.document_id != second.document_id:
        return False
    if first.chunk_index is not None and second.chunk_index is not None:
        return second.chunk_index == first.chunk_index + 1
    return second.chunk_id == first.chunk_id + 1 and first.page == second.page


def join_adjacent(first: RetrievedChunk, second: RetrievedChunk) -> str | None:
    """The source text `first` and `second` cover together, or None if they are not
    source-contiguous (see `_follows`).

    The chunker's windows overlap, so the longest end of `first` that starts `second` is
    counted once. Without that overlap they are joined only when both chunk indices are
    known: directly on one page, with a space across a page break. Chunks of different
    documents, or with a gap between them, are never joined.
    """
    if not _follows(first, second):
        return None
    head, tail = first.text, second.text
    for size in range(min(len(head), len(tail)), MIN_CHUNK_OVERLAP - 1, -1):
        if head.endswith(tail[:size]):
            return head + tail[size:]
    if first.chunk_index is None or second.chunk_index is None:
        return None
    return head + tail if first.page == second.page else f"{head} {tail}"


def contiguous_joins(chunks: Sequence[RetrievedChunk]) -> dict[int, list[tuple[int, str]]]:
    """For each retrieved chunk ID, (adjacent retrieved chunk ID, their joined text) pairs."""
    joins: dict[int, list[tuple[int, str]]] = {}
    for first in chunks:
        for second in chunks:
            if first.chunk_id == second.chunk_id:
                continue
            text = join_adjacent(first, second)
            if text is not None:
                joins.setdefault(first.chunk_id, []).append((second.chunk_id, text))
                joins.setdefault(second.chunk_id, []).append((first.chunk_id, text))
    return joins


def locate_quote(chunk_id: int, quote: str, chunks_by_id: Mapping[int, RetrievedChunk],
                 joins: Joins | None = None) -> tuple[int, str] | None:
    """(chunk ID, text) where `quote` occurs, starting from chunk `chunk_id`, or None.

    The quote is looked for in the chunk, then across its boundary with an adjacent retrieved
    chunk of the same document (`contiguous_joins`). A quote found entirely in that neighbor
    is located there; one spanning the boundary keeps `chunk_id`, with the joined text.
    """
    chunk = chunks_by_id.get(chunk_id)
    if chunk is None:
        return None
    if answer_checks.quote_occurs(quote, chunk.text):
        return chunk_id, chunk.text
    for neighbor_id, text in (joins or {}).get(chunk_id, ()):
        if answer_checks.quote_occurs(quote, text):
            neighbor = chunks_by_id[neighbor_id]
            if answer_checks.quote_occurs(quote, neighbor.text):
                return neighbor_id, neighbor.text
            return chunk_id, text
    return None


def verify_evidence(claim: ClaimJudgement, chunks_by_id: Mapping[int, RetrievedChunk],
                    joins: Joins | None = None) -> str | None:
    """Return why the claim's evidence is invalid, or None if it checks out.

    Evidence must reference a supplied chunk and quote text that occurs in that chunk, or
    across its boundary with an adjacent retrieved chunk of the same document
    (`locate_quote`; see `answer_checks.quote_occurs`: case, whitespace, punctuation,
    typographic quote/dash differences, and line-break hyphenation are ignored, but every
    word must match in order). Unsupported claims may omit evidence entirely.
    """
    chunk_id, quote = claim.evidence_chunk_id, claim.evidence_quote
    if chunk_id is None and not quote:
        return None if claim.verdict == UNSUPPORTED else "no evidence given"
    if chunk_id is None:
        return "evidence_quote given without evidence_chunk_id"
    chunk = chunks_by_id.get(chunk_id)
    if chunk is None:
        return f"evidence_chunk_id {chunk_id} is not one of the retrieved chunks"
    if not _normalize(quote or ""):
        return f"no evidence_quote given for chunk {chunk_id}"
    if locate_quote(chunk_id, quote, chunks_by_id, joins) is None:
        return f"evidence_quote does not appear in chunk {chunk_id}"
    return None


def _lower_verdict(verdict: str, cap: str | None) -> str:
    """`verdict` lowered to at most `cap`; never raised."""
    if cap == CAP_NONE:
        return UNSUPPORTED
    if cap == CAP_PARTIAL and verdict == SUPPORTED:
        return PARTIALLY_SUPPORTED
    return verdict


def _verified(items: Sequence[EvidenceItem], chunks_by_id: Mapping[int, RetrievedChunk],
              joins: Joins | None = None) -> list[tuple[int, str, str]]:
    """(chunk_id, quote, text) for each item whose quote `locate_quote` finds, without repeats;
    anything else is dropped, never trusted."""
    found: dict[tuple[int, str], tuple[int, str, str]] = {}
    for item in items:
        located = locate_quote(item.evidence_chunk_id, item.evidence_quote, chunks_by_id, joins)
        if located is not None:
            chunk_id, text = located
            key = (chunk_id, _normalize(item.evidence_quote))
            found.setdefault(key, (chunk_id, item.evidence_quote, text))
    return list(found.values())


def describe_evidence(chunk: RetrievedChunk, quote: str) -> str:
    page = f", page {chunk.page}" if chunk.page is not None else ""
    return f'chunk {chunk.chunk_id} ({chunk.document}{page}): "{quote}"'


def judge_claim(claim: ClaimJudgement, chunks_by_id: Mapping[int, RetrievedChunk], *,
                premises: set[str] = frozenset(),
                derived: set[str] = frozenset(),
                premise_names: set[str] = frozenset(),
                known: frozenset[str] = frozenset(),
                joins: Joins | None = None,
                cited_texts: Sequence[str] = ()) -> ClaimVerdict:
    """Apply evidence verification: a claim with invalid evidence is always unsupported.

    Claude judges whether the evidence means what the claim says; these checks can only lower
    that verdict. The main evidence must be valid (`verify_evidence`); a quote that continues
    into an adjacent chunk of the same document is checked against their joined text, and one
    found wholly in that neighbor is recorded against it. Additional evidence from other
    passages counts only if its quote is verified too, and all verified evidence together
    must pass `answer_checks.support_cap` (with the question's numbers and names, `premises`
    and `premise_names`, and the `known` names). A verified passage reported as contradicting
    a supported claim, and relevant to it (`answer_checks.conflict_problem`), leaves the claim
    at most partially supported, with the conflicting chunk, document, page, and quote recorded.

    Claude's verdict and evidence are always kept (`claude_verdict`, `claude_evidence_*`);
    the verified evidence is cleared whenever the final verdict is unsupported.
    """
    given = {"claude_evidence_chunk_id": claim.evidence_chunk_id,
             "claude_evidence_quote": claim.evidence_quote}
    error = verify_evidence(claim, chunks_by_id, joins)
    if error is not None:
        return ClaimVerdict(claim.claim_text, UNSUPPORTED, None, None, claim.verdict, error,
                            CHECK_EVIDENCE, **given)
    if claim.verdict == UNSUPPORTED:
        return ClaimVerdict(claim.claim_text, claim.verdict, None, None, claim.verdict, None,
                            **given)
    main_id, main_text = locate_quote(claim.evidence_chunk_id, claim.evidence_quote,
                                      chunks_by_id, joins)
    main = (main_id, claim.evidence_quote, main_text)
    additional = [item for item in _verified(claim.additional_evidence, chunks_by_id, joins)
                  if (item[0], _normalize(item[1])) != (main_id, _normalize(main[1]))]
    evidence = [main, *additional]
    cap, reason = answer_checks.support_cap(
        claim.claim_text, [(quote, text) for _, quote, text in evidence],
        premises=premises, derived=derived, premise_names=premise_names, known=known,
        cited_texts=cited_texts)
    verdict = _lower_verdict(claim.verdict, cap)
    if verdict == UNSUPPORTED:
        return ClaimVerdict(claim.claim_text, UNSUPPORTED, None, None, claim.verdict, reason,
                            CHECK_SUPPORT, **given)

    quotes = [quote for _, quote, _ in evidence]
    conflicts = [
        (chunk_id, quote) for chunk_id, quote, text
        in _verified(claim.conflicting_evidence, chunks_by_id, joins)
        if answer_checks.conflict_problem(claim.claim_text, quote, text, quotes) is None
    ]
    if conflicts:
        verdict = _lower_verdict(verdict, CAP_PARTIAL)
        note = "contradicted by " + "; ".join(describe_evidence(chunks_by_id[chunk_id], quote)
                                              for chunk_id, quote in conflicts)
        reason = f"{reason}; {note}" if reason else note
    changed = verdict != claim.verdict
    return ClaimVerdict(claim.claim_text, verdict, main_id, claim.evidence_quote,
                        claim.verdict, reason if changed else None,
                        CHECK_SUPPORT if changed else None,
                        tuple((chunk_id, quote) for chunk_id, quote, _ in additional),
                        tuple(conflicts), **given)


def judge_limitations(statements: Sequence[str],
                      claims: Sequence[ClaimVerdict] = ()) -> tuple[list[str], list[ClaimVerdict]]:
    """(limitation statements, unsupported claims for statements that assert facts).

    A statement counts as a limitation if it says what is missing or uncertain and asserts
    nothing else, or if every other clause of it only restates one of the answer's `claims`,
    which are scored on their own (`answer_checks.unscored_parts`): "The passages mention
    that X contains Y, but the text is cut off before the list" when "X contains Y" is a
    claim. Anything else labeled a limitation is scored as an unsupported claim, so a factual
    claim cannot avoid the faithfulness check by being called a limitation.
    """
    claim_texts = [claim.claim_text for claim in claims]
    limitations, mislabeled = [], []
    for statement in statements:
        if (answer_checks.is_pure_limitation(statement)
                or (answer_checks.is_limitation_statement(statement)
                    and not answer_checks.unscored_parts(statement, claim_texts))):
            limitations.append(statement)
        else:
            mislabeled.append(ClaimVerdict(
                statement, UNSUPPORTED, None, None, None,
                "labeled a limitation but asserts something", CHECK_LIMITATION))
    return limitations, mislabeled


def judge_contradictions(
    answer: str, limitations: Sequence[str], claims: Sequence[ClaimVerdict],
    listed: Sequence[str] = (),
) -> tuple[list[str], list[ClaimVerdict]]:
    """(limitations that stand, unsupported claims for limitations the answer contradicts).

    A limitation contradicts the answer when one of its own factual claims states what the
    limitation says the sources leave out (`answer_checks.contradicted_claim`). Besides the
    evaluator's `limitations`, every limitation sentence of the answer that the evaluator did
    not list (`listed`, its limitation statements before `judge_limitations`) is checked, so
    a contradiction cannot pass unnoticed because it was not reported.
    """
    def key(text: str) -> str:
        return _normalize(answer_checks.strip_citations(text)).rstrip(" .!?;:")

    claim_texts = [claim.claim_text for claim in claims]
    seen = {key(text) for text in [*limitations, *listed]}
    unlisted = [answer_checks.strip_citations(sentence.text).strip()
                for sentence in answer_checks.split_sentences(answer)]
    unlisted = [text for text in unlisted
                if key(text) not in seen and answer_checks.is_pure_limitation(text)]
    kept, contradictions = [], []
    for statement in [*limitations, *unlisted]:
        contradicted = answer_checks.contradicted_claim(statement, claim_texts)
        if contradicted is None:
            if statement in limitations:
                kept.append(statement)
            continue
        contradictions.append(ClaimVerdict(
            statement, UNSUPPORTED, None, None, None,
            f'says the sources do not cover what the answer itself claims: "{contradicted}"',
            CHECK_CONTRADICTION))
    return kept, contradictions


def check_citations(
    answer: str, claims: Sequence[ClaimVerdict], chunks: Sequence[RetrievedChunk],
    joins: Joins | None = None,
) -> tuple[list[ClaimVerdict], list[int]]:
    """Apply citation checks to `claims`; also returns the non-existent passage numbers cited.

    Each claim is matched to the answer sentence restating it. A supported claim whose sentence
    cites no passage, cites a passage number that does not exist, or cites only passages that
    do not contain its evidence is lowered to partially supported. A factual sentence that no
    claim covers and that has no valid citation is added as an unsupported claim. Limitation
    statements need no citation. A quote spanning two adjacent cited chunks (`joins`) counts as
    contained in them.
    """
    sentences = answer_checks.split_sentences(answer)
    match_texts = answer_checks.with_lead_ins(sentences)
    contiguous = {chunk_id: [text for _, text in pairs] for chunk_id, pairs in (joins or {}).items()}
    covered: set[int] = set()
    checked = []
    for claim in claims:
        index = answer_checks.match_sentence(claim.claim_text, match_texts)
        if index is not None:
            covered.add(index)
        if index is None or claim.verdict == UNSUPPORTED or claim.evidence_chunk_id is None:
            checked.append(claim)
            continue
        problem = answer_checks.citation_problem(
            claim.claim_text, [quote for _, quote in claim.evidence], sentences[index], chunks,
            contiguous)
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


_VERDICT_RANK = {UNSUPPORTED: 0, PARTIALLY_SUPPORTED: 1, SUPPORTED: 2}


def merge_duplicate_claims(claims: Sequence[ClaimVerdict]) -> tuple[list[ClaimVerdict], int]:
    """(`claims` with each statement counted once, number of duplicates removed).

    Claims are duplicates when their text is the same apart from case, whitespace, and trailing
    punctuation. The first occurrence keeps its place and takes the lowest verdict among them,
    so a repeated statement cannot weigh twice or hide a weaker judgement.
    """
    merged: dict[str, ClaimVerdict] = {}
    for claim in claims:
        key = _normalize(claim.claim_text).rstrip(" .!?;:")
        kept = merged.get(key)
        if kept is None or _VERDICT_RANK[claim.verdict] < _VERDICT_RANK[kept.verdict]:
            merged[key] = claim
    return list(merged.values()), len(claims) - len(merged)


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

    A score meets `threshold` when it is finite and at least `threshold` (0-1 scale), so a
    score exactly at the threshold passes and a NaN or infinite score always fails. Scores are
    checked in the order faithfulness, answer relevance, context relevance.
    `threshold=None` uses EVALUATOR_PASS_THRESHOLD.
    """
    if threshold is None:
        threshold = settings.evaluator_pass_threshold
    for score, failure_type in (
        (faithfulness, UNSUPPORTED_CLAIM),
        (answer_relevance, MISSING_INFO),
        (context_relevance, IRRELEVANT_RETRIEVAL),
    ):
        if not math.isfinite(score) or score < threshold:
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
    joins = contiguous_joins(chunks)
    premises = answer_checks.numbers(question)
    known = answer_checks.name_vocabulary(question, answer, *(chunk.text for chunk in chunks))
    premise_names = answer_checks.anchors(question, known)
    _, derived = answer_checks.grounded_calculations(
        answer, set().union(*(answer_checks.numbers(chunk.text) for chunk in chunks)), premises)
    claims = [judge_claim(claim, chunks_by_id, premises=premises, derived=derived,
                          premise_names=premise_names, known=known, joins=joins,
                          cited_texts=[chunk.text for chunk in answer_checks.cited_passages(
                              claim.claim_text, answer, chunks)])
              for claim in output.claims]
    limitations, mislabeled = judge_limitations(output.limitations, claims)
    limitations, contradictions = judge_contradictions(answer, limitations, claims,
                                                       output.limitations)
    claims, duplicates = merge_duplicate_claims(claims + mislabeled + contradictions)
    claims, nonexistent = check_citations(answer, claims, chunks, joins)
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
    if failure_type is None and any(c.check == CHECK_CONTRADICTION for c in claims):
        # Scores alone cannot pass an answer that contradicts itself.
        failure_type = UNSUPPORTED_CLAIM

    return EvaluationResult(
        faithfulness=faithfulness,
        answer_relevance=answer_relevance,
        context_relevance=output.context_relevance,
        passed=failure_type is None,
        failure_type=failure_type,
        feedback=_feedback(output.feedback, claims, limitations, nonexistent, duplicates,
                           scores=(faithfulness, answer_relevance, output.context_relevance),
                           threshold=threshold) or None,
        claims=claims,
        **usage,
    )


def _feedback(feedback: str, claims: Sequence[ClaimVerdict], limitations: Sequence[str],
              nonexistent: Sequence[int], duplicates: int = 0, *,
              scores: tuple[float, float, float] | None = None,
              threshold: float | None = None) -> str:
    """Claude's feedback followed by a note for each deterministic check that changed a score,
    and, when the checks lowered a score below `threshold` or found a contradiction, the
    resulting verdict, so the feedback never reads as a pass for an answer that failed.

    When a check changed any claim, Claude's feedback describes the answer before
    verification, so it no longer leads: the feedback opens with the verified claim counts
    and faithfulness, and Claude's text follows last, labeled as the pre-verification
    assessment."""
    def count(check: str) -> int:
        return sum(c.check == check for c in claims)

    checked = any(c.check is not None for c in claims)
    notes = []
    if checked:
        verdicts = [c.verdict for c in claims]
        summary = (f"Verified result: {verdicts.count(SUPPORTED)} of {len(claims)} claim(s) "
                   f"supported, {verdicts.count(PARTIALLY_SUPPORTED)} partially supported, "
                   f"{verdicts.count(UNSUPPORTED)} unsupported")
        if scores is not None and math.isfinite(scores[0]):
            summary += f" (faithfulness {scores[0]:.2f})"
        notes.append(f"{summary}.")
    else:
        notes.append(feedback.strip())
    invalid = sum(c.check == CHECK_EVIDENCE and c.claude_verdict != UNSUPPORTED for c in claims)
    if invalid:
        notes.append(f"{invalid} claim(s) cited evidence that could not be verified against the "
                     f"retrieved chunks and were marked unsupported.")
    if count(CHECK_SUPPORT):
        notes.append(f"{count(CHECK_SUPPORT)} claim(s) quoted evidence that does not fully "
                     f"support them and were downgraded.")
    conflicted = sum(bool(c.conflicting_evidence) for c in claims)
    if conflicted:
        notes.append(f"{conflicted} claim(s) are contradicted by another retrieved passage.")
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
    if count(CHECK_CONTRADICTION):
        notes.append(f"{count(CHECK_CONTRADICTION)} limitation statement(s) say the sources do "
                     f"not cover something the answer itself claims; the answer contradicts "
                     f"itself and cannot pass.")
    if limitations:
        notes.append(f"{len(limitations)} limitation statement(s) were not scored as factual "
                     f"claims.")
    if duplicates:
        notes.append(f"{duplicates} repeated claim(s) were counted once.")
    if scores is not None and checked:
        if threshold is None:
            threshold = settings.evaluator_pass_threshold
        below = [f"{name} {score:.2f}" for name, score in
                 zip(("faithfulness", "answer relevance", "context relevance"), scores)
                 if not math.isfinite(score) or score < threshold]
        if below:
            notes.append(f"After verification, {', '.join(below)} "
                         f"{'is' if len(below) == 1 else 'are'} below the {threshold:.2f} "
                         f"threshold, so the answer did not pass.")
    if checked and feedback.strip():
        notes.append(f"Evaluator's assessment before verification (superseded by the verified "
                     f"result above): {feedback.strip()}")
    return " ".join(note for note in notes if note)
