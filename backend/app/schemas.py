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
    mode: Literal["basic", "reli"] = "basic"
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


ClaimCheckName = Literal["evidence", "support", "citation", "uncited", "limitation"]


class ClaimRead(BaseModel):
    claim_text: str
    verdict: str | None
    evidence_chunk_id: int | None
    evidence_quote: str | None
    claude_verdict: str | None = Field(
        default=None, description="Claude's verdict before the deterministic checks; null for a "
                                  "claim a check added, and for claims saved before this was "
                                  "recorded.")
    evidence_error: str | None = Field(
        default=None, description="Why a check changed the claim's verdict, if one did.")
    check_name: ClaimCheckName | None = Field(
        default=None, description="Which check changed the claim's verdict, if one did.")


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
    strategy: str | None = None
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
    final_attempt_number: int | None = None
    selection_reason: str | None = Field(
        default=None,
        description="Why `final_attempt_number` is the reported attempt, derived from the recorded "
                    "attempts with the attempt-selection rules; null when no final attempt is "
                    "recorded.")
    attempts: list[QueryAttempt]


BenchmarkRunId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64,
                           pattern=r"^[A-Za-z0-9._:-]+$")
]


class CompareRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    k: int = Field(default=DEFAULT_TOP_K, ge=1, le=MAX_TOP_K)
    document_ids: list[int] | None = None
    benchmark_run_id: BenchmarkRunId | None = Field(
        default=None, description="Stored on both queries so analytics can filter one benchmark run.")


class CompareResponse(BaseModel):
    compare_id: str
    benchmark_run_id: str | None = None
    question: str
    basic: QueryResponse
    reli: QueryResponse


class RateMetric(BaseModel):
    count: int
    total: int = Field(description="Denominator of `rate`.")
    rate: float | None = Field(description="count / total, or null when total is 0.")


class ScoreAverages(BaseModel):
    evaluations: int = Field(description="Usable evaluations averaged (not evaluator_error).")
    faithfulness: float | None
    answer_relevance: float | None
    context_relevance: float | None
    overall: float | None = Field(description="Average of each evaluation's mean of the three scores.")


class LatencySummary(BaseModel):
    queries: int = Field(description="Queries with any recorded Claude latency, the denominator of "
                                     "all three averages; gate rejections without a Claude call "
                                     "are excluded. A part with no recorded time counts as 0 ms, "
                                     "so avg_generation_ms + avg_evaluation_ms = avg_total_ms.")
    avg_generation_ms: float | None = Field(
        description="Per query, the summed answer-generation latency of all attempts.")
    avg_evaluation_ms: float | None = Field(
        description="Per query, the summed latency of each attempt's latest evaluation.")
    avg_total_ms: float | None = Field(
        description="Per query, generation plus evaluation latency. Retrieval and query rewriting "
                    "are not recorded and not included.")


class ModeSummary(BaseModel):
    questions: int
    first_pass: RateMetric = Field(
        description="Attempt 1 passed its latest evaluation, out of queries whose attempt 1 has a "
                    "usable evaluation.")
    final_pass: RateMetric = Field(
        description="The reported attempt (final_attempt_number) passed its latest evaluation, out "
                    "of queries whose reported attempt has a usable evaluation.")
    insufficient_evidence: int = Field(description="Queries whose final status is INSUFFICIENT_EVIDENCE.")
    first_attempt_scores: ScoreAverages
    final_scores: ScoreAverages = Field(description="Scores of the attempt each query reports.")
    unsupported_claims: int = Field(description="Unsupported claims in the latest evaluation of every attempt.")
    partially_supported_claims: int
    latency: LatencySummary


class ModeBreakdown(BaseModel):
    basic: ModeSummary
    reli: ModeSummary


class CorrectionSummary(BaseModel):
    eligible: int = Field(description="RELI-RAG queries whose attempt 1 failed a usable evaluation.")
    triggered: int = Field(description="RELI-RAG queries with a stored attempt 2.")
    successful: int = Field(description="Triggered corrections whose reported attempt is attempt 2 "
                                        "and passed its evaluation.")
    failed_after_correction: int = Field(description="triggered - successful.")
    trigger_rate: float | None = Field(description="triggered / eligible, or null.")
    success_rate: float | None = Field(description="successful / triggered, or null.")


class DocumentUsage(BaseModel):
    document_id: int
    filename: str
    retrievals: int = Field(description="retrieval_log rows (chunks retrieved for any attempt).")
    queries: int = Field(description="Distinct queries that retrieved a chunk of the document.")


class AnalyticsSummary(BaseModel):
    benchmark_run_id: str | None
    total_questions: int = Field(description="`queries` rows in scope; a /compare call adds one per mode.")
    first_pass: RateMetric = Field(description="Both modes combined; see ModeSummary.first_pass.")
    corrections: CorrectionSummary
    insufficient_evidence: int
    unsupported_claims: int
    by_mode: ModeBreakdown
    top_documents: list[DocumentUsage] = Field(description="Most retrieved documents, most first.")
