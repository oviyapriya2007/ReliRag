"""Deterministic, language-level checks on answers and their evidence.

Used by the evaluator to tell limitation statements from factual claims, to check that a quote
actually supports its claim, and to check citations. Nothing here depends on what the documents
are about: the word lists are English function words and phrasing used by the generator and
evaluator prompts.
"""
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.retrieval import RetrievedChunk

_QUOTE_CHARS = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
                              "\u2013": "-", "\u2014": "-"})
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:['./-][a-z0-9]+)*")
_CITATION_RE = re.compile(r"\[(\d+)\]")
_NUMBER_TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)*|[a-z]+")
_CALC_TOKEN_RE = re.compile(
    r"(?P<num>\d+(?:[.,]\d+)*)|(?P<op>[×*+−÷/]|(?<!\S)[xX-](?!\S))|(?P<eq>=)"
    r"|(?P<brk>[:;()\[\]\n]|[.!?,](?=\s|$))|(?P<word>[^\W\d_]+)")
_CALC_OPERATORS = {"×": "*", "x": "*", "X": "*", "*": "*", "+": "+", "-": "-", "−": "-",
                   "÷": "/", "/": "/"}
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
                               "unstated", "unable", "incomplete", "truncated", "cut"}
# "without" negates a fact ("written without co-writers"); it never by itself says that the
# sources leave something out.
_LIMITATION_CUE_WORDS = LIMITATION_CUES - {"without"}
# A limitation is about what the sources (or the answerer) do and do not cover, so it must also
# refer to them; "X does not do Y" without such a reference is a negative factual claim.
SOURCE_REFERENCES = frozenset("""
passage passages document documents context source sources excerpt excerpts information evidence
detail details mention mentions mentioned specify specifies specified say says said stated
discuss discusses discussed describe describes described clarify clarifies clarified explain
explains explained i unclear uncertain unspecified unstated text
""".split())
# A leading attribution to the sources ("Based on the context provided, X ..."), which says
# where a statement comes from, not what the sources leave out.
_SOURCE_LEAD_IN_RE = re.compile(
    r"^[\W_]*(?:based\s+on|according\s+to|as\s+(?:stated|described|shown|noted)\s+in|"
    r"from|per|in)\s+(?:the\s+)?(?:[^\W\d_]+\s+){0,2}?(?:context|passages?|documents?|"
    r"sources?|texts?|excerpts?|information|evidence)(?:\s+(?:provided|given|retrieved|"
    r"above|supplied))?\s*,\s*", re.IGNORECASE)
# A limitation statement only says what is missing; one that also asserts something is mixed.
CONTRAST_MARKERS = frozenset({"but", "however", "although", "though", "yet", "whereas", "while"})
# Contrast markers that, as a statement's first word ("However, ..."), only link it to the
# previous sentence. The rest ("Although X, ...") open a clause of the statement itself.
LEADING_DISCOURSE_MARKERS = frozenset({"but", "however", "yet"})
_LEADING_MARKER_RE = re.compile(
    rf"^[\W_]*(?:{'|'.join(sorted(LEADING_DISCOURSE_MARKERS))})\b[\W_]*", re.IGNORECASE)
_CLAUSE_BREAK_RE = re.compile(r"[,;:]|\s(?:and|or)\s", re.IGNORECASE)
# Qualifiers compared as classes: a claim that generalizes ("always", "all") where the evidence
# does not, or drops a hedge ("may", "some") the evidence has, states more than the evidence.
UNIVERSAL_QUALIFIERS = frozenset({"always", "all", "every", "only", "entirely", "completely",
                                  "fully", "exclusively"})
HEDGES = frozenset({"may", "might", "often", "usually", "sometimes", "typically", "generally",
                    "some", "likely", "possibly"})
# Words that open a new clause; a hedge beyond one of them qualifies that clause, not the quote.
CLAUSE_OPENERS = frozenset({"that", "which", "who", "whom", "whose", "and", "but", "or", "while",
                            "whereas", "although", "though", "because", "since", "unless"})
_CLAUSE_TOKEN_RE = re.compile(r"[^\W_]+|[,;:()\[\]\u2022\u25cf]")
# Determiners that may precede a claim's grammatical subject ("The X200 was ...").
_SUBJECT_DETERMINERS = frozenset({"the", "a", "an", "this", "that", "these", "those", "its",
                                  "their", "his", "her", "our", "both", "each"})
# A passive construction ("was built by"): it states its agent after the verb, so the names of
# an active paraphrase appear in the opposite order without reversing the relationship.
_PASSIVE_RE = re.compile(r"\b(?:is|are|was|were|be|been|being)\s+(?:[a-z]+\s+){1,2}?by\b")
# Words introducing the list a count counts ("Three features are A, B, and C").
_LIST_INTRO_RE = re.compile(r"\s(?:are|were|include|includes|included|including|comprise|"
                            r"comprises|comprised)\s|:\s*")
_LIST_INTRO_WORDS = frozenset({"are", "were", "is", "was", "has", "have", "include", "includes",
                               "included", "including", "comprise", "comprises", "comprised"})
_ITEM_SPLIT_RE = re.compile(r"\s*,\s*(?:(?:and|or)\s+)?|\s+(?:and|or)\s+|\s*[\u2022\u25cf]\s*")
_BULLET_RE = re.compile(r"[\u2022\u25cf\u25aa\u25e6\u2023\u2043]")
# Where a list starts in source text: a colon, a list-introducing word, a first numbered item,
# or a bullet. Items are separated by commas, semicolons, bullets, numbering, "and", "or".
_LIST_START_RE = re.compile(
    r":\s|\b(?:include|includes|included|including|are|were|such\s+as|feature|features|"
    r"featured|featuring|contain|contains|contained|comprise|comprises|comprised|"
    r"consists?\s+of|lists?|listed)\b|(?<![\w.])1[.)](?=\s)|[\u2022\u25cf\u25aa\u25e6\u2023\u2043]",
    re.IGNORECASE)
_LIST_SEPARATOR_RE = re.compile(
    r"[,;\u2022\u25cf\u25aa\u25e6\u2023\u2043]|(?<![\w.])\d{1,3}[.)](?=\s)|\b(?:and|or)\b",
    re.IGNORECASE)
