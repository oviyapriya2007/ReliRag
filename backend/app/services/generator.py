import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

from app.config import settings
from app.services.llm import LLMError, LLMResult, call_claude
from app.services.retrieval import RetrievedChunk
from app.services.similarity_gate import INSUFFICIENT_EVIDENCE

ANSWERED = "ANSWERED"
# Anthropic stop_reasons: cut off by a safety classifier, by max_tokens, or by the context window.
REFUSAL_STOP_REASON = "refusal"
MAX_TOKENS_STOP_REASON = "max_tokens"
CONTEXT_WINDOW_STOP_REASON = "model_context_window_exceeded"
# Ceiling for the larger budget a truncated answer is retried with; each retry doubles it.
MAX_GENERATION_TOKENS = 4096

_CITATION_RE = re.compile(r"\[(\d+)\]")
# Claude sometimes wraps the refusal token in Markdown or follows it with an explanation.
_REFUSAL_RE = re.compile(rf"^[\s*_`]*{INSUFFICIENT_EVIDENCE}\b")
# The token inside an answer, with any Markdown or brackets around it and the spaces before it.
_INLINE_REFUSAL_RE = re.compile(
    rf"[ \t]*(?:\[[*_`]*{INSUFFICIENT_EVIDENCE}[*_`]*\]|\([*_`]*{INSUFFICIENT_EVIDENCE}[*_`]*\)"
    rf"|[*_`]*(?<![A-Za-z0-9]){INSUFFICIENT_EVIDENCE}(?![A-Za-z0-9])[*_`]*)"
)
# Text left after stripping that still carries an answer.
_WORD_RE = re.compile(r"\w")

SYSTEM_PROMPT = f"""You answer questions using ONLY the numbered context passages provided.

Rules:
- Use only facts stated in the context. Do not use prior knowledge or make assumptions.
- Address every part of the question that the context supports.
- Cite every claim with the number of the passage that supports it, in square brackets, e.g. [1]. \
Cite multiple passages separately, e.g. [1][3]. Never cite a number that is not in the context.
- If the context does not contain enough information to answer the question, reply with exactly \
{INSUFFICIENT_EVIDENCE} and nothing else.
- If you answer but the context does not cover some part of the question, say so plainly in a \
separate sentence without a citation, naming the part that is not covered. Never write \
{INSUFFICIENT_EVIDENCE} inside an answer."""

MAX_STRICT_CLAIMS = 20
MAX_STRICT_CLAIM_CHARS = 500
# Evaluator feedback quoted in correction instructions is cut to this length.
MAX_CORRECTION_FEEDBACK_CHARS = 1500

CORRECTION_INSTRUCTIONS = f"""Correction: an evaluator reviewed a previous answer to this question \
and reported these problems.
Problems: {{problems}}
Evaluator feedback: {{feedback}}
- Cover every part of the question that the context passages support, including any part the \
previous answer left out, and cite every factual sentence.
- The problems and feedback only say what to look for; they are not evidence. Do not add anything \
the passages do not state, even if the feedback mentions it.
- If the passages still do not cover a part of the question, say so plainly in a separate \
sentence without a citation instead of guessing. Reply with exactly {INSUFFICIENT_EVIDENCE} only \
if the passages answer no part of the question."""

STRICT_INSTRUCTIONS = f"""Strict mode: a previous answer to this question was rejected because \
some of its claims are not supported by the context passages.{{claims}}
- Do not repeat a rejected claim unless a passage states it explicitly.
- State only what the passages say explicitly, and cite every factual sentence. Leave out \
anything you cannot cite, even if it seems likely.
- If what remains does not answer the question, reply with exactly {INSUFFICIENT_EVIDENCE} and \
nothing else."""


@dataclass(frozen=True)
class GenerationResult:
    status: str
    answer: str | None
    citations: list[int]
    cited_chunks: list[RetrievedChunk]
    llm: LLMResult | None


def build_context(chunks: Sequence[RetrievedChunk]) -> str:
    blocks = []
    for number, chunk in enumerate(chunks, start=1):
        page = f", page {chunk.page}" if chunk.page is not None else ""
        blocks.append(f"[{number}] (source: {chunk.document}{page})\n{chunk.text}")
    return "\n\n".join(blocks)


def build_prompt(question: str, chunks: Sequence[RetrievedChunk]) -> str:
    return f"Context:\n\n{build_context(chunks)}\n\nQuestion: {question}"


def build_strict_instructions(rejected_claims: Sequence[str]) -> str:
    """Strict-mode rules for regenerating an answer, listing the claims to avoid.

    Blank claims are dropped, whitespace is collapsed, and the list is capped at
    MAX_STRICT_CLAIMS claims of at most MAX_STRICT_CLAIM_CHARS characters each.
    """
    claims = [" ".join(claim.split())[:MAX_STRICT_CLAIM_CHARS] for claim in rejected_claims]
    claims = [claim for claim in claims if claim][:MAX_STRICT_CLAIMS]
    listing = "".join(f"\n- {claim}" for claim in claims)
    return STRICT_INSTRUCTIONS.format(claims=f"\nRejected claims:{listing}\n" if claims else "")


