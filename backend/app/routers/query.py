from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Answer, DocumentChunk, Evaluation, Query, RetrievalLog
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
from app.services.query_pipeline import ERROR, run_basic_query
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


def _to_evaluation(evaluation: Evaluation) -> EvaluationRead:
    return EvaluationRead(
        faithfulness=evaluation.faithfulness,
        answer_relevance=evaluation.answer_relevance,
        context_relevance=evaluation.context_relevance,
        passed=evaluation.passed,
        failure_type=evaluation.failure_type,
        feedback=evaluation.feedback,
        claims=[
            ClaimRead(
                claim_text=claim.claim_text,
                verdict=claim.verdict,
                evidence_chunk_id=claim.evidence_chunk_id,
                evidence_quote=claim.evidence_quote,
            )
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
    citations = parse_citations(answer.answer_text, len(retrieval)) if answer.answer_text else []
    # Evaluations are ordered by id, so the last one is the latest.
    evaluation = answer.evaluations[-1] if answer.evaluations else None
    return QueryAttempt(
        attempt_number=answer.attempt_number,
        answer=answer.answer_text,
        retrieval_query=answer.retrieval_query,
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


def _final_answer(query: Query) -> str | None:
    last = query.answers[-1] if query.answers else None
    if query.final_status == ANSWERED and last is not None:
        return last.answer_text
    if query.final_status == INSUFFICIENT_EVIDENCE:
        claude_called = last is not None and last.model is not None
        return NOT_SUPPORTED_MESSAGE if claude_called else GATE_FAILED_MESSAGE
    if query.final_status == ERROR:
        return ERROR_MESSAGE
    return None


def _to_response(query: Query) -> QueryResponse:
    return QueryResponse(
        query_id=query.id,
        question=query.question,
        mode=query.mode,
        created_at=query.created_at,
        status=query.final_status,
        final_answer=_final_answer(query),
        attempts=[_to_attempt(answer) for answer in query.answers],
    )


# Sync handler on purpose: embedding and the Claude call block, so FastAPI runs it in a worker thread.
@router.post("", response_model=QueryResponse)
def run_query(request: QueryRequest, db: Session = Depends(get_db)):
    try:
        query = run_basic_query(db, request.question, k=request.k, document_ids=request.document_ids)
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Claude call failed: {exc}") from exc

    return _to_response(_load_query(db, query.id))


@router.get("/{query_id}", response_model=QueryResponse)
def get_query(query_id: int, db: Session = Depends(get_db)):
    query = _load_query(db, query_id)
    if query is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Query {query_id} not found.")
    return _to_response(query)