# What may follow a list item: a separator, the end, a closing mark, or item details such
# as a number ("3:50") or a dash.
_ITEM_END_RE = re.compile(
    r"\s*(?:$|[,;.:!?)\]\u2022\u25cf\u25aa\u25e6\u2023\u2043*\u2013\u2014\"'(-]|\d|(?:and|or)\b)",
    re.IGNORECASE)
_HEAD_BOUNDARY_RE = re.compile(r"[.!?]\s+")
MAX_LIST_ITEM_WORDS = 8
MAX_LIST_HEAD_WORDS = 30
LIST_WINDOW_CHARS = 800
_PLURAL_NOUNS = frozenset({"people", "children", "men", "women", "data", "criteria", "media"})
_COORDINATORS = frozenset({"and", "or", "&"})
_COORDINATION_FILLERS = frozenset({"the", "a", "an", "both", "either"})
# Words of a limitation statement that say what kind of gap it is, not what it is about.
_LIMITATION_META = frozenset({
    "provide", "provides", "provided", "list", "lists", "listed", "include", "includes",
    "included", "contain", "contains", "contained", "cover", "covers", "covered", "address",
    "addresses", "addressed", "give", "gives", "indicate", "indicates", "indicated", "exact",
    "exactly", "precise", "precisely", "specific", "specifically", "explicit", "explicitly",
    "directly", "clear", "clearly", "whether", "find", "found", "able", "sure", "confirm",
    "confirms", "determine", "available", "reference", "references", "referenced", "appear",
    "appears", "appeared", "seem", "seems", "seemed", "off"})
# Where a statement labeled a limitation divides into clauses (see `unscored_parts`).
_STATEMENT_PART_RE = re.compile(
    r"[;:,]|\s(?:and|or)\s|\b(?:but|however|although|though|yet|whereas|while)\b",
    re.IGNORECASE)
# A limitation using these is about something beyond what a claim states ("other features",
# "why it happens"), so a claim on the same topic does not contradict it.
_LIMITATION_BEYOND = frozenset({"other", "others", "more", "additional", "further", "remaining",
                                "else", "beyond", "besides", "except", "all", "every", "full",
                                "complete", "why", "reason", "reasons", "cause", "causes"})
_HOW_QUANTITIES = frozenset({"many", "much", "long", "often", "far", "old", "large", "big",
                             "soon", "frequently", "high", "low", "fast", "quickly"})

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


# Words that name a calculation or its result rather than a fact from the sources.
_CALCULATION_TERMS = frozenset(_stem(word) for word in (
    "total", "sum", "combined", "overall", "altogether", "calculation", "calculated", "result"))


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
    return {value for value, _, _ in _number_spans(normalize_text(strip_citations(text)))}


def _number_spans(text: str) -> list[tuple[str, int, int]]:
    """(value, start, end) of every number in normalized `text` (see `numbers`)."""
    tokens = list(_NUMBER_TOKEN_RE.finditer(text))
    found = []
    index = 0
    while index < len(tokens):
        word, value = tokens[index].group(), None
        start, end = tokens[index].span()
        if word[0].isdigit():
            found.append((word.replace(",", ""), start, end))
            index += 1
            continue
        if word in _TENS:
            value = _TENS[word]
            if index + 1 < len(tokens) and 0 < _UNITS.get(tokens[index + 1].group(), 0) < 10:
                index += 1
                value += _UNITS[tokens[index].group()]
                end = tokens[index].end()
        elif word in _UNITS and word != "one":
            value = _UNITS[word]
        index += 1
        if value is not None and not (index < len(tokens) and tokens[index].group() in _SCALES):
            found.append((str(value), start, end))
    return found


_QUOTE_MARK_RE = re.compile(r"\"|(?<![^\W_])'|'(?![^\W_])")


def _list_items(text: str) -> list[str]:
    """Items of an "A, B, and C" (or bulleted) list making up `text`. Quotation marks around
    items are ignored, including punctuation placed inside them ("A," "B," and "C.")."""
    text = _QUOTE_MARK_RE.sub(" ", text).strip().rstrip(".!?;: ")
    return [item.strip() for item in _ITEM_SPLIT_RE.split(text) if _WORD_RE.search(item)]


def _counted_noun_is_plural(after: str) -> bool:
    """True if the words right after a number ("notable features of ...") name a plural noun,
    so the number counts things rather than measuring a quantity ("3 GB plan")."""
    for word in _TOKEN_RE.findall(after)[:3]:
        if word in _LIST_INTRO_WORDS:
            return False
        if word in _PLURAL_NOUNS or (word.endswith("s") and not word.endswith("ss")
                                      and len(word) > 2 and not word.isdigit()):
            return True
        if word in STOPWORDS:
            return False
    return False


def _claim_list(claim: str, start: int, end: int) -> list[str] | None:
    """The items the count at `claim[start:end]` counts, when the claim lists them: after a
    list-introducing word following the count ("Three features are A, B, and C"), or before
    one right in front of it ("A, B, and C are three features"). None if it lists none."""
    intros = list(_LIST_INTRO_RE.finditer(claim))
    after = [match for match in intros if match.start() >= end]
    if after:
        items = _list_items(claim[after[0].end():])
    else:
        before = [match for match in intros
                  if match.end() <= start and len(claim[match.end():start].split()) <= 1]
        if not before:
            return None
        items = _list_items(claim[:before[-1].start()])
    return items if len(items) >= 2 else None


def _named_groups(text: str, known: frozenset[str]) -> list[list[str]]:
    """Coordinated names in `text` ("the Atlas and the Zephyr", "A, B, or C"), each group
    with two or more items; adjacent names form one multi-word item."""
    groups: list[list[str]] = []
    current: list[str] = []
    gap: list[str] = []
    for word, name, _ in _named_words(text.replace(",", " and "), known):
        if name is None:
            gap.append(word.casefold())
            if gap[-1] not in _COORDINATORS | _COORDINATION_FILLERS:
                if len(current) >= 2:
                    groups.append(current)
                current, gap = [], []
            continue
        if current and not gap:
            current[-1] = f"{current[-1]} {name}"
        elif current and _COORDINATORS & set(gap):
            current.append(name)
        else:
            if len(current) >= 2:
                groups.append(current)
            current = [name]
        gap = []
    if len(current) >= 2:
        groups.append(current)
    return groups


