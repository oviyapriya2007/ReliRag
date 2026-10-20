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
_NUMBER_WORD_RE = re.compile(r"[a-z]+")
_MATCH_WORD_RE = re.compile(r"[^\W_]+")
# A word split across a line break ("sepa-\nrate") in extracted text.
_LINE_BREAK_HYPHEN_RE = re.compile(r"(?<=[^\W\d_])-\s+(?=[^\W\d_])")
_UNITS = {word: value for value, word in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {word: 10 * value for value, word in enumerate(
    "twenty thirty forty fifty sixty seventy eighty ninety".split(), start=2)}
_SCALES = frozenset({"hundred", "thousand", "million", "billion", "trillion", "dozen"})
_ANCHOR_WORD_RE = re.compile(r"[^\W_]+")
_ANCHOR_BREAK_RE = re.compile(r"[.!?:;]\s+|\n+|[\"()\[\]]")
_EVIDENCE_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
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
                               "unstated", "unable"}
# A limitation is about what the sources (or the answerer) do and do not cover, so it must also
# refer to them; "X does not do Y" without such a reference is a negative factual claim.
SOURCE_REFERENCES = frozenset("""
passage passages document documents context source sources excerpt excerpts information evidence
detail details mention mentions mentioned specify specifies specified say says said stated
discuss discusses discussed describe describes described clarify clarifies clarified explain
explains explained i unclear uncertain unspecified unstated
""".split())
# A limitation statement only says what is missing; one that also asserts something is mixed.
CONTRAST_MARKERS = frozenset({"but", "however", "although", "though", "yet", "whereas", "while"})
# Qualifiers compared as classes: a claim that generalizes ("always", "all") where the evidence
# does not, or drops a hedge ("may", "some") the evidence has, states more than the evidence.
UNIVERSAL_QUALIFIERS = frozenset({"always", "all", "every", "only", "entirely", "completely",
                                  "fully", "exclusively"})
HEDGES = frozenset({"may", "might", "often", "usually", "sometimes", "typically", "generally",
                    "some", "likely", "possibly"})

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
    if word.endswith(("ies", "ied")) and len(word) >= 6:
        return (word[:-3] + "y")[:5]
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
    """The numbers `text` states, as digit strings: numerals, and spelled-out cardinals such
    as "three" or "twenty-five" (so "3" and "three" match, and "four" differs from "three").

    "one" alone is skipped because it is mostly a pronoun or article, and a spelled number
    followed by a scale word ("two hundred") is skipped because its value is not a single word.
    """
    text = normalize_text(strip_citations(text))
    found = {number.replace(",", "") for number in _NUMBER_RE.findall(text)}
    words = _NUMBER_WORD_RE.findall(text)
    index = 0
    while index < len(words):
        word, value = words[index], None
        if word in _TENS:
            value = _TENS[word]
            if index + 1 < len(words) and 0 < _UNITS.get(words[index + 1], 0) < 10:
                index += 1
                value += _UNITS[words[index]]
        elif word in _UNITS and word != "one":
            value = _UNITS[word]
        index += 1
        if value is not None and not (index < len(words) and words[index] in _SCALES):
            found.add(str(value))
    return found


def negated(text: str) -> bool:
    """True if `text` has an odd number of negations, so "cannot ... without" reads as positive."""
    return sum(token in NEGATIONS for token in _tokens(text)) % 2 == 1


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
    """True if `text` says that the sources leave something missing, unknown, or not covered:
    a limitation cue together with a reference to the sources or what they state."""
    tokens = set(_tokens(text))
    return bool(tokens & LIMITATION_CUES) and bool(tokens & SOURCE_REFERENCES)


def is_pure_limitation(text: str) -> bool:
    """A limitation statement that asserts nothing else (no contrasting clause)."""
    return (is_limitation_statement(text)
            and not any(token in CONTRAST_MARKERS for token in _tokens(text)))


def _name(word: str, starts_sentence: bool) -> str | None:
    letters = sum(ch.isalpha() for ch in word)
    if not letters or word == "I":
        return None
    if len(word) > 1 and word.casefold() in STOPWORDS | LIMITATION_CUES:
        return None
    if letters < len(word) or (letters >= 2 and word.isupper()):
        return word.casefold()
    if not starts_sentence and word[0].isupper():
        return word if len(word) == 1 else word.casefold()
    return None


def _named_words(text: str) -> list[tuple[str, str | None]]:
    """Every word of `text` with the name it is (see `anchor_sequence`), or None."""
    text = unicodedata.normalize("NFKC", strip_citations(text)).translate(_QUOTE_CHARS)
    named = []
    for part in _ANCHOR_BREAK_RE.split(text):
        for position, word in enumerate(_ANCHOR_WORD_RE.findall(part)):
            named.append((word, _name(word, position == 0)))
    return named


