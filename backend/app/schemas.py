from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.services.retrieval import DEFAULT_TOP_K, MAX_TOP_K


class HealthResponse(BaseModel):
    status: str


class DocumentUploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    total_pages: int | None
    total_chunks: int | None


class DocumentRead(DocumentUploadResponse):
    uploaded_at: datetime


class DocumentDeleteResponse(BaseModel):
    id: int
    filename: str
    deleted: bool
    message: str


class QueryRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    mode: Literal["basic"] = "basic"
    k: int = Field(default=DEFAULT_TOP_K, ge=1, le=MAX_TOP_K)
    document_ids: list[int] | None = None


class RetrievalResult(BaseModel):
    rank: int
    chunk_id: int
    document_id: int
    filename: str
    page_number: int | None
    chunk_index: int
    similarity: float | None
    content: str


class ClaimRead(BaseModel):
    claim_text: str
    verdict: str | None
    evidence_chunk_id: int | None
    evidence_quote: str | None


class EvaluationRead(BaseModel):
    faithfulness: float | None
    answer_relevance: float | None
    context_relevance: float | None
    passed: bool | None
    failure_type: str | None
    feedback: str | None
    claims: list[ClaimRead]


class AttemptTimings(BaseModel):
    retrieve_ms: int | None = None
    generate_ms: int | None = None
    evaluate_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class QueryAttempt(BaseModel):
    attempt_number: int
    answer: str | None
    retrieval_query: str | None
    status: str | None
    model: str | None
    citations: list[int]
    retrieval: list[RetrievalResult]
    evaluation: EvaluationRead | None
    timings: AttemptTimings


class QueryResponse(BaseModel):
    query_id: int
    question: str
    mode: str
    created_at: datetime
    status: str | None
    final_answer: str | None
    attempts: list[QueryAttempt]