def _evidence_list_sizes(sentence: str) -> set[int]:
    """Sizes of the lists `sentence` states: bulleted items, or a comma list of three or more
    items after a list-introducing word ("Features include A, B, and C")."""
    sizes = set()
    bullets = len(_BULLET_RE.findall(sentence))
    if bullets >= 2:
        sizes.add(bullets)
    normalized = normalize_text(sentence)
    for match in _LIST_INTRO_RE.finditer(normalized):
        items = _list_items(_EVIDENCE_SENTENCE_RE.split(normalized[match.end():], maxsplit=1)[0])
        if len(items) >= 3:
            sizes.add(len(items))
    return sizes


def _ends_with_separator(segment: str) -> bool:
    """True if `segment` (the text between a list's start and an item) is empty or ends
    with an item separator, apart from spaces, quotes, and an opening parenthesis."""
    if not segment.strip(" \t\"'("):
        return True
    last = None
    for last in _LIST_SEPARATOR_RE.finditer(segment):
        pass
    return last is not None and not segment[last.end():].strip(" \t\"'(")


def _next_item_follows(after: str) -> bool:
    """True if another list item follows an item: a separator within MAX_LIST_ITEM_WORDS
    words, with no sentence end before it, and a word after it."""
    separator = _LIST_SEPARATOR_RE.search(after[:LIST_WINDOW_CHARS])
    if separator is None:
        return False
    between = after[:separator.start()]
    return (len(_ANCHOR_WORD_RE.findall(between)) <= MAX_LIST_ITEM_WORDS
            and not re.search(r"[.!?]\s", between)
            and bool(_ANCHOR_WORD_RE.search(after[separator.end():separator.end() + 80])))


def list_head(quote: str, text: str) -> str | None:
    """The heading of the list that `quote` is an item of in `text`, or None.

    In "Album X track listing: 1. A 2. B 3. C" the quote "B" is an item of a list headed by
    "Album X track listing:", so the passage states "Album X track listing: B" even though
    no sentence of it does word for word. The quote must be a whole item (followed by a
    separator, the end, or item details such as a number), the list must have another item
    before or right after it, every item between the list's start and the quote must be
    short, and the list must start at a colon, a list-introducing
    word ("include", "are", ...), a first numbered item, or a bullet. The heading is the text
    from the start of its sentence to the list's start, extended to the sentence before when
    it names nothing itself ("Track listing:"), and at most MAX_LIST_HEAD_WORDS words.
    """
    words = _ANCHOR_WORD_RE.findall(unicodedata.normalize("NFKC", strip_citations(quote)))
    if not words:
        return None
    source = unicodedata.normalize("NFKC", text).translate(_QUOTE_CHARS)
    pattern = r"(?<![^\W_])" + r"[\W_]+".join(map(re.escape, words)) + r"(?![^\W_])"
    found = re.search(pattern, source, re.IGNORECASE)
    if found is None or not _ITEM_END_RE.match(source, found.end()):
        return None
    before = source[max(0, found.start() - LIST_WINDOW_CHARS):found.start()]
    start, earlier_items = None, False
    for candidate in reversed(list(_LIST_START_RE.finditer(before))):
        segment = before[candidate.end():]
        items = [item for item in _LIST_SEPARATOR_RE.split(segment)
                 if _ANCHOR_WORD_RE.search(item)]
        if any(len(_ANCHOR_WORD_RE.findall(item)) > MAX_LIST_ITEM_WORDS for item in items):
            break
        if _ends_with_separator(segment):
            start, earlier_items = candidate, bool(items)
    if start is None or not (earlier_items or _next_item_follows(source[found.end():])):
        return None
    marker = start.group()
    head_text = before[:start.start()] + (marker if marker[0].isalpha() else "")
    boundaries = list(_HEAD_BOUNDARY_RE.finditer(head_text))
    head = head_text[boundaries[-1].end():] if boundaries else head_text
    if not anchor_sequence(head) and boundaries:
        head = head_text[boundaries[-2].end() if len(boundaries) >= 2 else 0:]
    head = " ".join(head.split()[-MAX_LIST_HEAD_WORDS:]).strip(" :")
    return head or None


def claim_list_items(claim: str) -> list[str] | None:
    """The items of a list the claim states ("The album includes A, B, and C", "A, B, and C
    are tracks on it"), or None if it states no list of two or more items."""
    text = normalize_text(strip_citations(claim))
    intro = _LIST_INTRO_RE.search(text)
    if intro is None:
        return None
    items = _list_items(text[intro.end():])
    if len(items) >= 2:
        return items
    if len(text[intro.end():].split()) <= 5:
        items = _list_items(text[:intro.start()])
        if len(items) >= 2:
            return items
    return None


def count_list_mismatch(claim: str) -> str | None:
    """Why a count in the claim disagrees with the list it counts ("Three tracks are A and
    B"), or None. A number that only measures something ("the 3 GB plan includes A and B")
    is not a count (`_counted_noun_is_plural`)."""
    text = normalize_text(strip_citations(claim))
    for value, start, end in _number_spans(text):
        if not value.isdigit() or not _counted_noun_is_plural(text[end:]):
            continue
        items = _claim_list(text, start, end)
        if items is not None and len(items) != int(value):
            return f"the claim states {value} but lists {len(items)} item(s)"
    return None


# A listed item with at most this many content words is a name or short phrase ("Love
# Story", "guest isolation"), which must occur as a phrase, not as scattered words.
MAX_PHRASE_ITEM_TERMS = 2


def _phrase_occurs(item: str, text: str) -> bool:
    """True if the item's words, from its first to its last content word, occur
    consecutively in `text`, compared by stem ("parental control" in "parental controls")."""
    words = _MATCH_WORD_RE.findall(normalize_text(item))
    content = [i for i, word in enumerate(words) if word not in STOPWORDS]
    if not content:
        return True
    target = [_stem(word) for word in words[content[0]:content[-1] + 1]]
    source = [_stem(word) for word in _MATCH_WORD_RE.findall(normalize_text(text))]
    return any(source[start:start + len(target)] == target
               for start in range(len(source) - len(target) + 1))


