from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk
from app.services.ingestion import embed_texts

DEFAULT_TOP_K = 5
MAX_TOP_K = 50


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    document_id: int
    document: str
    page: int | None
    text: str
    similarity: float


def embed_query(question: str) -> list[float]:
    """Embed a question with the same model and normalization used for stored chunks."""
    return embed_texts([question])[0]


def retrieve(
    db: Session,
    question: str,
    k: int = DEFAULT_TOP_K,
    document_ids: Sequence[int] | None = None,
) -> list[RetrievedChunk]:
    """Return the `k` chunks closest to `question` by cosine distance.

    `document_ids=None` searches all documents; an empty sequence matches nothing.
    """
    question = question.strip()
    if not question:
        raise ValueError("question must not be empty")
    if not 1 <= k <= MAX_TOP_K:
        raise ValueError(f"k must be between 1 and {MAX_TOP_K}")
    if document_ids is not None and len(document_ids) == 0:
        return []

    query_embedding = embed_query(question)
    distance = DocumentChunk.embedding.cosine_distance(query_embedding).label("distance")

    stmt = (
        select(
            DocumentChunk.id,
            DocumentChunk.document_id,
            Document.filename,
            DocumentChunk.page_number,
            DocumentChunk.content,
            distance,
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.embedding.is_not(None))
    )
    if document_ids is not None:
        stmt = stmt.where(DocumentChunk.document_id.in_(list(document_ids)))
    stmt = stmt.order_by(distance).limit(k)

    return [
        RetrievedChunk(
            chunk_id=row.id,
            document_id=row.document_id,
            document=row.filename,
            page=row.page_number,
            text=row.content,
            similarity=1.0 - float(row.distance),
        )
        for row in db.execute(stmt)
    ]
