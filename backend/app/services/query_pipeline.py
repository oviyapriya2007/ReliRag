from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Answer, Query
from app.services.generator import generate_answer
from app.services.llm import LLMError
from app.services.retrieval import DEFAULT_TOP_K
from app.services.similarity_gate import retrieve_with_gate

ERROR = "ERROR"


def run_basic_query(
    db: Session,
    question: str,
    *,
    k: int = DEFAULT_TOP_K,
    document_ids: Sequence[int] | None = None,
) -> Query:
    """Run basic RAG for one question: retrieve + gate (A2), then generate (A4) as attempt 1.

    Every step is persisted. If the gate fails, Claude is not called. If the Claude call
    fails, the attempt and query are marked ERROR and the `LLMError` is re-raised.
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
    return query
