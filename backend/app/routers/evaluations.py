import csv
import io
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Answer, Document, DocumentChunk, Evaluation, RetrievalLog
from app.models import Query as StoredQuery
from app.schemas import ClaimRead
from app.services.evaluator import EVALUATOR_ERROR, PARTIALLY_SUPPORTED, SUPPORTED, UNSUPPORTED

router = APIRouter(prefix="/evaluations", tags=["evaluations"])

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
_ANSWER_ID_BATCH = 500

EvaluationStatus = Literal["passed", "failed", "evaluator_error"]

_NOT_ERROR = or_(Evaluation.failure_type.is_(None), Evaluation.failure_type != EVALUATOR_ERROR)
_STATUS_CONDITIONS = {
    "passed": and_(Evaluation.passed.is_(True), _NOT_ERROR),
    "failed": and_(Evaluation.passed.is_(False), _NOT_ERROR),
    "evaluator_error": Evaluation.failure_type == EVALUATOR_ERROR,
}
_LATEST = (
    select(Evaluation.answer_id, func.max(Evaluation.id).label("evaluation_id"))
    .group_by(Evaluation.answer_id)
    .subquery("latest")
)

CSV_FIELDS = (
    "evaluation_id", "answer_id", "query_id", "benchmark_run_id", "mode", "question",
    "query_created_at", "final_status", "final_attempt_number", "attempt_number", "strategy",
    "answer_status", "answer", "status", "passed", "failure_type", "faithfulness",
    "answer_relevance", "context_relevance", "supported_claims", "partially_supported_claims",
    "unsupported_claims", "total_claims", "feedback", "document_ids", "documents", "model",
    "latency_ms", "input_tokens", "output_tokens", "is_latest",
)
# Spreadsheet apps execute cells starting with these characters as formulas.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class EvaluationDocument(BaseModel):
    document_id: int
    filename: str


class EvaluationListItem(BaseModel):
    evaluation_id: int
    answer_id: int
    query_id: int
    benchmark_run_id: str | None
    mode: str
    question: str
    query_created_at: datetime
    final_status: str | None
    final_attempt_number: int | None
    attempt_number: int
    strategy: str | None
    answer_status: str | None
    answer: str | None
    status: EvaluationStatus | None = Field(
        description="evaluator_error when evaluation failed, else passed/failed; null if unknown.")
    passed: bool | None
    failure_type: str | None
    faithfulness: float | None
    answer_relevance: float | None
    context_relevance: float | None
    feedback: str | None
    model: str | None
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    is_latest: bool = Field(description="Whether this is the answer's most recent evaluation.")
    documents: list[EvaluationDocument] = Field(
        description="Documents the evaluated attempt retrieved, best-ranked first.")
    claims: list[ClaimRead]


class EvaluationPage(BaseModel):
    total: int = Field(description="Evaluations matching the filters, ignoring limit/offset.")
    limit: int
    offset: int
    items: list[EvaluationListItem]


@dataclass(frozen=True)
class EvaluationFilters:
    status: EvaluationStatus | None
    document_id: int | None
    latest_only: bool


def evaluation_filters(
    status: EvaluationStatus | None = Query(default=None),
    document_id: int | None = Query(
        default=None, ge=1, description="Only attempts that retrieved a chunk of this document."),
    latest_only: bool = Query(
        default=True, description="Skip evaluations superseded by a re-evaluation of the answer."),
) -> EvaluationFilters:
    return EvaluationFilters(status=status, document_id=document_id, latest_only=latest_only)


def _filtered(filters: EvaluationFilters, *columns: Any) -> Select:
    stmt = (
        select(*columns)
        .select_from(Evaluation)
        .join(Answer, Answer.id == Evaluation.answer_id)
        .join(StoredQuery, StoredQuery.id == Answer.query_id)
        .join(_LATEST, _LATEST.c.answer_id == Evaluation.answer_id)
    )
    if filters.latest_only:
        stmt = stmt.where(Evaluation.id == _LATEST.c.evaluation_id)
    if filters.status is not None:
        stmt = stmt.where(_STATUS_CONDITIONS[filters.status])
    if filters.document_id is not None:
        stmt = stmt.where(
            select(RetrievalLog.id)
            .join(DocumentChunk, DocumentChunk.id == RetrievalLog.chunk_id)
            .where(RetrievalLog.answer_id == Evaluation.answer_id,
                   DocumentChunk.document_id == filters.document_id)
            .exists()
        )
    return stmt


