import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Answer, Claim, Evaluation, Query, RetrievalLog
from app.services.attempt_selection import AttemptEvaluation, AttemptSummary, select_final_attempt
from app.services.corrector import (
    RETRY_TOP_K,
    REWRITE,
    STRICT,
    RewriteResult,
    carry_over_chunks,
    choose_correction,
    claims_to_reject,
    describe_failures,
    failure_signals,
    retry_top_k,
    rewrite_query,
)
from app.services.evaluator import EVALUATOR_ERROR, EvaluationResult, evaluate_answer
from app.services.generator import (
    ANSWERED,
    GenerationResult,
    build_correction_instructions,
    build_strict_instructions,
    generate_answer,
)
from app.services.llm import LLMError
from app.services.retrieval import DEFAULT_TOP_K, RetrievedChunk, load_logged_chunks
from app.services.similarity_gate import retrieve_with_gate

logger = logging.getLogger(__name__)

ERROR = "ERROR"


@dataclass(frozen=True)
class AttemptResult:
    answer: Answer
    chunks: list[RetrievedChunk]
    rewrite: RewriteResult | None = None


def create_query(
    db: Session,
    question: str,
    *,
    mode: str,
    k: int = DEFAULT_TOP_K,
    document_ids: Sequence[int] | None = None,
    extra_options: Mapping[str, Any] | None = None,
    benchmark_run_id: str | None = None,
) -> Query:
    """Insert and commit the `queries` row for one run; its options record the run settings.

    The `execute_*` functions read k, document_ids, and the similarity gate back from these
    options. `extra_options` are merged in, e.g. to link the queries of one comparison.
    `benchmark_run_id` tags the row as part of one benchmark run.
    """
    options: dict[str, Any] = {"k": k}
    if mode == "reli":
        options["retry_k"] = retry_top_k(k)
    options["document_ids"] = list(document_ids) if document_ids is not None else None
    options["similarity_gate"] = settings.similarity_gate
    options.update(extra_options or {})
    query = Query(question=question, mode=mode, options=options,
                  benchmark_run_id=benchmark_run_id)
    db.add(query)
    db.commit()
    return query


def _run_settings(query: Query) -> tuple[int, list[int] | None, float]:
    options = query.options
    return options["k"], options["document_ids"], options["similarity_gate"]


def _retry_k(query: Query) -> int:
    """The REWRITE retry size recorded for `query`, never below its `k`."""
    options = query.options
    return max(options["k"], options.get("retry_k") or retry_top_k(options["k"]))


def run_basic_query(
    db: Session,
    question: str,
    *,
    k: int = DEFAULT_TOP_K,
    document_ids: Sequence[int] | None = None,
    chunks: Sequence[RetrievedChunk] | None = None,
) -> Query:
    """Run basic RAG for one question: retrieve + gate (A2), generate (A4), then evaluate.

    Every step is persisted. If the gate fails, Claude is not called. If the Claude call
    fails, the attempt and query are marked ERROR and the `LLMError` is re-raised; any other
    failure (e.g. in retrieval) also marks the query ERROR and is re-raised.
    An ANSWERED attempt is evaluated after it is committed; evaluation never changes the
    answer or its status, and evaluation failures are saved as `evaluator_error`.
    `chunks`, if given, replace the retrieval (see `execute_basic_query`).
    """
    query = create_query(db, question, mode="basic", k=k, document_ids=document_ids)
    return execute_basic_query(db, query, chunks=chunks)


def execute_basic_query(
    db: Session, query: Query, *, chunks: Sequence[RetrievedChunk] | None = None
) -> Query:
    """Run basic RAG (see `run_basic_query`) for a `query` made by `create_query`.

    `chunks`, if given, are an already retrieved result for `query.question`, used instead
    of retrieving again; they are still gated and logged.
    """
    query_id = query.id
    k, document_ids, threshold = _run_settings(query)
    try:
        attempt = run_attempt(
            db, query, attempt_number=1, k=k, document_ids=document_ids, threshold=threshold,
            chunks=chunks,
        )
    except Exception:
        record_failure(db, query_id)
        raise
    set_final_attempt(db, query, 1, attempt.answer.status)

    if attempt.answer.status == ANSWERED:
        save_evaluation(
            db, attempt.answer,
            run_evaluation(query.question, attempt.answer.answer_text, attempt.chunks),
        )
    return query


