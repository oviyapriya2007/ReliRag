from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Answer, Query, RetrievalLog
from app.services.retrieval import DEFAULT_TOP_K, RetrievedChunk, merge_ranked_chunks, retrieve

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
    strategy: str | None = None,
    chunks: Sequence[RetrievedChunk] | None = None,
    carry_over: Sequence[RetrievedChunk] = (),
) -> GateResult:
    """Retrieve chunks for one answer attempt, log them, and apply the similarity gate.

    Creates the `answers` row for this attempt and one `retrieval_log` row per chunk,
    whether or not the gate passes. On failure the attempt is marked INSUFFICIENT_EVIDENCE
    and no answer should be generated. `query.final_status` is never changed here; the
    pipeline decides it. `chunks`, if given, are an already retrieved result (in rank order)
    for `retrieval_query`; they are gated and logged the same way, without retrieving again.

    `carry_over` are chunks kept from an earlier attempt (in that attempt's rank order). The
    gate is applied to this attempt's own retrieval only, since carried similarities were
    scored against a different query; if it passes, the carried chunks are merged in (see
    `merge_ranked_chunks`) and the merged list is what gets logged and returned.
    """
    if threshold is None:
        threshold = settings.similarity_gate
    retrieval_query = retrieval_query or query.question

    if chunks is None:
        chunks = retrieve(db, retrieval_query, k=k, document_ids=document_ids)
    else:
        chunks = list(chunks)
    passed = passes_gate(chunks, threshold)
    top_similarity = chunks[0].similarity if chunks else None
    if passed and carry_over:
        chunks = merge_ranked_chunks(chunks, carry_over)
    status = None if passed else INSUFFICIENT_EVIDENCE

    try:
        answer = Answer(
            query=query,
            attempt_number=attempt_number,
            retrieval_query=retrieval_query,
            strategy=strategy,
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
        db.commit()
    except Exception:
        db.rollback()
        raise

    return GateResult(
        query_id=query.id,
        answer_id=answer.id,
        passed=passed,
        status=status,
        top_similarity=top_similarity,
        threshold=threshold,
        chunks=chunks,
    )