def item_supported(item: str, available: str, available_terms: set[str] | None = None) -> bool:
    """True if a listed item occurs in `available`: as a phrase when it is a name or short
    phrase (MAX_PHRASE_ITEM_TERMS), else with most of its content words."""
    terms = content_terms(item)
    if not terms:
        return True
    if len(terms) <= MAX_PHRASE_ITEM_TERMS:
        return _phrase_occurs(item, available)
    if available_terms is None:
        available_terms = content_terms(available)
    return len(terms & available_terms) / len(terms) >= MIN_SUPPORT_COVERAGE


def unsupported_list_items(claim: str, available: str) -> tuple[list[str], int]:
    """(the claim's listed items that do not occur in `available` (`item_supported`), how
    many checkable items it lists); ([], 0) when it lists none."""
    items = claim_list_items(claim)
    if not items:
        return [], 0
    available_terms = content_terms(available)
    checkable = [item for item in items if content_terms(item)]
    missing = [item for item in checkable
               if not item_supported(item, available, available_terms)]
    return missing, len(checkable)


def supported_counts(claim: str, values: set[str], evidence_text: str,
                     evidence_sentences: Sequence[str], *, premises: set[str] = frozenset(),
                     premise_names: set[str] = frozenset(),
                     known: frozenset[str] = frozenset()) -> tuple[set[str], str | None]:
    """(values of `values` the evidence supports as counts in `claim`, why one is not).

    A number counts things when the words after it name a plural noun ("three features").
    Such a count is supported when:

    - the claim lists the counted items itself, the list has exactly that many items, and
      each item's content words occur in `evidence_text`; or, when the claim lists none,
    - an evidence sentence coordinates exactly that many names, all named by the question or
      the claim ("the Atlas and the Zephyr" for "the two bicycles"); or
    - the question states the count (`premises`), and an evidence sentence that mentions the
      counted noun lists exactly that many items.

    Any other number is a quantity the evidence must state itself.
    """
    text = normalize_text(strip_citations(claim))
    evidence_terms = content_terms(evidence_text)
    claim_names = set(anchor_sequence(claim, known))
    counted: set[str] = set()
    problem: str | None = None
    for value, start, end in _number_spans(text):
        if value not in values or value in counted or not _counted_noun_is_plural(text[end:]):
            continue
        expected = int(value) if value.isdigit() else None
        if expected is None:
            continue
        items = _claim_list(text, start, end)
        if items is not None:
            if len(items) != expected:
                problem = problem or (f"the claim states {value} but lists {len(items)} "
                                      f"item(s)")
                continue
            unsupported = [item for item in items
                           if not content_terms(item)
                           or not item_supported(item, evidence_text, evidence_terms)]
            if unsupported:
                problem = problem or (f"listed item(s) {', '.join(unsupported)} do not occur "
                                      f"in the cited passage")
                continue
            counted.add(value)
            continue
        allowed = premise_names | claim_names
        if any(len(group) == expected and all(name in allowed for item in group
                                               for name in item.split())
               for sentence in evidence_sentences for group in _named_groups(sentence, known)):
            counted.add(value)
            continue
        noun = next((_stem(word) for word in _TOKEN_RE.findall(text[end:])
                     if word not in STOPWORDS), None)
        if value in premises and noun and any(
                expected in _evidence_list_sizes(sentence) and noun in content_terms(sentence)
                for sentence in evidence_sentences):
            counted.add(value)
    return counted, problem


@dataclass(frozen=True)
class _Calculation:
    operands: tuple[str, ...]
    result: str
    correct: bool


def _calculation_value(operands: Sequence[str], operators: Sequence[str]) -> float | None:
    """`operands` combined by `operators`, with × and ÷ before + and -; None on division by 0."""
    values = [float(operand) for operand in operands]
    terms, signs = [values[0]], []
    for operator, value in zip(operators, values[1:]):
        if operator in "*/":
            if operator == "/" and value == 0:
                return None
            terms[-1] = terms[-1] * value if operator == "*" else terms[-1] / value
        else:
            terms.append(value)
            signs.append(operator)
    total = terms[0]
    for sign, value in zip(signs, terms[1:]):
        total = total + value if sign == "+" else total - value
    return total


def _calculations(text: str) -> list[_Calculation]:
    """Arithmetic written out in `text`, such as "₹20 × 4 days = ₹80" or "2 × 4 × 20 = 160".

    An expression is numbers joined by operators, ending at "=" and the number right after it.
    Unit words may follow a number ("4 days ×"), but nothing else may come between an operator
    and its next number, and a clause break (",", ":", ";", a bracket, a line or sentence end)
    ends the expression. "x" and "-" count as operators only when standing alone.
    """
    text = unicodedata.normalize("NFKC", strip_citations(text)).translate(_QUOTE_CHARS)
    tokens = [(match.lastgroup, match.group()) for match in _CALC_TOKEN_RE.finditer(text)]
    found = []
    for index, (kind, _) in enumerate(tokens):
        if kind != "eq" or index + 1 >= len(tokens) or tokens[index + 1][0] != "num":
            continue
        position = index - 1
        while position >= 0 and tokens[position][0] == "word":
            position -= 1
        if position < 0 or tokens[position][0] != "num":
            continue
        operands, operators = [tokens[position][1]], []
        while (position >= 2 and tokens[position - 1][0] == "op"):
            before = position - 2
            while before >= 0 and tokens[before][0] == "word":
                before -= 1
            if before < 0 or tokens[before][0] != "num":
                break
            operators.insert(0, _CALC_OPERATORS[tokens[position - 1][1]])
            operands.insert(0, tokens[before][1])
            position = before
        if not operators:
            continue
        operands = [operand.replace(",", "") for operand in operands]
        result = tokens[index + 1][1].replace(",", "")
        value = _calculation_value(operands, operators)
        decimals = len(result.split(".")[1]) if "." in result else 0
        correct = value is not None and round(value, decimals) == float(result)
        found.append(_Calculation(tuple(operands), result, correct))
    return found