def run_reli_rag(
    db: Session,
    question: str,
    *,
    k: int = DEFAULT_TOP_K,
    document_ids: Sequence[int] | None = None,
    chunks: Sequence[RetrievedChunk] | None = None,
) -> Query:
    """Run RELI-RAG: attempt 1 as in basic mode, then at most one corrective attempt.

    Attempt 1 is retrieved, gated, generated, and evaluated as in `run_basic_query` and is
    committed as the final attempt before any correction starts. Any failure on attempt 1
    marks the query ERROR and is re-raised (an `LLMError` for a Claude failure). Gate
    rejections, refusals, passing evaluations, and `evaluator_error` are not retried.

    Otherwise `choose_correction` picks one retry from all of the evaluation's failure
    signals: REWRITE (rewrite the question from the evaluator feedback, retrieve again with
    the retry size, keep attempt 1's verified evidence, and avoid any rejected claims) or
    STRICT (regenerate from the same chunks, listing the rejected claims). Attempt 2 is
    evaluated on its own and `select_final_attempt` decides which attempt the query reports.
    Only saved evaluations count, so the stored record always explains the choice. A failure
    during attempt 2 is logged, marks attempt 2 ERROR if its row was left without a status,
    and leaves attempt 1 as the final attempt.
    `chunks`, if given, replace attempt 1's retrieval (see `execute_reli_rag`).
    """
    query = create_query(db, question, mode="reli", k=k, document_ids=document_ids)
    return execute_reli_rag(db, query, chunks=chunks)


def execute_reli_rag(
    db: Session, query: Query, *, chunks: Sequence[RetrievedChunk] | None = None
) -> Query:
    """Run RELI-RAG (see `run_reli_rag`) for a `query` made by `create_query`.

    `chunks`, if given, are an already retrieved result for `query.question`, used as
    attempt 1's retrieval instead of retrieving again; they are still gated and logged.
    A REWRITE correction always retrieves again.
    """
    k, document_ids, threshold = _run_settings(query)
    question = query.question
    query_id = query.id

    try:
        first = run_attempt(
            db, query, attempt_number=1, k=k, document_ids=document_ids, threshold=threshold,
            chunks=chunks,
        )
    except Exception:
        record_failure(db, query_id)
        raise
    set_final_attempt(db, query, 1, first.answer.status)
    if first.answer.status != ANSWERED:
        return query

    first_evaluation = evaluate_and_save(db, question, first)
    strategy = choose_correction(first_evaluation)
    if strategy is None:
        return query

    attempts = [summarize_attempt(first.answer, first_evaluation)]
    try:
        if strategy == STRICT:
            second = run_strict_attempt(
                db, first.answer, attempt_number=2,
                rejected_claims=claims_to_reject(first_evaluation),
            )
        else:
            second = run_rewrite_attempt(
                db, query, attempt_number=2, feedback=first_evaluation.feedback,
                failure_type=failure_signals(first_evaluation),
                k=_retry_k(query), document_ids=document_ids, threshold=threshold,
                carry_over=carry_over_chunks(first.chunks, first_evaluation),
                rejected_claims=claims_to_reject(first_evaluation),
            )
        second_evaluation = None
        if second.answer.status == ANSWERED:
            second_evaluation = evaluate_and_save(db, question, second)
        attempts.append(summarize_attempt(second.answer, second_evaluation))
    except LLMError as exc:
        logger.warning("Correction attempt Claude call failed for query_id=%s: %s", query_id, exc)
    except Exception:
        db.rollback()
        logger.exception("Correction attempt failed for query_id=%s", query_id)
        _mark_unfinished_attempt_error(db, query_id, 2)

    final = select_final_attempt(attempts)
    set_final_attempt(db, query, final.attempt_number, final.status)
    return query


def evaluate_and_save(
    db: Session, question: str, attempt: AttemptResult
) -> EvaluationResult | None:
    """Evaluate an ANSWERED attempt and save it; the result, or None if it could not be saved."""
    result = run_evaluation(question, attempt.answer.answer_text, attempt.chunks)
    return result if save_evaluation(db, attempt.answer, result) is not None else None


def summarize_attempt(
    answer: Answer, evaluation: EvaluationResult | Evaluation | None
) -> AttemptSummary:
    """Selection view of an attempt and its fresh or stored evaluation."""
    scores = None
    if evaluation is not None:
        scores = AttemptEvaluation(
            passed=evaluation.passed,
            failure_type=evaluation.failure_type,
            faithfulness=evaluation.faithfulness,
            answer_relevance=evaluation.answer_relevance,
            context_relevance=evaluation.context_relevance,
        )
    return AttemptSummary(attempt_number=answer.attempt_number, status=answer.status,
                          evaluation=scores)


def set_final_attempt(db: Session, query: Query, attempt_number: int, status: str | None) -> None:
    """Record which attempt the query reports, and its status, and commit."""
    query.final_attempt_number = attempt_number
    query.final_status = status
    db.commit()


