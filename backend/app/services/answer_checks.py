"""Deterministic, language-level checks on answers and their evidence.

Used by the evaluator to tell limitation statements from factual claims, to check that a quote
actually supports its claim, and to check citations. Nothing here depends on what the documents
are about: the word lists are English function words and phrasing used by the generator and
evaluator prompts.
"""
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.retrieval import RetrievedChunk

_QUOTE_CHARS = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
                              "\u2013": "-", "\u2014": "-"})
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:['./-][a-z0-9]+)*")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
_CITATION_RE = re.compile(r"\[(\d+)\]")
_SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD_RE = re.compile(r"[^\W\d_]", re.UNICODE)

STOPWORDS = frozenset("""
a an the and or but if then than so as of to in on at by for from with into onto over under
about between through during before after above below up down out off again further once here
there when where why how all any both each few more most other some such only own same too very
can will just should would could may might must shall do does did doing done be is are was were
been being have has had having it its this that these those i me my we our you your he she they
them their his her him what which who whom whose also however therefore thus via etc one per
according based provided given context passage passages document documents text source sources
information answer question explain describe identify state states stated say says said mention
mentions mentioned following
""".split())
NEGATIONS = frozenset({"not", "no", "never", "cannot", "can't", "doesn't", "don't", "isn't",
                       "aren't", "wasn't", "weren't", "won't", "didn't", "without", "nor",
                       "neither", "none"})
LIMITATION_CUES = NEGATIONS | {"unclear", "unknown", "uncertain", "insufficient", "lack", "lacks",
                               "lacking", "missing", "absent", "unavailable", "unspecified",
                               "unable"}
# A limitation statement only says what is missing; one that also asserts something is mixed.
CONTRAST_MARKERS = frozenset({"but", "however", "although", "though", "yet", "whereas", "while"})

# A quote supports its claim fully when it shares at least this share of the claim's content
# words, partially when it shares at least MIN_PARTIAL_COVERAGE and MIN_SHARED_TERMS words.
MIN_SUPPORT_COVERAGE = 0.5
MIN_PARTIAL_COVERAGE = 0.25
MIN_SHARED_TERMS = 2
# A claim is matched to the answer sentence covering at least this share of its content words.
MIN_SENTENCE_MATCH = 0.5
# A sentence with fewer content words is not treated as a factual statement (headings, lead-ins).
MIN_FACT_TERMS = 3

# Highest verdict a check allows.
CAP_PARTIAL = "partial"
CAP_NONE = "none"


def normalize_text(text: str) -> str:
    """Casefolded text with whitespace collapsed and typographic quotes and dashes unified."""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTE_CHARS)
    return " ".join(text.split()).casefold()


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(normalize_text(text))


def _stem(word: str) -> str:
    """A crude stem: common inflections removed, then the first five letters."""
    if any(ch.isdigit() for ch in word):
        return word
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    return word[:5]


def content_terms(text: str) -> set[str]:
    """Stemmed words of `text` that carry meaning: no function words, negations, or citations."""
    return {_stem(token) for token in _tokens(strip_citations(text))
            if token not in STOPWORDS and token not in NEGATIONS
            and (len(token) > 1 or token.isdigit())}


def numbers(text: str) -> set[str]:
    return {number.replace(",", "") for number in _NUMBER_RE.findall(strip_citations(text))}


def has_negation(text: str) -> bool:
    return any(token in NEGATIONS for token in _tokens(text))


def coverage(claim: str, text: str) -> float | None:
    """Share of `claim`'s content words that also occur in `text`; None if it has none."""
    terms = content_terms(claim)
    if not terms:
        return None
    return len(terms & content_terms(text)) / len(terms)


def strip_citations(text: str) -> str:
    return _CITATION_RE.sub("", text)


def citation_numbers(text: str) -> list[int]:
    return [int(number) for number in _CITATION_RE.findall(text)]


def is_limitation_statement(text: str) -> bool:
    """True if `text` says that something is missing, unknown, or not covered."""
    return any(token in LIMITATION_CUES for token in _tokens(text))