def anchor_sequence(text: str) -> list[str]:
    """Names that pin down what `text` is about, in order of first appearance: acronyms
    ("ABC"), words mixing letters and digits ("X200"), and capitalized words or single capital
    letters that do not start a sentence ("Paris", "item A").

    Lowercased, except single letters, whose case is what makes them names.
    """
    return list(dict.fromkeys(name for _, name in _named_words(text) if name))


def quote_subjects(quote: str, chunk_text: str) -> set[str]:
    """The names the quoted statement is about: those in the quoted words, else the nearest
    name before them in their sentence (e.g. "ABC" for the quote "provides ..." in "ABC
    provides ..."). Names are read from the chunk's own text, not from how the quote is cased.
    """
    quote_words = [w.casefold() for w in _words(quote)]
    for sentence in evidence_sentences(quote, chunk_text):
        named = _named_words(sentence)
        words = [word.casefold() for word, _ in named]
        for start in range(len(words) - len(quote_words) + 1):
            if quote_words and words[start:start + len(quote_words)] == quote_words:
                inside = {name for _, name in named[start:start + len(quote_words)] if name}
                before = [name for _, name in named[:start] if name]
                return inside or ({before[-1]} if before else set())
    return anchors(quote)


def anchors(text: str) -> set[str]:
    return set(anchor_sequence(text))


def _words(text: str) -> list[str]:
    return _ANCHOR_WORD_RE.findall(unicodedata.normalize("NFKC", text))


def mentions(text: str, anchor: str) -> bool:
    """True if `text` contains the name `anchor` (see `anchor_sequence`)."""
    if len(anchor) == 1:
        return anchor in _words(text)
    return anchor in {word.casefold() for word in _words(text)}


def evidence_sentences(quote: str, chunk_text: str) -> list[str]:
    """The sentences of `chunk_text` that contain `quote` or that `quote` spans, else [quote]."""
    sentences = [s for s in _EVIDENCE_SENTENCE_RE.split(chunk_text)
                 if s.strip() and (quote_occurs(quote, s) or quote_occurs(s, quote))]
    return sentences or [quote]


def _order(names: Sequence[str], text: str) -> list[str]:
    words = [w if len(w) == 1 else w.casefold() for w in _words(text)]
    seen: dict[str, None] = {}
    for word in words:
        if word in names:
            seen.setdefault(word, None)
    return list(seen)


def support_cap(claim: str,
                evidence: Sequence[tuple[str, str]]) -> tuple[str | None, str | None]:
    """(highest verdict the evidence allows, reason), or (None, None) if it holds up.

    `evidence` holds (quote, chunk text) pairs for every passage the claim relies on, each quote
    already known to occur in its chunk; together they must state the claim:

    - Every number in the claim (written in digits or words) occurs in the chunks.
    - Every name in the claim (see `anchor_sequence`) occurs in the chunks. If the quoted
      statement is about another name (`quote_subjects`) and states most of the rest of the
      claim ("X does Y" for evidence "Z does Y"), the claim is unsupported, or partial when the
      claim's name also appears in that sentence (two candidate subjects). A name the evidence
      never mentions otherwise leaves it partial.
    - The quotes share enough of the claim's content words.
    - Polarity matches: a quote with every content word of the claim and the opposite polarity
      contradicts it (unsupported); a weaker polarity difference leaves it partial.
    - The claim does not generalize ("always", "all") or drop a hedge ("may", "some") beyond the
      evidence sentences, and names do not appear in the opposite order (a reversed
      relationship).

    These checks only find reasons to doubt the evaluator's verdict; they never confirm one.
    """
    quotes = [quote for quote, _ in evidence]
    chunk_texts = [text for _, text in evidence]
    sentences = [s for quote, text in evidence for s in evidence_sentences(quote, text)]
    partial: str | None = None

    missing_numbers = sorted(numbers(claim) - set().union(*map(numbers, chunk_texts)))
    if missing_numbers:
        return CAP_NONE, (f"number(s) {', '.join(missing_numbers)} do not occur in the cited "
                          f"passage")

    terms = content_terms(claim)
    quote_terms = content_terms(" ".join(quotes))
    claim_names = anchor_sequence(claim)
    subjects = set().union(*(quote_subjects(quote, text) for quote, text in evidence))
    if subjects - set(claim_names):
        others = ", ".join(sorted(subjects - set(claim_names)))
        for name in (n for n in claim_names if n not in subjects):
            rest = terms - content_terms(name)
            restated = rest & quote_terms
            if (len(restated) >= min(MIN_SHARED_TERMS, len(rest)) and rest
                    and len(restated) / len(rest) >= MIN_SUPPORT_COVERAGE):
                if not any(mentions(s, name) for s in sentences):
                    return CAP_NONE, f"the quoted statement is about {others}, not {name}"
                partial = partial or (f"the quoted statement is about {others}; {name} is only "
                                      f"mentioned nearby")
    missing_names = [name for name in claim_names
                     if not any(mentions(text, name) for text in chunk_texts)]
    if missing_names:
        partial = partial or f"the evidence does not mention {', '.join(missing_names)}"

    if terms:
        shared = terms & quote_terms
        share = len(shared) / len(terms)
        if share < MIN_PARTIAL_COVERAGE or len(shared) < min(MIN_SHARED_TERMS, len(terms)):
            return CAP_NONE, "evidence_quote does not support the claim"
        if share < MIN_SUPPORT_COVERAGE:
            partial = partial or "evidence_quote supports only part of the claim"

    for quote in quotes:
        if negated(claim) != negated(quote) and terms and terms <= content_terms(quote):
            return CAP_NONE, "evidence_quote states the opposite of the claim"
    if negated(claim) != negated(quotes[0]):
        partial = partial or "claim and evidence_quote differ in negation"

    claim_tokens = set(_tokens(claim))
    context_tokens = set(_tokens(" ".join([*quotes, *sentences])))
    if claim_tokens & UNIVERSAL_QUALIFIERS and not context_tokens & UNIVERSAL_QUALIFIERS:
        partial = partial or "the claim generalizes beyond the evidence"
    if context_tokens & HEDGES and not claim_tokens & HEDGES:
        partial = partial or "the evidence is qualified but the claim is not"

    for quote, text in evidence:
        names = set(claim_names) | quote_subjects(quote, text)
        in_claim, in_quote = _order(names, claim), _order(names, quote)
        common = [name for name in in_claim if name in in_quote]
        if (len(common) >= 2 and [n for n in in_quote if n in common] != common
                and terms <= content_terms(quote)):
            partial = partial or "names appear in the opposite order in the evidence"
    return (CAP_PARTIAL, partial) if partial else (None, None)


