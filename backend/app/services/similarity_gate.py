from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Answer, Query, RetrievalLog
from app.services.retrieval import DEFAULT_TOP_K, RetrievedChunk, retrieve

INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class GateResult:
    query_id: int
    answer_id: int
    passed: bool
    status: str | None
    top_similarity: float | None
    threshold: float
    chunks: list[RetrievedChunk]


def passes_gate(chunks: Sequence[RetrievedChunk], threshold: float) -> bool:
    """True if the top-1 chunk is at least `threshold` similar; no chunks never passes."""
    return bool(chunks) and chunks[0].similarity >= threshold


def retrieve_with_gate(
    db: Session,
    query: Query,
    *,
    retrieval_query: str | None = None,
    attempt_number: int = 1,
    k: int = DEFAULT_TOP_K,
    document_ids: Sequence[int] | None = None,
    threshold: float | None = None,
) -> GateResult:
    """Retrieve chunks for one answer attempt, log them, and apply the similarity gate.

    Creates the `answers` row for this attempt and one `retrieval_log` row per chunk,
    whether or not the gate passes. On failure the attempt and the query are marked
    INSUFFICIENT_EVIDENCE and no answer should be generated.
    """
    if threshold is None:
        threshold = settings.similarity_gate
    retrieval_query = retrieval_query or query.question

    chunks = retrieve(db, retrieval_query, k=k, document_ids=document_ids)
    passed = passes_gate(chunks, threshold)
    status = None if passed else INSUFFICIENT_EVIDENCE

    try:
        answer = Answer(
            query=query,
            attempt_number=attempt_number,
            retrieval_query=retrieval_query,
            status=status,
        )
        db.add(answer)
        db.flush()

        if chunks:
            db.execute(
                insert(RetrievalLog),
                [
                    {
                        "answer_id": answer.id,
                        "chunk_id": chunk.chunk_id,
                        "rank": rank,
                        "similarity": chunk.similarity,
                    }
                    for rank, chunk in enumerate(chunks, start=1)
                ],
            )
        if not passed:
            query.final_status = INSUFFICIENT_EVIDENCE
        db.commit()
    except Exception:
        db.rollback()
        raise

    return GateResult(
        query_id=query.id,
        answer_id=answer.id,
        passed=passed,
        status=status,
        top_similarity=chunks[0].similarity if chunks else None,
        threshold=threshold,
        chunks=chunks,
    )