def is_pure_limitation(text: str) -> bool:
    """A limitation statement that asserts nothing else (no contrasting clause)."""
    tokens = _tokens(text)
    return (any(token in LIMITATION_CUES for token in tokens)
            and not any(token in CONTRAST_MARKERS for token in tokens))


def support_cap(claim: str, quote: str, chunk_text: str) -> tuple[str | None, str | None]:
    """(highest verdict the quoted evidence allows, reason), or (None, None) if it holds up.

    `quote` is already known to occur in `chunk_text`. Every number in the claim must occur in
    the chunk; the quote must share enough of the claim's content words; and a negation in only
    one of claim and quote means the quote does not state the claim as written.
    """
    missing = sorted(numbers(claim) - numbers(chunk_text))
    if missing:
        return CAP_NONE, f"number(s) {', '.join(missing)} do not occur in the cited passage"
    terms = content_terms(claim)
    if terms:
        shared = terms & content_terms(quote)
        share = len(shared) / len(terms)
        if share < MIN_PARTIAL_COVERAGE or len(shared) < min(MIN_SHARED_TERMS, len(terms)):
            return CAP_NONE, "evidence_quote does not support the claim"
        if share < MIN_SUPPORT_COVERAGE:
            return CAP_PARTIAL, "evidence_quote supports only part of the claim"
    if has_negation(claim) != has_negation(quote):
        return CAP_PARTIAL, "claim and evidence_quote differ in negation"
    return None, None


@dataclass(frozen=True)
class AnswerSentence:
    text: str
    citations: tuple[int, ...]


def split_sentences(answer: str) -> list[AnswerSentence]:
    """The answer's sentences and lines, each with the [n] markers it contains.

    Markers written after a sentence's full stop (e.g. "... units. [2]") belong to it.
    """
    sentences: list[AnswerSentence] = []
    for part in _SENTENCE_BREAK_RE.split(answer):
        part = part.strip()
        if not part:
            continue
        cited = tuple(citation_numbers(part))
        if sentences and cited and not _WORD_RE.search(strip_citations(part)):
            previous = sentences[-1]
            sentences[-1] = AnswerSentence(f"{previous.text} {part}", previous.citations + cited)
        else:
            sentences.append(AnswerSentence(part, cited))
    return sentences


def match_sentence(claim: str, sentences: Sequence[AnswerSentence]) -> int | None:
    """Index of the sentence that best restates `claim`, or None if none covers enough of it."""
    best, best_share = None, 0.0
    for index, sentence in enumerate(sentences):
        share = coverage(claim, sentence.text) or 0.0
        if share > best_share:
            best, best_share = index, share
    return best if best_share >= MIN_SENTENCE_MATCH else None


def invalid_citations(sentence: AnswerSentence, num_chunks: int) -> list[int]:
    return [number for number in sentence.citations if not 1 <= number <= num_chunks]


def citation_problem(claim: str, quote: str | None, sentence: AnswerSentence,
                     chunks: Sequence["RetrievedChunk"]) -> str | None:
    """Why the sentence stating `claim` is not properly cited, or None.

    The sentence must cite only existing passages, and at least one cited passage must contain
    the claim's evidence quote or most of the claim's content words.
    """
    invalid = invalid_citations(sentence, len(chunks))
    if invalid:
        return f"cites passage number(s) {invalid} that do not exist"
    if not sentence.citations:
        return "statement has no citation"
    cited = [chunks[number - 1] for number in sentence.citations]
    normalized_quote = normalize_text(quote or "")
    for chunk in cited:
        if normalized_quote and normalized_quote in normalize_text(chunk.text):
            return None
        if (coverage(claim, chunk.text) or 0.0) >= MIN_SUPPORT_COVERAGE:
            return None
    return "cited passage(s) do not contain the evidence for this statement"


def is_factual_sentence(sentence: AnswerSentence) -> bool:
    """A sentence that asserts something checkable (not a limitation, heading, or lead-in)."""
    text = strip_citations(sentence.text).strip().rstrip("*_` ")
    if text.startswith("#") or text.endswith((":", "?")):
        return False
    return (not is_limitation_statement(text)
            and len(content_terms(text)) >= MIN_FACT_TERMS)