def conflict_problem(claim: str, quote: str, chunk_text: str,
                     supporting_quotes: Sequence[str]) -> str | None:
    """Why a passage reported as contradicting `claim` does not count, or None if it does.

    `quote` is already known to occur in `chunk_text`. A conflict must be about the claim: not
    one of its own supporting quotes, mentioning every name in the claim, and covering enough of
    its content words. Whether it applies to the same conditions is the evaluator's judgement.
    """
    if any(quote_occurs(quote, s) or quote_occurs(s, quote) for s in supporting_quotes):
        return "it is part of the claim's own evidence"
    missing = [name for name in anchor_sequence(claim) if not mentions(chunk_text, name)]
    if missing:
        return f"it does not mention {', '.join(missing)}"
    terms = content_terms(claim)
    context = " ".join([quote, *evidence_sentences(quote, chunk_text)])
    if terms and len(terms & content_terms(context)) / len(terms) < MIN_PARTIAL_COVERAGE:
        return "it does not address the claim"
    return None


def _match_words(text: str, *, join_line_breaks: bool) -> str:
    text = normalize_text(text)
    if join_line_breaks:
        text = _LINE_BREAK_HYPHEN_RE.sub("", text)
    return " ".join(_MATCH_WORD_RE.findall(text))


def quote_occurs(quote: str, text: str) -> bool:
    """True if `quote` occurs verbatim in `text`, ignoring case, whitespace, typographic quotes
    and dashes, punctuation, and words hyphenated across a line break in `text`.

    The quote's words must still appear in `text` in the same order and without gaps.
    """
    normalized_quote = normalize_text(quote)
    if not normalized_quote:
        return False
    if normalized_quote in normalize_text(text):
        return True
    words = _match_words(quote, join_line_breaks=False)
    if not words:
        return False
    return any(f" {words} " in f" {_match_words(text, join_line_breaks=join)} "
               for join in (False, True))


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


def citation_problem(claim: str, quotes: Sequence[str], sentence: AnswerSentence,
                     chunks: Sequence["RetrievedChunk"]) -> str | None:
    """Why the sentence stating `claim` is not properly cited, or None.

    The sentence must cite only existing passages, and at least one cited passage must contain
    one of the claim's evidence quotes or most of the claim's content words.
    """
    invalid = invalid_citations(sentence, len(chunks))
    if invalid:
        return f"cites passage number(s) {invalid} that do not exist"
    if not sentence.citations:
        return "statement has no citation"
    cited = [chunks[number - 1] for number in sentence.citations]
    for chunk in cited:
        if any(quote and quote_occurs(quote, chunk.text) for quote in quotes):
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
