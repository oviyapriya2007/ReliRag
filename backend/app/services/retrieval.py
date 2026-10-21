import re
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Document, DocumentChunk, RetrievalLog
from app.services.answer_checks import content_terms, normalize_text
from app.services.ingestion import embed_texts

DEFAULT_TOP_K = 5
MAX_TOP_K = 50
# How many times `k` candidates a search may read to replace chunks that repeat another
# chunk's text (see `_search`).
DUPLICATE_SEARCH_FACTOR = 4
# Reciprocal rank fusion constant; 60 is the usual choice and damps the weight of rank 1.
RRF_K = 60
# Most requirements of one question searched separately (each costs one vector search).
MAX_SUBQUERIES = 6
# A chunk among this many top results that is cut off mid-text brings its continuation, the
# next chunk of its document (see `add_continuations`).
CONTINUATION_RANKS = 3
_SENTENCE_END_RE = re.compile(r"[.!?][\"'\u201d\u2019)\]]*\s*$")

_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)]|\(?[a-z][.)])\s+(.+)$", re.MULTILINE)
_QUESTION_RE = re.compile(r"[^?]*\?")
_SENTENCE_RE = re.compile(r"[^.;:!?\n]+")
_LAST_ITEM_RE = re.compile(r"^(?:and|or)\s+|\s+(?:and|or)\s+", re.IGNORECASE)
# Lead-in phrases ("According to the report, ...") that name the source, not a requirement.
_SOURCE_LEAD_IN_RE = re.compile(r"^(?:according\s+to|based\s+on|as\s+per|using)\b", re.IGNORECASE)
_LEAD_RE = re.compile(
    r"^(?:(?:and|or|also|then|please)\s+)*(?:(?:explain|describe|list|identify|compare|discuss|"
    r"define|outline|summari[sz]e|give|tell\s+me\s+about|what\s+(?:is|are)|how\s+(?:does|do|is|"
    r"are|can)|why\s+(?:is|are|does|do))\s+)?", re.IGNORECASE)


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    document_id: int
    document: str
    page: int | None
    text: str
    similarity: float
    # Position of the chunk in its document (DocumentChunk.chunk_index), when known; used to
    # tell source-contiguous chunks apart.
    chunk_index: int | None = None


def embed_query(question: str) -> list[float]:
    """Embed a question with the same model and normalization used for stored chunks."""
    return embed_texts([question])[0]


def _clean_requirement(text: str) -> str:
    text = text.strip(" \t,;:.?!")
    if _SOURCE_LEAD_IN_RE.match(text):
        return ""
    text = _LEAD_RE.sub("", text).strip(" \t,;:.?!")
    return " ".join(text.split())


def _enumeration(sentence: str) -> list[str]:
    """Items of an "A, B, and C" list (three or more items, last one joined by and/or)."""
    parts = [part.strip() for part in sentence.split(",")]
    if len(parts) < 2:
        return []
    last = parts[-1]
    if _LAST_ITEM_RE.match(last):
        items = parts[:-1] + [_LAST_ITEM_RE.sub("", last, count=1)]
    else:
        split = _LAST_ITEM_RE.split(last, maxsplit=1)
        if len(split) < 2:
            return []
        items = parts[:-1] + split
    return items if len(items) >= 3 else []


def split_requirements(question: str) -> list[str]:
    """Separate search queries for the distinct requirements a question lists, or [].

    Recognised forms: a bulleted or numbered list, several questions, and in-sentence
    enumerations of three or more items ("explain A, B, and C"). Lead-in phrases and items
    without content words (e.g. "According to the document") are dropped. A question with
    fewer than two such requirements returns [], so it is searched as a whole only.
    """
    listed = _LIST_ITEM_RE.findall(question)
    if len(listed) >= 2:
        candidates = listed
    else:
        questions = [q for q in _QUESTION_RE.findall(question) if q.strip(" ?")]
        candidates = questions if len(questions) >= 2 else []
        for sentence in _SENTENCE_RE.findall(question):
            candidates.extend(_enumeration(sentence))

    requirements: dict[str, str] = {}
    whole = " ".join(question.split()).casefold()
    for candidate in candidates:
        requirement = _clean_requirement(candidate)
        key = requirement.casefold()
        if key and key != whole and content_terms(requirement) and key not in requirements:
            requirements[key] = requirement
    found = list(requirements.values())[:MAX_SUBQUERIES]
    return found if len(found) >= 2 else []