def grounded_calculations(text: str, evidence: set[str],
                          premises: set[str] = frozenset()) -> tuple[set[str], set[str]]:
    """(numbers accounted for, results) of the correct calculations in `text` (`_calculations`)
    that are grounded in the evidence.

    A calculation is grounded when every operand is an `evidence` number, a `premises` number
    (one the question gives), or the result of another grounded calculation, and at least one
    operand is not a premise, so arithmetic on the question's numbers alone proves nothing
    about the sources. A number stated outside a grounded calculation is not accounted for.
    """
    known = set(evidence)
    accounted: set[str] = set()
    results: set[str] = set()
    pending = [calculation for calculation in _calculations(text) if calculation.correct]
    progress = True
    while progress:
        progress = False
        for calculation in list(pending):
            operands = calculation.operands
            if (all(o in known or o in premises for o in operands)
                    and any(o in known for o in operands)):
                pending.remove(calculation)
                known.add(calculation.result)
                results.add(calculation.result)
                accounted.update(operands, [calculation.result])
                progress = True
    return accounted, results


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
    a limitation cue together with a reference to the sources or what they state.

    A leading attribution ("Based on the context provided, ...") is not such a reference, and
    "without" is not such a cue, so "Based on the context, X was written without co-writers"
    is a factual statement."""
    tokens = set(_tokens(_SOURCE_LEAD_IN_RE.sub("", strip_citations(text), count=1)))
    return bool(tokens & _LIMITATION_CUE_WORDS) and bool(tokens & SOURCE_REFERENCES)


def is_pure_limitation(text: str) -> bool:
    """A limitation statement that asserts nothing else (no contrasting clause).

    A leading discourse marker ("However, the passages do not ...") is not a contrasting
    clause, but only when the clause right after it is the limitation itself; any other
    contrast marker still makes the statement mixed.
    """
    rest = _LEADING_MARKER_RE.sub("", text, count=1)
    if rest != text and not is_limitation_statement(_CLAUSE_BREAK_RE.split(rest, maxsplit=1)[0]):
        return False
    return (is_limitation_statement(rest)
            and not any(token in CONTRAST_MARKERS for token in _tokens(rest)))


_NOT_NAMES = STOPWORDS | LIMITATION_CUES


def _name(word: str, starts_sentence: bool, known: frozenset[str] = frozenset()) -> str | None:
    letters = sum(ch.isalpha() for ch in word)
    if not letters or word == "I":
        return None
    if len(word) > 1 and word.casefold() in _NOT_NAMES:
        return None
    if letters < len(word) or (letters >= 2 and word.isupper()):
        return word.casefold()
    if word[0].isupper() and (not starts_sentence
                              or (len(word) > 1 and word.casefold() in known)):
        return word if len(word) == 1 else word.casefold()
    return None


def _is_titlecase(word: str) -> bool:
    return word.isalpha() and word[0].isupper() and (len(word) == 1 or word[1:].islower())


def _label_positions(words: Sequence[str], known: frozenset[str]) -> set[int]:
    """Positions of the field label ending `words` ("Release date" in "Model X200 Release
    date"), which a colon follows: a capitalized word and at most three lowercase words.
    A word known as a name elsewhere ("Kestrel: launched ...") is not a label."""
    for start in range(len(words) - 1, max(len(words) - 5, -1), -1):
        word = words[start]
        if _is_titlecase(word):
            if word.casefold() in known:
                return set()
            return set(range(start, len(words)))
        if not (word.isalpha() and word.islower()):
            return set()
    return set()


def _named_words(text: str,
                 known: frozenset[str] = frozenset()) -> list[tuple[str, str | None, bool]]:
    """Every word of `text` with the name it is (see `anchor_sequence`) or None, and whether
    it is part of a field label ("Dosage" in "Dosage: one tablet"), which is never a name.

    A capitalized word that starts a sentence is a name only if it is in `known` (names seen
    elsewhere where capitalization is not explained by position).
    """
    text = unicodedata.normalize("NFKC", strip_citations(text)).translate(_QUOTE_CHARS)
    named = []
    position = 0
    for separator in [*_ANCHOR_BREAK_RE.finditer(text), None]:
        part = text[position:separator.start() if separator else len(text)]
        words = _ANCHOR_WORD_RE.findall(part)
        labels = (_label_positions(words, known)
                  if separator is not None and separator.group().startswith(":") else set())
        for index, word in enumerate(words):
            is_label = index in labels
            named.append((word, None if is_label else _name(word, index == 0, known), is_label))
        if separator is not None:
            position = separator.end()
    return named


def anchor_sequence(text: str, known: frozenset[str] = frozenset()) -> list[str]:
    """Names that pin down what `text` is about, in order of first appearance: acronyms
    ("ABC"), words mixing letters and digits ("X200"), capitalized words or single capital
    letters that do not start a sentence ("Paris", "item A"), and sentence-initial words that
    are in `known` ("Rust extended ..."). Field labels ("Weight:") are not names.

    Lowercased, except single letters, whose case is what makes them names.
    """
    return list(dict.fromkeys(name for _, name, _ in _named_words(text, known) if name))


def name_vocabulary(*texts: str) -> frozenset[str]:
    """Multi-letter names of `texts` found where position does not explain capitalization;
    passed as `known` so the same words also count as names at the start of a sentence."""
    return frozenset(name for text in texts for name in anchor_sequence(text) if len(name) > 1)


def name_groups(text: str, known: frozenset[str] = frozenset()) -> list[frozenset[str]]:
    """The multiword names of `text`: runs of adjacent name words ("Taylor Swift",
    "Speak Now"), each as the set of its names (see `anchor_sequence`)."""
    groups: list[frozenset[str]] = []
    current: list[str] = []
    for _, name, _ in [*_named_words(text, known), ("", None, False)]:
        if name:
            current.append(name)
        elif current:
            groups.append(frozenset(current))
            current = []
    return list(dict.fromkeys(groups))


def _same_entity(group: frozenset[str], others: Sequence[frozenset[str]]) -> bool:
    """True if a name and one of `others` name the same thing: one's words contain the
    other's ("Swift" in "Taylor Swift"), not merely share one ("Alice Smith", "Bob Smith")."""
    return any(group <= other or other <= group for other in others)


def claim_subject(text: str, known: frozenset[str] = frozenset()) -> str | None:
    """The name a statement starts with, after determiners ("X200" in "The X200 was ..."),
    taken as its grammatical subject; None if it starts any other way."""
    for word, name, _ in _named_words(text, known):
        if name:
            return name
        if word.casefold() not in _SUBJECT_DETERMINERS:
            return None
    return None


def quote_context(quote: str, chunk_text: str,
                  known: frozenset[str] = frozenset()) -> tuple[set[str], str | None]:
    """(the names the quoted statement is about, its record), read from the chunk's own text.

    The subject is the names in the quoted words, else the nearest name before them in their
    sentence (e.g. "ABC" for the quote "provides ..." in "ABC provides ..."). Names in the
    value of a field ("Release date: March 3, 2021") are not its subject: the record's
    heading before the label is ("X200" in "Model X200 Release date: ..."), and the record is
    the text from that heading to the end of the quote. The record is None when the quote is
    not a field value of an earlier heading.
    """
    quote_words = [w.casefold() for w in _words(quote)]
    for sentence in evidence_sentences(quote, chunk_text):
        named = _named_words(sentence, known)
        words = [word.casefold() for word, _, _ in named]
        for start in range(len(words) - len(quote_words) + 1):
            if not quote_words or words[start:start + len(quote_words)] != quote_words:
                continue
            span = named[start:start + len(quote_words)]
            label = next((i for i, (_, _, is_label) in enumerate(span) if is_label), None)
            inside = {name for _, name, _ in (span if label is None else span[:label]) if name}
            if inside:
                return inside, None
            before = [(i, name) for i, (_, name, _) in enumerate(named[:start]) if name]
            if not before:
                return set(), None
            heading, name = before[-1]
            if label is None:
                return {name}, None
            return {name}, " ".join(word for word, _, _ in named[heading:start + len(quote_words)])
    return anchors(quote, known), None


def quote_subjects(quote: str, chunk_text: str, known: frozenset[str] = frozenset()) -> set[str]:
    """The names the quoted statement is about (see `quote_context`)."""
    return quote_context(quote, chunk_text, known)[0]


def anchors(text: str, known: frozenset[str] = frozenset()) -> set[str]:
    return set(anchor_sequence(text, known))


def quote_clause(quote: str, sentence: str) -> str:
    """The clause of `sentence` the quote belongs to: the quote extended to the nearest
    punctuation or clause-opening word ("that", "which", "and", ...) on either side, so a
    hedge there ("Patients may experience ...") qualifies it while one in another clause
    ("..., and sessions that are usually booked") does not. `sentence` if the quote is not
    found in it word for word."""
    target = _MATCH_WORD_RE.findall(normalize_text(quote))
    for text in (normalize_text(sentence),
                 _LINE_BREAK_HYPHEN_RE.sub("", normalize_text(sentence))):
        tokens = _CLAUSE_TOKEN_RE.findall(text)
        positions = [i for i, token in enumerate(tokens) if _MATCH_WORD_RE.fullmatch(token)]
        words = [tokens[i] for i in positions]
        for start in range(len(words) - len(target) + 1):
            if not target or words[start:start + len(target)] != target:
                continue
            first, last = positions[start], positions[start + len(target) - 1]
            while (first > 0 and _MATCH_WORD_RE.fullmatch(tokens[first - 1])
                   and tokens[first - 1] not in CLAUSE_OPENERS):
                first -= 1
            while (last + 1 < len(tokens) and _MATCH_WORD_RE.fullmatch(tokens[last + 1])
                   and tokens[last + 1] not in CLAUSE_OPENERS):
                last += 1
            return " ".join(tokens[first:last + 1])
    return sentence


def is_passive(text: str) -> bool:
    return bool(_PASSIVE_RE.search(normalize_text(strip_citations(text))))


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
                evidence: Sequence[tuple[str, str]],
                *,
                premises: set[str] = frozenset(),
                derived: set[str] = frozenset(),
                premise_names: set[str] = frozenset(),
                known: frozenset[str] = frozenset(),
                cited_texts: Sequence[str] = ()) -> tuple[str | None, str | None]:
    """(highest verdict the evidence allows, reason), or (None, None) if it holds up.

    `evidence` holds (quote, evidence text) pairs for every passage the claim relies on, each
    quote already known to occur in its text; together they must state the claim. A quote
    that is an item of a list (`list_head`) states the item together with the list's heading
    ("Album X track listing: B"), so the heading's words and names count as part of what it
    states; the quote itself must still state the claim's other words. `cited_texts` are the
    passages the answer cites for the claim, where the claim's listed items may also be found.

    - Every number in the claim (written in digits or words) occurs in the evidence, is part
      of a correct calculation in the claim grounded in it (`grounded_calculations`), whose
      operands may also be `premises` (numbers the question gives), is in `derived` (results
      of grounded calculations elsewhere in the answer), or is a count the evidence supports
      (`supported_counts`, which may use `premise_names`, the names the question gives).
    - Every name in the claim (see `anchor_sequence`, with `known` names recognized at the
      start of a sentence too) occurs in the evidence. If the quoted statement is about
      another name (`quote_context`), or the claim's grammatical subject (`claim_subject`) is
      not the quote's, and the quote states most of the rest of the claim ("X does Y" for
      evidence "Z does Y"), the claim is unsupported, or partial when the claim's name also
      appears near the quote (in its sentence, or in its record for a field value).
      A name the evidence never mentions otherwise leaves it partial.
    - A count agrees with the list it counts (`count_list_mismatch`), whether or not the
      number happens to occur in the evidence.
    - The quotes, with their list headings, share enough of the claim's content words, and
      the quotes themselves state enough of the words the headings do not.
    - Every item of a list the claim states occurs in the quotes, their headings, the
      evidence passages, or `cited_texts` (all items missing: unsupported; some: partial).
    - Polarity matches: a quote with every content word of the claim and the opposite polarity
      contradicts it (unsupported); a weaker polarity difference leaves it partial.
    - The claim does not generalize ("always", "all") beyond the evidence sentences or drop a
      hedge ("may", "some") of the quote's own clause (`quote_clause`), and names do not
      appear in the opposite order (a reversed relationship) unless exactly one of the claim
      and the quote is passive ("X built Y" for "Y was built by X").

    These checks only find reasons to doubt the evaluator's verdict; they never confirm one.
    """
    quotes = [quote for quote, _ in evidence]
    chunk_texts = [text for _, text in evidence]
    sentences = [s for quote, text in evidence for s in evidence_sentences(quote, text)]
    heads = [head for quote, text in evidence if (head := list_head(quote, text))]
    item_texts = [*quotes, *heads, *chunk_texts, *cited_texts]
    partial: str | None = None

    mismatch = count_list_mismatch(claim)
    if mismatch:
        return CAP_NONE, mismatch
    evidence_numbers = set().union(*map(numbers, chunk_texts))
    calculated, _ = grounded_calculations(claim, evidence_numbers | derived, premises)
    calculated |= numbers(claim) & derived
    missing = numbers(claim) - evidence_numbers - calculated
    counted: set[str] = set()
    count_problem = None
    if missing:
        counted, count_problem = supported_counts(
            claim, missing, " ".join(item_texts), [*sentences, *heads], premises=premises,
            premise_names=premise_names, known=known)
    missing_numbers = sorted(missing - counted)
    if missing_numbers:
        return CAP_NONE, (count_problem or f"number(s) {', '.join(missing_numbers)} do not "
                                           f"occur in the cited passage")

    # Numbers checked by a grounded calculation, and the words naming it ("total"), need no
    # quote, nor do supported counts; the claim's other words still do.
    terms = content_terms(claim)
    if calculated:
        terms = {term for term in terms
                 if term not in _CALCULATION_TERMS and not numbers(term) & calculated}
    if counted:
        terms = {term for term in terms if not numbers(term) & counted}
    quote_terms = content_terms(" ".join(quotes))
    head_terms = content_terms(" ".join(heads))
    stated_terms = quote_terms | head_terms
    claim_names = anchor_sequence(claim, known)
    contexts = [quote_context(quote, text, known) for quote, text in evidence]
    subjects = set().union(*(found for found, _ in contexts), *(anchors(h, known) for h in heads))
    nearby = [text for (_, record), (quote, chunk_text) in zip(contexts, evidence)
              for text in ([record] if record is not None
                           else evidence_sentences(quote, chunk_text))] + heads
    # Names are compared as whole names: the quote's "Swift" is the claim's "Taylor Swift".
    claim_groups = name_groups(claim, known)
    subject_groups = [group for text in [*quotes, *heads] for group in name_groups(text, known)
                      if group & subjects]
    subject_groups += [frozenset({name}) for name in subjects
                       if not any(name in group for group in subject_groups)]

    def matches_subject(name: str) -> bool:
        group = next((g for g in claim_groups if name in g), frozenset({name}))
        return _same_entity(group, subject_groups)

    unmatched = {name for name in subjects
                 if not _same_entity(next((g for g in subject_groups if name in g),
                                          frozenset({name})), claim_groups)}
    mismatched = [n for n in claim_names if not matches_subject(n)] if unmatched else []
    subject = claim_subject(claim, known)
    if (subject is not None and subjects and not matches_subject(subject)
            and subject not in mismatched):
        mismatched.insert(0, subject)
    others = ", ".join(sorted((unmatched - set(claim_names)) or unmatched or subjects))
    for name in mismatched:
        rest = terms - content_terms(name)
        restated = rest & stated_terms
        if (len(restated) >= min(MIN_SHARED_TERMS, len(rest)) and rest
                and len(restated) / len(rest) >= MIN_SUPPORT_COVERAGE):
            if not any(mentions(s, name) for s in nearby):
                return CAP_NONE, f"the quoted statement is about {others}, not {name}"
            partial = partial or (f"the quoted statement is about {others}; {name} is only "
                                  f"mentioned nearby")
    missing_names = [name for name in claim_names
                     if not any(mentions(text, name) for text in chunk_texts)]
    if missing_names:
        partial = partial or f"the evidence does not mention {', '.join(missing_names)}"

    if terms:
        shared = terms & stated_terms
        share = len(shared) / len(terms)
        if (share < MIN_PARTIAL_COVERAGE or len(shared) < min(MIN_SHARED_TERMS, len(terms))
                or not terms & quote_terms):
            return CAP_NONE, "evidence_quote does not support the claim"
        if share < MIN_SUPPORT_COVERAGE:
            partial = partial or "evidence_quote supports only part of the claim"
        own = terms - head_terms
        if head_terms and own and len(own & quote_terms) / len(own) < MIN_SUPPORT_COVERAGE:
            partial = partial or ("evidence_quote states only part of what the claim adds to "
                                  "the list it belongs to")

    missing_items, listed = unsupported_list_items(claim, " ".join(item_texts))
    if missing_items and len(missing_items) == listed:
        return CAP_NONE, (f"listed item(s) {', '.join(missing_items)} do not occur in the "
                          f"cited passages")
    if missing_items:
        partial = partial or (f"listed item(s) {', '.join(missing_items)} do not occur in the "
                              f"cited passages")

    for quote in quotes:
        if negated(claim) != negated(quote) and terms and terms <= content_terms(quote):
            return CAP_NONE, "evidence_quote states the opposite of the claim"
    if negated(claim) != negated(quotes[0]):
        partial = partial or "claim and evidence_quote differ in negation"

    claim_tokens = set(_tokens(claim))
    context_tokens = set(_tokens(" ".join([*quotes, *sentences])))
    if claim_tokens & UNIVERSAL_QUALIFIERS and not context_tokens & UNIVERSAL_QUALIFIERS:
        partial = partial or "the claim generalizes beyond the evidence"
    clauses = [quote_clause(quote, sentence)
               for quote, text in evidence for sentence in evidence_sentences(quote, text)]
    if set(_tokens(" ".join([*quotes, *clauses]))) & HEDGES and not claim_tokens & HEDGES:
        partial = partial or "the evidence is qualified but the claim is not"

    for (quote, _), (found, _) in zip(evidence, contexts):
        if is_passive(claim) != is_passive(quote):
            continue
        names = set(claim_names) | found
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


