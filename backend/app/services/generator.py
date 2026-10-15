import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.llm import LLMResult, call_claude
from app.services.retrieval import RetrievedChunk
from app.services.similarity_gate import INSUFFICIENT_EVIDENCE

ANSWERED = "ANSWERED"

_CITATION_RE = re.compile(r"\[(\d+)\]")
# Claude sometimes wraps the refusal token in Markdown or follows it with an explanation.
_REFUSAL_RE = re.compile(rf"^[\s*_`]*{INSUFFICIENT_EVIDENCE}\b")

SYSTEM_PROMPT = f"""You answer questions using ONLY the numbered context passages provided.

Rules:
- Use only facts stated in the context. Do not use prior knowledge or make assumptions.
- Cite every claim with the number of the passage that supports it, in square brackets, e.g. [1]. \
Cite multiple passages separately, e.g. [1][3]. Never cite a number that is not in the context.
- If the context does not contain enough information to answer the question, reply with exactly \
{INSUFFICIENT_EVIDENCE} and nothing else."""

MAX_STRICT_CLAIMS = 20
MAX_STRICT_CLAIM_CHARS = 500

STRICT_INSTRUCTIONS = f"""Strict mode: a previous answer to this question was rejected because \
some of its claims are not supported by the context passages.{{claims}}
- Do not repeat a rejected claim unless a passage states it explicitly.
- State only what the passages say explicitly, and cite every sentence. Leave out anything you \
cannot cite, even if it seems likely.
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


def is_refusal(text: str) -> bool:
    """True if a Claude reply begins with the INSUFFICIENT_EVIDENCE refusal token."""
    return _REFUSAL_RE.match(text) is not None


def parse_citations(text: str, num_chunks: int) -> list[int]:
    """Return valid 1-based citation numbers in order of first appearance, without duplicates."""
    seen: list[int] = []
    for match in _CITATION_RE.finditer(text):
        number = int(match.group(1))
        if 1 <= number <= num_chunks and number not in seen:
            seen.append(number)
    return seen


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
    Raises `LLMError` if the Claude call fails.
    """
    question = question.strip()
    if not question:
        raise ValueError("question must not be empty")
    if not chunks:
        return GenerationResult(INSUFFICIENT_EVIDENCE, None, [], [], None)

    system = SYSTEM_PROMPT
    if strict_instructions and strict_instructions.strip():
        system = f"{SYSTEM_PROMPT}\n\n{strict_instructions.strip()}"
    llm = call_claude(build_prompt(question, chunks), system=system, max_tokens=max_tokens)
    text = llm.text.strip()

    if is_refusal(text):
        return GenerationResult(INSUFFICIENT_EVIDENCE, None, [], [], llm)

    citations = parse_citations(text, len(chunks))
    return GenerationResult(
        status=ANSWERED,
        answer=text,
        citations=citations,
        cited_chunks=[chunks[n - 1] for n in citations],
        llm=llm,
    )