def record_failure(db: Session, query_id: int) -> None:
    """Mark a query whose run raised as ERROR, unless it already has a final status.

    Attempt 1 becomes the final attempt if its row exists. `db` is rolled back first; if it
    still cannot be used, a new session on the same connection is used instead. Never
    raises, so the caller re-raises the original exception.
    """
    try:
        db.rollback()
        _mark_error(db, query_id)
        return
    except Exception:
        logger.exception("Could not mark query_id=%s as ERROR; retrying in a new session",
                         query_id)
        try:
            db.rollback()
        except Exception:
            logger.exception("Rollback failed for query_id=%s", query_id)
    try:
        with Session(bind=db.get_bind(), autoflush=False, expire_on_commit=False) as fresh:
            _mark_error(fresh, query_id)
    except Exception:
        logger.exception("Could not mark query_id=%s as ERROR", query_id)


def _mark_unfinished_attempt_error(db: Session, query_id: int, attempt_number: int) -> None:
    """Mark the attempt ERROR if a failure left its row without a status; never raises."""
    try:
        answer = db.scalar(select(Answer).where(Answer.query_id == query_id,
                                                Answer.attempt_number == attempt_number))
        if answer is not None and answer.status is None:
            answer.status = ERROR
            db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not mark attempt %s of query_id=%s as ERROR",
                         attempt_number, query_id)


def _mark_error(db: Session, query_id: int) -> None:
    query = db.get(Query, query_id)
    if query is None or query.final_status is not None:
        return
    first = db.scalar(select(Answer.attempt_number)
                      .where(Answer.query_id == query_id, Answer.attempt_number == 1))
    query.final_status = ERROR
    query.final_attempt_number = first
    db.commit()


def run_attempt(
    db: Session,
    query: Query,
    *,
    attempt_number: int,
    retrieval_query: str | None = None,
    k: int = DEFAULT_TOP_K,
    document_ids: Sequence[int] | None = None,
    threshold: float | None = None,
    strategy: str | None = None,
    chunks: Sequence[RetrievedChunk] | None = None,
    carry_over: Sequence[RetrievedChunk] = (),
    strict_instructions: str | None = None,
) -> AttemptResult:
    """Retrieve, gate, and generate one answer attempt for `query.question`.

    Writes only this attempt's `answers` and `retrieval_log` rows and never changes
    `query.final_status`, so a failing later attempt cannot overwrite an earlier result.
    If the gate fails, Claude is not called and the attempt is INSUFFICIENT_EVIDENCE.
    If the Claude call fails, the attempt is marked ERROR and the `LLMError` is re-raised.
    `chunks`, if given, are used instead of retrieving, and `carry_over` chunks from an
    earlier attempt are merged in after the gate (see `retrieve_with_gate`). The answer is
    generated from exactly the logged chunks, with `strict_instructions` if given.
    """
    gate = retrieve_with_gate(
        db, query, retrieval_query=retrieval_query, attempt_number=attempt_number,
        k=k, document_ids=document_ids, threshold=threshold, strategy=strategy, chunks=chunks,
        carry_over=carry_over,
    )
    answer = db.get(Answer, gate.answer_id)
    if gate.passed:
        generate_into(db, answer, query.question, gate.chunks,
                      strict_instructions=strict_instructions)
    return AttemptResult(answer=answer, chunks=gate.chunks)


def run_rewrite_attempt(
    db: Session,
    query: Query,
    *,
    attempt_number: int,
    feedback: str | None,
    failure_type: str | Sequence[str] | None,
    k: int = RETRY_TOP_K,
    document_ids: Sequence[int] | None = None,
    threshold: float | None = None,
    carry_over: Sequence[RetrievedChunk] = (),
    rejected_claims: Sequence[str] = (),
) -> AttemptResult:
    """Rewrite the question from evaluator feedback, then retrieve again and generate.

    The rewritten query is used only for retrieval (it is saved as the attempt's
    `retrieval_query`); the answer is still generated for `query.question`. A rejected
    rewrite falls back to the original question, retrieved with the larger `k`.
    `failure_type` is one failure type or all of the evaluation's failure signals.
    `carry_over` (attempt 1's chunks to keep, see `carry_over_chunks`) is merged with the new
    retrieval once it passes the gate. The answer is generated with correction instructions
    naming the problems and the evaluator `feedback` (see `build_correction_instructions`),
    preceded by strict instructions listing `rejected_claims`, if any.
    Same guarantees as `run_attempt`: earlier attempts and `query.final_status` are untouched.
    """
    rewrite = rewrite_query(query.question, feedback, failure_type=failure_type)
    instructions = [build_correction_instructions(describe_failures(failure_type), feedback)]
    if rejected_claims:
        instructions.insert(0, build_strict_instructions(rejected_claims))
    attempt = run_attempt(
        db, query, attempt_number=attempt_number, retrieval_query=rewrite.query,
        k=k, document_ids=document_ids, threshold=threshold, strategy=REWRITE,
        carry_over=carry_over, strict_instructions="\n\n".join(instructions),
    )
    return replace(attempt, rewrite=rewrite)