def with_lead_ins(sentences: Sequence[AnswerSentence]) -> list[AnswerSentence]:
    """`sentences` with each list item under a lead-in ("Three tracks from X are:") read
    together with it ("Three tracks from X are: - A [1]"), keeping the item's own citations,
    so a claim about an item is matched to the line that cites it rather than to the uncited
    lead-in. An item is a line after the lead-in too short to state a fact on its own."""
    combined: list[AnswerSentence] = []
    lead: str | None = None
    for sentence in sentences:
        text = strip_citations(sentence.text).strip().rstrip("*_` ")
        if text.endswith(":"):
            lead = text
            combined.append(sentence)
        elif lead is not None and len(content_terms(text)) < MIN_FACT_TERMS:
            combined.append(AnswerSentence(f"{lead} {sentence.text}", sentence.citations))
        else:
            lead = None
            combined.append(sentence)
    return combined


def cited_passages(claim: str, answer: str,
                   chunks: Sequence["RetrievedChunk"]) -> list["RetrievedChunk"]:
    """The existing passages cited by the answer sentence that states `claim`
    (`match_sentence` over `with_lead_ins`), in citation order; [] if none matches."""
    sentences = with_lead_ins(split_sentences(answer))
    index = match_sentence(claim, sentences)
    if index is None:
        return []
    return [chunks[number - 1] for number in dict.fromkeys(sentences[index].citations)
            if 1 <= number <= len(chunks)]


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
                     chunks: Sequence["RetrievedChunk"],
                     contiguous: Mapping[int, Sequence[str]] | None = None) -> str | None:
    """Why the sentence stating `claim` is not properly cited, or None.

    The sentence must cite only existing passages, and at least one cited passage must contain
    one of the claim's evidence quotes or most of the claim's content words. `contiguous` maps
    a chunk ID to its text joined with an adjacent chunk of the same document, so a quote
    spanning that boundary counts as contained in either chunk.
    """
    invalid = invalid_citations(sentence, len(chunks))
    if invalid:
        return f"cites passage number(s) {invalid} that do not exist"
    if not sentence.citations:
        return "statement has no citation"
    cited = [chunks[number - 1] for number in sentence.citations]
    for chunk in cited:
        texts = [chunk.text, *(contiguous or {}).get(chunk.chunk_id, ())]
        if any(quote and quote_occurs(quote, text) for quote in quotes for text in texts):
            return None
        if (coverage(claim, chunk.text) or 0.0) >= MIN_SUPPORT_COVERAGE:
            return None
    return "cited passage(s) do not contain the evidence for this statement"