def build_correction_instructions(problems: str, feedback: str | None) -> str:
    """Rules for regenerating an answer that an evaluation found incomplete or weakly
    supported: what was wrong, and that only the passages count as evidence.

    `feedback` (the evaluator's) has its whitespace collapsed and is cut to
    MAX_CORRECTION_FEEDBACK_CHARS characters.
    """
    feedback = " ".join((feedback or "").split())[:MAX_CORRECTION_FEEDBACK_CHARS]
    return CORRECTION_INSTRUCTIONS.format(problems=" ".join(problems.split()),
                                          feedback=feedback or "None given.")


def is_refusal(text: str) -> bool:
    """True if a Claude reply begins with the INSUFFICIENT_EVIDENCE refusal token."""
    return _REFUSAL_RE.match(text) is not None


def strip_inline_refusals(text: str) -> str:
    """Remove stray INSUFFICIENT_EVIDENCE tokens from inside an answer, keeping the rest.

    Only call this for replies that are not refusals (see `is_refusal`).
    """
    return _INLINE_REFUSAL_RE.sub("", text).strip()


def parse_citations(text: str, num_chunks: int) -> list[int]:
    """Return valid 1-based citation numbers in order of first appearance, without duplicates."""
    seen: list[int] = []
    for match in _CITATION_RE.finditer(text):
        number = int(match.group(1))
        if 1 <= number <= num_chunks and number not in seen:
            seen.append(number)
    return seen


def _complete_reply(prompt: str, system: str, max_tokens: int | None) -> LLMResult:
    """Call Claude until the reply is not truncated; usage is summed over all calls.

    The first request is the normal one. A reply cut off at max_tokens (unless it is a
    refusal) is retried with double the budget, up to MAX_GENERATION_TOKENS.
    """
    budget = max_tokens or settings.claude_max_tokens
    request_tokens = max_tokens
    calls: list[LLMResult] = []
    while True:
        llm = call_claude(prompt, system=system, max_tokens=request_tokens)
        calls.append(llm)
        if llm.stop_reason == CONTEXT_WINDOW_STOP_REASON:
            raise LLMError("Claude's context window was exceeded before the answer was complete")
        if llm.stop_reason != MAX_TOKENS_STOP_REASON or is_refusal(llm.text.strip()):
            break
        larger = min(budget * 2, MAX_GENERATION_TOKENS)
        if larger <= budget:
            raise LLMError(f"Claude's answer was cut off at the {budget}-token output limit")
        budget = request_tokens = larger
    if len(calls) == 1:
        return llm
    return replace(llm, input_tokens=sum(c.input_tokens for c in calls),
                   output_tokens=sum(c.output_tokens for c in calls),
                   latency_ms=sum(c.latency_ms for c in calls),
                   attempts=sum(c.attempts for c in calls))


def generate_answer(
    question: str,
    chunks: Sequence[RetrievedChunk],
    *,
    max_tokens: int | None = None,
    strict_instructions: str | None = None,
) -> GenerationResult:
    """Answer `question` from `chunks` (numbered [1]..[n] in order) via Claude.

    `strict_instructions` (see `build_strict_instructions`) are appended to the system
    prompt; without them the request is the normal one.
    With no chunks, Claude is not called and the result is INSUFFICIENT_EVIDENCE.
    A reply beginning with the refusal token is INSUFFICIENT_EVIDENCE, whatever follows it;
    stray tokens inside an answer are removed. A reply cut off at its token budget is retried
    with double the budget, up to MAX_GENERATION_TOKENS, so a truncated answer is never
    returned as ANSWERED. Raises `LLMError` if the Claude call fails, the answer stays
    truncated or exceeds the context window, or there is no usable answer (an empty reply, or
    a safety-classifier refusal stop with no answer text).
    """
    question = question.strip()
    if not question:
        raise ValueError("question must not be empty")
    if not chunks:
        return GenerationResult(INSUFFICIENT_EVIDENCE, None, [], [], None)

    system = SYSTEM_PROMPT
    if strict_instructions and strict_instructions.strip():
        system = f"{SYSTEM_PROMPT}\n\n{strict_instructions.strip()}"
    llm = _complete_reply(build_prompt(question, chunks), system, max_tokens)
    text = llm.text.strip()

    if is_refusal(text):
        return GenerationResult(INSUFFICIENT_EVIDENCE, None, [], [], llm)

    answer = strip_inline_refusals(text)
    if _WORD_RE.search(answer) is None:
        # Nothing but refusal tokens (e.g. "[INSUFFICIENT_EVIDENCE]") is still a refusal.
        if INSUFFICIENT_EVIDENCE in text and llm.stop_reason != REFUSAL_STOP_REASON:
            return GenerationResult(INSUFFICIENT_EVIDENCE, None, [], [], llm)
        raise LLMError(f"Claude returned no usable answer (stop_reason={llm.stop_reason})")
    text = answer

    citations = parse_citations(text, len(chunks))
    return GenerationResult(
        status=ANSWERED,
        answer=text,
        citations=citations,
        cited_chunks=[chunks[n - 1] for n in citations],
        llm=llm,
    )
