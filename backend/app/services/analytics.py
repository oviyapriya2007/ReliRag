from collections.abc import Mapping
from typing import Any

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.models import Answer, Claim, Document, DocumentChunk, Evaluation, Query, RetrievalLog
from app.schemas import (
    AnalyticsSummary,
    CorrectionSummary,
    DocumentUsage,
    LatencySummary,
    ModeBreakdown,
    ModeSummary,
    RateMetric,
    ScoreAverages,
)
from app.services.evaluator import EVALUATOR_ERROR, PARTIALLY_SUPPORTED, UNSUPPORTED
from app.services.similarity_gate import INSUFFICIENT_EVIDENCE

MODES = ("basic", "reli")
DEFAULT_TOP_DOCUMENTS = 5

# A usable evaluation produced scores; evaluator_error rows only record that evaluation failed.
_USABLE = and_(
    Evaluation.passed.is_not(None),
    or_(Evaluation.failure_type.is_(None), Evaluation.failure_type != EVALUATOR_ERROR),
)


def _rate(count: int, total: int) -> float | None:
    return count / total if total else None


def _float(value: Any) -> float | None:
    return None if value is None else float(value)


def _by_mode(db: Session, stmt: Select) -> dict[str, Any]:
    return {row[0]: row for row in db.execute(stmt)}


def build_summary(
    db: Session,
    *,
    benchmark_run_id: str | None = None,
    top_documents: int = DEFAULT_TOP_DOCUMENTS,
) -> AnalyticsSummary:
    """Aggregate stored queries, attempts, evaluations, and retrievals into one summary.

    Scope: every `queries` row, or only those with `benchmark_run_id`. Each attempt is judged
    by its latest evaluation (highest id); `evaluator_error` evaluations have no scores and are
    left out of pass rates and averages. A query's final attempt is `final_attempt_number`
    (RELI-RAG), else attempt 1 (Basic RAG). Rates are null when their denominator is 0.
    """
    scope_stmt = select(Query.id, Query.mode, Query.final_status, Query.final_attempt_number)
    if benchmark_run_id is not None:
        scope_stmt = scope_stmt.where(Query.benchmark_run_id == benchmark_run_id)
    scope = scope_stmt.subquery("scope")
    latest = (
        select(Evaluation.answer_id, func.max(Evaluation.id).label("evaluation_id"))
        .group_by(Evaluation.answer_id)
        .subquery("latest")
    )

    def evaluated_attempts(attempt_number):
        """One row per in-scope query whose given attempt has a usable latest evaluation."""
        return (
            select(scope.c.id.label("query_id"), scope.c.mode, scope.c.final_attempt_number,
                   Evaluation.passed, Evaluation.faithfulness, Evaluation.answer_relevance,
                   Evaluation.context_relevance)
            .select_from(scope)
            .join(Answer, Answer.query_id == scope.c.id)
            .join(latest, latest.c.answer_id == Answer.id)
            .join(Evaluation, Evaluation.id == latest.c.evaluation_id)
            .where(Answer.attempt_number == attempt_number, _USABLE)
            .subquery()
        )

    def score_stats(rows) -> dict[str, Any]:
        f, a, c = rows.c.faithfulness, rows.c.answer_relevance, rows.c.context_relevance
        return _by_mode(db, select(
            rows.c.mode,
            func.count().label("evaluations"),
            func.sum(case((rows.c.passed.is_(True), 1), else_=0)).label("passed"),
            func.sum(case((rows.c.passed.is_(False), 1), else_=0)).label("failed"),
            func.avg(f).label("faithfulness"),
            func.avg(a).label("answer_relevance"),
            func.avg(c).label("context_relevance"),
            func.avg((f + a + c) / 3.0).label("overall"),
        ).group_by(rows.c.mode))

    first = evaluated_attempts(1)
    final = evaluated_attempts(func.coalesce(scope.c.final_attempt_number, 1))
    first_stats = score_stats(first)
    final_stats = score_stats(final)

    questions = _by_mode(db, select(
        scope.c.mode,
        func.count().label("questions"),
        func.sum(case((scope.c.final_status == INSUFFICIENT_EVIDENCE, 1), else_=0))
        .label("insufficient_evidence"),
    ).group_by(scope.c.mode))

    claims = _by_mode(db, select(
        scope.c.mode,
        func.sum(case((Claim.verdict == UNSUPPORTED, 1), else_=0)).label("unsupported"),
        func.sum(case((Claim.verdict == PARTIALLY_SUPPORTED, 1), else_=0)).label("partial"),
    ).select_from(scope)
        .join(Answer, Answer.query_id == scope.c.id)
        .join(latest, latest.c.answer_id == Answer.id)
        .join(Claim, Claim.evaluation_id == latest.c.evaluation_id)
        .group_by(scope.c.mode))

    generation = (
        select(Answer.query_id, func.sum(Answer.latency_ms).label("ms"))
        .group_by(Answer.query_id)
        .subquery("generation")
    )
    evaluation = (
        select(Answer.query_id, func.sum(Evaluation.latency_ms).label("ms"))
        .select_from(Answer)
        .join(latest, latest.c.answer_id == Answer.id)
        .join(Evaluation, Evaluation.id == latest.c.evaluation_id)
        .group_by(Answer.query_id)
        .subquery("evaluation")
    )
    recorded = or_(generation.c.ms.is_not(None), evaluation.c.ms.is_not(None))
    total_ms = func.coalesce(generation.c.ms, 0) + func.coalesce(evaluation.c.ms, 0)
    latency = _by_mode(db, select(
        scope.c.mode,
        func.count(case((recorded, 1))).label("queries"),
        func.avg(generation.c.ms).label("generation_ms"),
        func.avg(evaluation.c.ms).label("evaluation_ms"),
        func.avg(case((recorded, total_ms))).label("total_ms"),
    ).select_from(scope)
        .outerjoin(generation, generation.c.query_id == scope.c.id)
        .outerjoin(evaluation, evaluation.c.query_id == scope.c.id)
        .group_by(scope.c.mode))

    by_mode = {
        mode: _mode_summary(mode, questions, first_stats, final_stats, claims, latency)
        for mode in MODES
    }

    triggered = db.scalar(
        select(func.count(func.distinct(Answer.query_id)))
        .select_from(scope)
        .join(Answer, Answer.query_id == scope.c.id)
        .where(scope.c.mode == "reli", Answer.attempt_number == 2)
    ) or 0
    successful = db.scalar(
        select(func.count())
        .select_from(final)
        .where(final.c.mode == "reli", final.c.final_attempt_number == 2,
               final.c.passed.is_(True))
    ) or 0
    reli_first = first_stats.get("reli")
    eligible = int(reli_first.failed or 0) if reli_first else 0

    retrievals = func.count(RetrievalLog.id).label("retrievals")
    documents = db.execute(
        select(Document.id.label("document_id"), Document.filename, retrievals,
               func.count(func.distinct(Answer.query_id)).label("queries"))
        .select_from(RetrievalLog)
        .join(Answer, Answer.id == RetrievalLog.answer_id)
        .join(scope, scope.c.id == Answer.query_id)
        .join(DocumentChunk, DocumentChunk.id == RetrievalLog.chunk_id)
        .join(Document, Document.id == DocumentChunk.document_id)
        .group_by(Document.id, Document.filename)
        .order_by(retrievals.desc(), Document.id)
        .limit(top_documents)
    ).all()

    first_pass_count = sum(by_mode[mode].first_pass.count for mode in MODES)
    first_pass_total = sum(by_mode[mode].first_pass.total for mode in MODES)
    return AnalyticsSummary(
        benchmark_run_id=benchmark_run_id,
        total_questions=sum(by_mode[mode].questions for mode in MODES),
        first_pass=RateMetric(count=first_pass_count, total=first_pass_total,
                              rate=_rate(first_pass_count, first_pass_total)),
        corrections=CorrectionSummary(
            eligible=eligible,
            triggered=triggered,
            successful=successful,
            failed_after_correction=triggered - successful,
            trigger_rate=_rate(triggered, eligible),
            success_rate=_rate(successful, triggered),
        ),
        insufficient_evidence=sum(by_mode[mode].insufficient_evidence for mode in MODES),
        unsupported_claims=sum(by_mode[mode].unsupported_claims for mode in MODES),
        by_mode=ModeBreakdown(**by_mode),
        top_documents=[
            DocumentUsage(document_id=row.document_id, filename=row.filename,
                          retrievals=row.retrievals, queries=row.queries)
            for row in documents
        ],
    )