def limitation_topic(text: str) -> set[str]:
    """Content words of a limitation statement naming what it says is missing ("clinic",
    "open" in "The passages do not state when the clinic opens"), without the words that
    only say it is missing or refer to the sources."""
    meta = {_stem(word) for word in
            _LIMITATION_META | LIMITATION_CUES | SOURCE_REFERENCES | CONTRAST_MARKERS}
    return {term for term in content_terms(text) if term not in meta}


def unscored_parts(statement: str, claims: Sequence[str]) -> list[str]:
    """The clauses of a statement labeled a limitation that assert something no claim
    scores; [] if it only states limitations and restates claims.

    The statement is split at clause boundaries and contrast words. A clause that is itself
    a limitation (`is_limitation_statement`), or names nothing besides the sources, is fine;
    so is one whose words (apart from those referring to the sources) all occur in one of
    `claims`, the answer's own claims, which are verified separately ("The passages mention
    that X contains Y" when "X contains Y" is a claim). Any other clause is a factual
    assertion the statement would otherwise slip past the checks.
    """
    claim_terms = [content_terms(claim) for claim in claims]
    unscored = []
    for part in _STATEMENT_PART_RE.split(strip_citations(statement)):
        part = part.strip(" .!?\"'")
        if not part or is_limitation_statement(part):
            continue
        topic = limitation_topic(part)
        if topic and not any(topic <= terms for terms in claim_terms):
            unscored.append(part)
    return unscored