def _nearest(
    db: Session,
    query_embedding: Sequence[float],
    k: int,
    document_ids: Sequence[int] | None,
    *,
    score_embedding: Sequence[float] | None = None,
) -> list[tuple[RetrievedChunk, float]]:
    """The `k` chunks closest to `query_embedding`, each with its similarity to it.

    Each chunk's `similarity` is measured against `score_embedding` (default: the query).
    """
    distance = DocumentChunk.embedding.cosine_distance(query_embedding).label("distance")
    score = (distance if score_embedding is None
             else DocumentChunk.embedding.cosine_distance(score_embedding)).label("score")
    stmt = (
        select(
            DocumentChunk.id,
            DocumentChunk.document_id,
            Document.filename,
            DocumentChunk.page_number,
            DocumentChunk.content,
            DocumentChunk.chunk_index,
            distance,
            score,
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.embedding.is_not(None), Document.deleted_at.is_(None))
    )
    if document_ids is not None:
        stmt = stmt.where(DocumentChunk.document_id.in_(list(document_ids)))
    # Equal distances (e.g. identical text in two documents) are ordered by chunk ID, so the
    # same query always returns the same chunks in the same order.
    stmt = stmt.order_by(distance, DocumentChunk.id).limit(k)

    return [
        (RetrievedChunk(
            chunk_id=row.id,
            document_id=row.document_id,
            document=row.filename,
            page=row.page_number,
            text=row.content,
            similarity=1.0 - float(row.score),
            chunk_index=row.chunk_index,
        ), 1.0 - float(row.distance))
        for row in db.execute(stmt)
    ]


def _search(
    db: Session,
    query_embedding: Sequence[float],
    k: int,
    document_ids: Sequence[int] | None,
    *,
    score_embedding: Sequence[float] | None = None,
) -> list[tuple[RetrievedChunk, float]]:
    """`_nearest`, without chunks whose text repeats a higher-ranked chunk's word for word.

    Repeats (e.g. the same document uploaded twice) would otherwise fill several of the `k`
    places with one passage. When dropping them leaves fewer than `k` chunks, the search goes
    deeper, up to DUPLICATE_SEARCH_FACTOR * `k` candidates.
    """
    limit = k * DUPLICATE_SEARCH_FACTOR
    fetch = k
    while True:
        rows = _nearest(db, query_embedding, fetch, document_ids,
                        score_embedding=score_embedding)
        seen: set[str] = set()
        distinct = []
        for row in rows:
            key = normalize_text(row[0].text)
            if key not in seen:
                seen.add(key)
                distinct.append(row)
        if len(distinct) >= k or len(rows) < fetch or fetch >= limit:
            return distinct[:k]
        fetch = min(fetch * 2, limit)


def combine_requirement_results(
    whole: Sequence[RetrievedChunk],
    per_requirement: Sequence[Sequence[tuple[RetrievedChunk, float]]],
    k: int,
    min_similarity: float,
) -> list[RetrievedChunk]:
    """Choose `k` chunks covering the whole question and each of its requirements.

    `whole` is the ranking for the whole question; `per_requirement` holds, for each
    requirement, (chunk, similarity to that requirement) in rank order. Every chunk's
    `similarity` must be against the whole question. Requirement matches below
    `min_similarity` are dropped; the rest are fused with `whole` by reciprocal rank (see
    `fuse_rankings`). The whole question's best chunk is always kept, and the result is in
    descending similarity to the whole question, so its first chunk, which the similarity gate
    checks, is exactly the whole-question search's top result.
    """
    if not whole:
        return []
    rankings = [list(whole)] + [[chunk for chunk, similarity in matches
                                 if similarity >= min_similarity]
                                for matches in per_requirement]
    best = whole[0]
    others = [chunk for chunk in fuse_rankings(rankings) if chunk.chunk_id != best.chunk_id]
    chosen = [best, *others[: k - 1]]
    return sorted(chosen, key=lambda chunk: -chunk.similarity)


def retrieve(
    db: Session,
    question: str,
    k: int = DEFAULT_TOP_K,
    document_ids: Sequence[int] | None = None,
) -> list[RetrievedChunk]:
    """Return `k` chunks for `question`, by cosine distance.

    A question that lists several requirements (see `split_requirements`) is also searched
    once per requirement, so each one is represented (see `combine_requirement_results`);
    requirement matches weaker than SIMILARITY_GATE are not used. Otherwise this is a plain
    nearest-neighbour search. Similarities are always against the whole question. A chunk whose
    text repeats a higher-ranked chunk's is skipped (see `_search`).
    `document_ids=None` searches all documents; an empty sequence matches nothing. Soft-deleted
    documents are never searched.
    """
    question = question.strip()
    if not question:
        raise ValueError("question must not be empty")
    if not 1 <= k <= MAX_TOP_K:
        raise ValueError(f"k must be between 1 and {MAX_TOP_K}")
    if document_ids is not None and len(document_ids) == 0:
        return []

    query_embedding = embed_query(question)
    whole = [chunk for chunk, _ in _search(db, query_embedding, k, document_ids)]
    requirements = split_requirements(question)
    if not requirements or not whole:
        return add_continuations(db, whole, query_embedding)
    per_requirement = [
        _search(db, embedding, k, document_ids, score_embedding=query_embedding)
        for embedding in embed_texts(requirements)
    ]
    return add_continuations(
        db, combine_requirement_results(whole, per_requirement, k, settings.similarity_gate),
        query_embedding)