def _scores(row) -> ScoreAverages:
    if row is None:
        return ScoreAverages(evaluations=0, faithfulness=None, answer_relevance=None,
                             context_relevance=None, overall=None)
    return ScoreAverages(evaluations=row.evaluations, faithfulness=_float(row.faithfulness),
                         answer_relevance=_float(row.answer_relevance),
                         context_relevance=_float(row.context_relevance),
                         overall=_float(row.overall))


def _mode_summary(
    mode: str,
    questions: Mapping[str, Any],
    first_stats: Mapping[str, Any],
    final_stats: Mapping[str, Any],
    claims: Mapping[str, Any],
    latency: Mapping[str, Any],
) -> ModeSummary:
    question_row = questions.get(mode)
    first_row = first_stats.get(mode)
    claim_row = claims.get(mode)
    latency_row = latency.get(mode)
    evaluated = first_row.evaluations if first_row else 0
    passed = int(first_row.passed or 0) if first_row else 0
    return ModeSummary(
        questions=question_row.questions if question_row else 0,
        first_pass=RateMetric(count=passed, total=evaluated, rate=_rate(passed, evaluated)),
        insufficient_evidence=int(question_row.insufficient_evidence or 0) if question_row else 0,
        first_attempt_scores=_scores(first_row),
        final_scores=_scores(final_stats.get(mode)),
        unsupported_claims=int(claim_row.unsupported or 0) if claim_row else 0,
        partially_supported_claims=int(claim_row.partial or 0) if claim_row else 0,
        latency=LatencySummary(
            queries=latency_row.queries if latency_row else 0,
            avg_generation_ms=_float(latency_row.generation_ms) if latency_row else None,
            avg_evaluation_ms=_float(latency_row.evaluation_ms) if latency_row else None,
            avg_total_ms=_float(latency_row.total_ms) if latency_row else None,
        ),
    )