def _asked_quantities(text: str) -> set[str]:
    """Stems of the measure words a limitation asks "how" about ("long" in "how long")."""
    tokens = _tokens(strip_citations(text))
    return {_stem(tokens[index + 1]) for index, token in enumerate(tokens[:-1])
            if token == "how" and tokens[index + 1] in _HOW_QUANTITIES}


def limitation_is_open_ended(text: str) -> bool:
    """True if a limitation is about something beyond what a statement on its topic would
    state: other or further items, a complete list, a reason ("why"), or a manner ("how"
    other than "how many", "how long", ...)."""
    tokens = _tokens(strip_citations(text))
    if set(tokens) & _LIMITATION_BEYOND:
        return True
    return any(token == "how" and (index + 1 >= len(tokens)
                                   or tokens[index + 1] not in _HOW_QUANTITIES)
               for index, token in enumerate(tokens))


def contradicted_claim(limitation: str, claims: Sequence[str]) -> str | None:
    """The first of `claims` that states what `limitation` says the sources leave out, or None.

    A limitation contradicts a claim when every word naming what it says is missing
    (`limitation_topic`) occurs in that claim: "The passages do not state when the clinic
    opens" against "The clinic opens at 8 am". A limitation about something else ("when the
    clinic closes") or beyond the claim (`limitation_is_open_ended`) does not; contrast words
    such as "however" play no part. A limitation asking for a quantity ("how long the
    warranty lasts") is about its other words, at least two of them, and contradicts only a
    claim that states a number ("The warranty lasts 2 years").
    """
    topic = limitation_topic(limitation)
    if limitation_is_open_ended(limitation):
        return None
    quantities = _asked_quantities(limitation)
    if quantities:
        topic -= quantities
        if len(topic) < MIN_SHARED_TERMS:
            return None
    if not topic:
        return None
    limitation_key = normalize_text(strip_citations(limitation)).rstrip(" .!?;:")
    for claim in claims:
        if normalize_text(strip_citations(claim)).rstrip(" .!?;:") == limitation_key:
            continue
        if topic <= content_terms(claim) and (not quantities or numbers(claim)):
            return claim
    return None


def is_factual_sentence(sentence: AnswerSentence) -> bool:
    """A sentence that asserts something checkable (not a limitation, heading, or lead-in)."""
    text = strip_citations(sentence.text).strip().rstrip("*_` ")
    if text.startswith("#") or text.endswith((":", "?")):
        return False
    return (not is_limitation_statement(text)
            and len(content_terms(text)) >= MIN_FACT_TERMS)