def add_continuations(
    db: Session,
    chunks: Sequence[RetrievedChunk],
    query_embedding: Sequence[float],
    *,
    ranks: int = CONTINUATION_RANKS,
) -> list[RetrievedChunk]:
    """`chunks` with the continuation of each of the first `ranks` that is cut off mid-text.

    Chunks are fixed-size windows, so a section that a top result starts (an entry's heading
    and first facts) can end in the next window (the rest of the entry, such as its list of
    items), which may rank too low to be retrieved. The continuation is the next chunk
    (chunk_index + 1) of the same, not deleted, document; it is inserted right after the
    chunk it continues, with its own similarity to the query, unless it is already among
    `chunks`. Chunks without a known chunk_index are left as they are.
    """
    chunks = list(chunks)
    present = {(chunk.document_id, chunk.chunk_index) for chunk in chunks}
    wanted = [(chunk.document_id, chunk.chunk_index + 1) for chunk in chunks[:ranks]
              if chunk.chunk_index is not None
              and (chunk.document_id, chunk.chunk_index + 1) not in present
              and not _SENTENCE_END_RE.search(chunk.text)]
    if not wanted:
        return chunks
    distance = DocumentChunk.embedding.cosine_distance(query_embedding).label("distance")
    stmt = (
        select(DocumentChunk.id, DocumentChunk.document_id, Document.filename,
               DocumentChunk.page_number, DocumentChunk.content, DocumentChunk.chunk_index,
               distance)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.embedding.is_not(None), Document.deleted_at.is_(None),
               or_(*(and_(DocumentChunk.document_id == document_id,
                          DocumentChunk.chunk_index == chunk_index)
                     for document_id, chunk_index in wanted)))
    )
    found = {
        (row.document_id, row.chunk_index): RetrievedChunk(
            chunk_id=row.id, document_id=row.document_id, document=row.filename,
            page=row.page_number, text=row.content, similarity=1.0 - float(row.distance),
            chunk_index=row.chunk_index)
        for row in db.execute(stmt)
    }
    result = []
    for chunk in chunks:
        result.append(chunk)
        if chunk.chunk_index is not None:
            continuation = found.pop((chunk.document_id, chunk.chunk_index + 1), None)
            if continuation is not None:
                result.append(continuation)
    return result


def merge_ranked_chunks(
    primary: Sequence[RetrievedChunk],
    secondary: Sequence[RetrievedChunk],
    *,
    limit: int = MAX_TOP_K,
) -> list[RetrievedChunk]:
    """Fuse two rankings, each in rank order, into one list without duplicate chunks.

    See `fuse_rankings`; ties keep `primary` order first, and a chunk in both rankings keeps
    its `primary` entry. At most `limit` chunks are returned.
    """
    return fuse_rankings([primary, secondary], limit=limit)


def fuse_rankings(
    rankings: Sequence[Sequence[RetrievedChunk]], *, limit: int = MAX_TOP_K
) -> list[RetrievedChunk]:
    """Fuse rankings, each in rank order, into one list without duplicate chunks.

    The rankings may come from different queries, so their similarity scores are not
    compared: chunks are ordered by reciprocal rank fusion, the sum of 1 / (RRF_K + rank)
    over the rankings that contain them, and ties keep earlier rankings first. A chunk in
    several rankings keeps its entry from the first. At most `limit` chunks are returned.
    """
    entries: dict[int, RetrievedChunk] = {}
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking, start=1):
            entries.setdefault(chunk.chunk_id, chunk)
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (RRF_K + rank)
    order = {chunk_id: position for position, chunk_id in enumerate(entries)}
    ranked = sorted(entries, key=lambda chunk_id: (-scores[chunk_id], order[chunk_id]))
    return [entries[chunk_id] for chunk_id in ranked[:limit]]


def load_logged_chunks(db: Session, answer_id: int) -> list[RetrievedChunk]:
    """Return the chunks logged for an answer attempt, in rank order, without retrieving again.

    This is history, so chunks of soft-deleted documents are included.
    """
    stmt = (
        select(
            RetrievalLog.chunk_id,
            RetrievalLog.similarity,
            DocumentChunk.document_id,
            Document.filename,
            DocumentChunk.page_number,
            DocumentChunk.content,
            DocumentChunk.chunk_index,
        )
        .join(DocumentChunk, DocumentChunk.id == RetrievalLog.chunk_id)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(RetrievalLog.answer_id == answer_id)
        .order_by(RetrievalLog.rank)
    )
    return [
        RetrievedChunk(
            chunk_id=row.chunk_id,
            document_id=row.document_id,
            document=row.filename,
            page=row.page_number,
            text=row.content,
            similarity=row.similarity,
            chunk_index=row.chunk_index,
        )
        for row in db.execute(stmt)
    ]
