import logging
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Answer, Claim, Evaluation, Query
from app.services.evaluator import EVALUATOR_ERROR, EvaluationResult, evaluate_answer
from app.services.generator import ANSWERED, generate_answer
from app.services.llm import LLMError
from app.services.retrieval import DEFAULT_TOP_K, RetrievedChunk
from app.services.similarity_gate import retrieve_with_gate

logger = logging.getLogger(__name__)

ERROR = "ERROR"


def run_basic_query(
    db: Session,
    question: str,
    *,
    k: int = DEFAULT_TOP_K,
    document_ids: Sequence[int] | None = None,
) -> Query:
    """Run basic RAG for one question: retrieve + gate (A2), generate (A4), then evaluate.

    Every step is persisted. If the gate fails, Claude is not called. If the Claude call
    fails, the attempt and query are marked ERROR and the `LLMError` is re-raised.
    An ANSWERED attempt is evaluated after it is committed; evaluation never changes the
    answer or its status, and evaluation failures are saved as `evaluator_error`.
    """
    threshold = settings.similarity_gate
    query = Query(
        question=question,
        mode="basic",
        options={
            "k": k,
            "document_ids": list(document_ids) if document_ids is not None else None,
            "similarity_gate": threshold,
        },
    )
    db.add(query)
    db.commit()

    gate = retrieve_with_gate(
        db, query, k=k, document_ids=document_ids, threshold=threshold, attempt_number=1
    )
    if not gate.passed:
        return query

    answer = db.get(Answer, gate.answer_id)
    try:
        result = generate_answer(question, gate.chunks)
    except LLMError:
        answer.status = ERROR
        query.final_status = ERROR
        db.commit()
        raise

    answer.answer_text = result.answer
    answer.status = result.status
    if result.llm is not None:
        answer.model = result.llm.model
        answer.latency_ms = result.llm.latency_ms
        answer.input_tokens = result.llm.input_tokens
        answer.output_tokens = result.llm.output_tokens
    query.final_status = result.status
    db.commit()

    if result.status == ANSWERED:
        save_evaluation(db, answer, run_evaluation(question, result.answer, gate.chunks))
    return query


def run_evaluation(
    question: str, answer: str | None, chunks: Sequence[RetrievedChunk]
) -> EvaluationResult:
    """Evaluate an answer, turning any exception into an `evaluator_error` result."""
    try:
        return evaluate_answer(question, answer or "", chunks)
    except Exception as exc:
        logger.warning("Evaluator raised: %r", exc)
        return EvaluationResult(
            faithfulness=None, answer_relevance=None, context_relevance=None,
            passed=False, failure_type=EVALUATOR_ERROR, feedback=f"Evaluation failed: {exc}",
            claims=[], model=None, input_tokens=0, output_tokens=0, latency_ms=0, llm_calls=0,
        )


def save_evaluation(db: Session, answer: Answer, result: EvaluationResult) -> Evaluation | None:
    """Insert one `evaluations` row with its `claims` and commit.

    Claims keep the evaluator's final (verified) verdicts and real chunk IDs. A database
    failure is rolled back and logged, leaving the committed answer untouched.
    """
    answer_id = answer.id
    evaluation = Evaluation(
        answer=answer,
        faithfulness=result.faithfulness,
        answer_relevance=result.answer_relevance,
        context_relevance=result.context_relevance,
        passed=result.passed,
        failure_type=result.failure_type,
        feedback=result.feedback,
        model=result.model,
        latency_ms=result.latency_ms,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        claims=[
            Claim(
                claim_text=claim.claim_text,
                verdict=claim.verdict,
                evidence_chunk_id=claim.evidence_chunk_id,
                evidence_quote=claim.evidence_quote,
            )
            for claim in result.claims
        ],
    )
    try:
        db.add(evaluation)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to save evaluation for answer_id=%s", answer_id)
        return None
    return evaluation