def run_strict_attempt(
    db: Session,
    source: Answer,
    *,
    attempt_number: int,
    rejected_claims: Sequence[str],
) -> AttemptResult:
    """Regenerate `source`'s answer in strict mode from the same chunks, as a new attempt.

    Does not retrieve again: the new attempt reuses `source`'s logged chunks (see
    `create_attempt_with_same_chunks`), and the strict instructions list `rejected_claims`.
    If the Claude call fails, the new attempt is marked ERROR and the `LLMError` is re-raised.
    """
    attempt = create_attempt_with_same_chunks(
        db, source, attempt_number=attempt_number, strategy=STRICT
    )
    generate_into(db, attempt.answer, source.query.question, attempt.chunks,
                  strict_instructions=build_strict_instructions(rejected_claims))
    return attempt


def create_attempt_with_same_chunks(
    db: Session, source: Answer, *, attempt_number: int, strategy: str | None = None
) -> AttemptResult:
    """Create attempt `attempt_number` for `source`'s query, reusing `source`'s chunks.

    Copies `source`'s `retrieval_log` rows (chunk, rank order, similarity) and its
    `retrieval_query` onto the new attempt without retrieving again. `source`, its logs and
    its evaluations are not modified. Raises `ValueError` if `source` has no logged chunks.
    """
    chunks = load_logged_chunks(db, source.id)
    if not chunks:
        raise ValueError(f"answer {source.id} has no logged chunks to reuse")

    try:
        answer = Answer(
            query=source.query,
            attempt_number=attempt_number,
            retrieval_query=source.retrieval_query,
            strategy=strategy,
            status=None,
        )
        db.add(answer)
        db.flush()
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
    return AttemptResult(answer=answer, chunks=chunks)


def generate_into(
    db: Session,
    answer: Answer,
    question: str,
    chunks: Sequence[RetrievedChunk],
    *,
    strict_instructions: str | None = None,
) -> None:
    """Generate an answer from `chunks` and save it on `answer`'s row.

    If generation raises (an `LLMError` or anything unexpected), the attempt is marked ERROR
    and the exception is re-raised.
    """
    try:
        result = generate_answer(question, chunks, strict_instructions=strict_instructions)
    except Exception:
        answer.status = ERROR
        db.commit()
        raise
    save_generation(db, answer, result)


def save_generation(db: Session, answer: Answer, result: GenerationResult) -> None:
    """Copy a generation result onto its `answers` row and commit; the query is not touched."""
    answer.answer_text = result.answer
    answer.status = result.status
    if result.llm is not None:
        answer.model = result.llm.model
        answer.latency_ms = result.llm.latency_ms
        answer.input_tokens = result.llm.input_tokens
        answer.output_tokens = result.llm.output_tokens
    db.commit()


def run_evaluation(
    question: str, answer: str | None, chunks: Sequence[RetrievedChunk]
) -> EvaluationResult:
    """Evaluate an answer, turning any exception into an `evaluator_error` result."""
    try:
        return evaluate_answer(
            question, answer or "", chunks, threshold=settings.evaluator_pass_threshold
        )
    except Exception as exc:
        logger.warning("Evaluator raised: %r", exc)
        return EvaluationResult(
            faithfulness=None, answer_relevance=None, context_relevance=None,
            passed=False, failure_type=EVALUATOR_ERROR, feedback=f"Evaluation failed: {exc}",
            claims=[], model=None, input_tokens=0, output_tokens=0, latency_ms=0, llm_calls=0,
        )


def save_evaluation(db: Session, answer: Answer, result: EvaluationResult) -> Evaluation | None:
    """Insert one `evaluations` row with its `claims` and commit.

    Claims keep the evaluator's final (verified) verdicts and real chunk IDs, with Claude's
    original verdict, the reason a check changed it, and which check (`check_name`). A failure
    is rolled back and logged, leaving the committed answer untouched.
    """
    answer_id = answer.id
    try:
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
                    claude_verdict=claim.claude_verdict,
                    evidence_error=claim.evidence_error,
                    check_name=claim.check,
                )
                for claim in result.claims
            ],
        )
        db.add(evaluation)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to save evaluation for answer_id=%s", answer_id)
        return None
    return evaluation