def _documents_by_answer(
    db: Session, answer_ids: Iterable[int]
) -> dict[int, list[EvaluationDocument]]:
    ids = sorted(set(answer_ids))
    first_rank = func.min(RetrievalLog.rank).label("first_rank")
    documents: dict[int, list[EvaluationDocument]] = defaultdict(list)
    for start in range(0, len(ids), _ANSWER_ID_BATCH):
        rows = db.execute(
            select(RetrievalLog.answer_id, Document.id, Document.filename, first_rank)
            .join(DocumentChunk, DocumentChunk.id == RetrievalLog.chunk_id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(RetrievalLog.answer_id.in_(ids[start:start + _ANSWER_ID_BATCH]))
            .group_by(RetrievalLog.answer_id, Document.id, Document.filename)
            .order_by(RetrievalLog.answer_id, first_rank, Document.id)
        )
        for answer_id, document_id, filename, _ in rows:
            documents[answer_id].append(
                EvaluationDocument(document_id=document_id, filename=filename))
    return documents


def _status(evaluation: Evaluation) -> EvaluationStatus | None:
    if evaluation.failure_type == EVALUATOR_ERROR:
        return "evaluator_error"
    if evaluation.passed is None:
        return None
    return "passed" if evaluation.passed else "failed"


def _load_items(
    db: Session, filters: EvaluationFilters, *, limit: int | None = None, offset: int = 0
) -> list[EvaluationListItem]:
    is_latest = (Evaluation.id == _LATEST.c.evaluation_id).label("is_latest")
    stmt = (
        _filtered(filters, Evaluation, Answer, StoredQuery, is_latest)
        .options(selectinload(Evaluation.claims))
        .order_by(Evaluation.id.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = db.execute(stmt).all()
    documents = _documents_by_answer(db, (answer.id for _, answer, _, _ in rows))
    return [
        EvaluationListItem(
            evaluation_id=evaluation.id,
            answer_id=answer.id,
            query_id=query.id,
            benchmark_run_id=query.benchmark_run_id,
            mode=query.mode,
            question=query.question,
            query_created_at=query.created_at,
            final_status=query.final_status,
            final_attempt_number=query.final_attempt_number,
            attempt_number=answer.attempt_number,
            strategy=answer.strategy,
            answer_status=answer.status,
            answer=answer.answer_text,
            status=_status(evaluation),
            passed=evaluation.passed,
            failure_type=evaluation.failure_type,
            faithfulness=evaluation.faithfulness,
            answer_relevance=evaluation.answer_relevance,
            context_relevance=evaluation.context_relevance,
            feedback=evaluation.feedback,
            model=evaluation.model,
            latency_ms=evaluation.latency_ms,
            input_tokens=evaluation.input_tokens,
            output_tokens=evaluation.output_tokens,
            is_latest=bool(latest),
            documents=documents.get(answer.id, []),
            claims=[
                ClaimRead(claim_text=claim.claim_text, verdict=claim.verdict,
                          evidence_chunk_id=claim.evidence_chunk_id,
                          evidence_quote=claim.evidence_quote)
                for claim in evaluation.claims
            ],
        )
        for evaluation, answer, query, latest in rows
    ]


def _csv_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _csv_row(item: EvaluationListItem) -> dict[str, Any]:
    verdicts = [claim.verdict for claim in item.claims]
    row = item.model_dump(exclude={"documents", "claims"})
    row.update(
        supported_claims=verdicts.count(SUPPORTED),
        partially_supported_claims=verdicts.count(PARTIALLY_SUPPORTED),
        unsupported_claims=verdicts.count(UNSUPPORTED),
        total_claims=len(verdicts),
        document_ids=";".join(str(document.document_id) for document in item.documents),
        documents="; ".join(document.filename for document in item.documents),
    )
    return {field: _csv_cell(row[field]) for field in CSV_FIELDS}


@router.get("", response_model=EvaluationPage)
def list_evaluations(
    filters: EvaluationFilters = Depends(evaluation_filters),
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Stored evaluations, newest first, with their query, attempt, claims, and documents."""
    total = db.scalar(_filtered(filters, func.count(Evaluation.id))) or 0
    items = _load_items(db, filters, limit=limit, offset=offset) if offset < total else []
    return EvaluationPage(total=total, limit=limit, offset=offset, items=items)


@router.get(
    "/export.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}},
                     "description": "Every evaluation matching the filters, newest first."}},
)
def export_evaluations(
    filters: EvaluationFilters = Depends(evaluation_filters),
    db: Session = Depends(get_db),
):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS)
    writer.writeheader()
    writer.writerows(_csv_row(item) for item in _load_items(db, filters))
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="evaluations.csv"'},
    )
