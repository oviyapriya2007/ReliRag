from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Answer, Claim, DocumentChunk, Evaluation, Query, RetrievalLog
from app.schemas import (
    AttemptTimings,
    ClaimRead,
    EvaluationRead,
    QueryAttempt,
    QueryRequest,
    QueryResponse,
    RetrievalResult,
)
from app.services.generator import ANSWERED, parse_citations
from app.services.llm import LLMError
from app.services.query_pipeline import ERROR, run_basic_query, run_reli_rag
from app.services.similarity_gate import INSUFFICIENT_EVIDENCE

router = APIRouter(prefix="/query", tags=["query"])

GATE_FAILED_MESSAGE = (
    "I couldn't find enough evidence in the uploaded documents to answer this question. "
    "The most relevant passages did not meet the similarity threshold, so no answer was generated."
)
NOT_SUPPORTED_MESSAGE = (
    "I couldn't find enough evidence in the uploaded documents to answer this question. "
    "The retrieved passages did not contain the information needed."
)
ERROR_MESSAGE = "An error occurred while generating the answer. Please try again."


def _load_query(db: Session, query_id: int) -> Query | None:
    stmt = (
        select(Query)
        .where(Query.id == query_id)
        .options(
            selectinload(Query.answers).options(
                selectinload(Answer.retrieval_logs)
                .selectinload(RetrievalLog.chunk)
                .selectinload(DocumentChunk.document),
                selectinload(Answer.evaluations).selectinload(Evaluation.claims),
            )
        )
        .execution_options(populate_existing=True)
    )
    return db.scalars(stmt).first()


def claim_read(claim: Claim) -> ClaimRead:
    """API view of a stored claim; verification details stay null for claims saved before
    they were recorded."""
    return ClaimRead(
        claim_text=claim.claim_text,
        verdict=claim.verdict,
        evidence_chunk_id=claim.evidence_chunk_id,
        evidence_quote=claim.evidence_quote,
        claude_verdict=claim.claude_verdict,
        evidence_error=claim.evidence_error,
        check_name=claim.check_name,
    )


def _to_evaluation(evaluation: Evaluation) -> EvaluationRead:
    return EvaluationRead(
        faithfulness=evaluation.faithfulness,
        answer_relevance=evaluation.answer_relevance,
        context_relevance=evaluation.context_relevance,
        passed=evaluation.passed,
        failure_type=evaluation.failure_type,
        feedback=evaluation.feedback,
        claims=[
            claim_read(claim)
            for claim in evaluation.claims
        ],
    )


def _to_attempt(answer: Answer) -> QueryAttempt:
    retrieval = [
        RetrievalResult(
            rank=log.rank,
            chunk_id=log.chunk_id,
            document_id=log.chunk.document_id,
            filename=log.chunk.document.filename,
            page_number=log.chunk.page_number,
            chunk_index=log.chunk.chunk_index,
            similarity=log.similarity,
            content=log.chunk.content,
        )
        for log in answer.retrieval_logs
    ]
    # Citation [n] refers to the passage logged at rank n. Ranks stay fixed if a deleted
    # document removes some logged passages, so citations of the remaining ones still match.
    ranks = {result.rank for result in retrieval}
    citations = [number for number in parse_citations(answer.answer_text, max(ranks, default=0))
                 if number in ranks] if answer.answer_text else []
    # Evaluations are ordered by id, so the last one is the latest.
    evaluation = answer.evaluations[-1] if answer.evaluations else None
    return QueryAttempt(
        attempt_number=answer.attempt_number,
        answer=answer.answer_text,
        retrieval_query=answer.retrieval_query,
        strategy=answer.strategy,
        status=answer.status,
        model=answer.model,
        citations=citations,
        retrieval=retrieval,
        evaluation=_to_evaluation(evaluation) if evaluation is not None else None,
        timings=AttemptTimings(
            generate_ms=answer.latency_ms,
            evaluate_ms=evaluation.latency_ms if evaluation is not None else None,
            input_tokens=answer.input_tokens,
            output_tokens=answer.output_tokens,
        ),
    )


def _final_attempt(query: Query) -> Answer | None:
    """The attempt the query reports: the recorded choice, else (older rows) the last one."""
    for answer in query.answers:
        if answer.attempt_number == query.final_attempt_number:
            return answer
    return query.answers[-1] if query.answers else None


def _final_answer(query: Query, final: Answer | None) -> str | None:
    if query.final_status == ANSWERED and final is not None:
        return final.answer_text
    if query.final_status == INSUFFICIENT_EVIDENCE:
        claude_called = final is not None and final.model is not None
        return NOT_SUPPORTED_MESSAGE if claude_called else GATE_FAILED_MESSAGE
    if query.final_status == ERROR:
        return ERROR_MESSAGE
    return None


def _to_response(query: Query) -> QueryResponse:
    final = _final_attempt(query)
    return QueryResponse(
        query_id=query.id,
        question=query.question,
        mode=query.mode,
        created_at=query.created_at,
        status=query.final_status,
        final_answer=_final_answer(query, final),
        final_attempt_number=final.attempt_number if final is not None else None,
        attempts=[_to_attempt(answer) for answer in query.answers],
    )


# Sync handler on purpose: embedding and the Claude call block, so FastAPI runs it in a worker thread.
@router.post("", response_model=QueryResponse)
def run_query(request: QueryRequest, db: Session = Depends(get_db)):
    pipeline = run_reli_rag if request.mode == "reli" else run_basic_query
    try:
        query = pipeline(db, request.question, k=request.k, document_ids=request.document_ids)
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Claude call failed: {exc}") from exc

    return _to_response(_load_query(db, query.id))


@router.get("/{query_id}", response_model=QueryResponse)
def get_query(query_id: int, db: Session = Depends(get_db)):
    query = _load_query(db, query_id)
    if query is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Query {query_id} not found.")
    return _to_response(query)
