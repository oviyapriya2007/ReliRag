import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.models import Query
from app.services.llm import LLMError
from app.services.query_pipeline import (
    ERROR,
    create_query,
    execute_basic_query,
    execute_reli_rag,
)
from app.services.retrieval import DEFAULT_TOP_K, RetrievedChunk, retrieve

logger = logging.getLogger(__name__)

BRANCHES: dict[str, Callable[..., Query]] = {
    "basic": execute_basic_query,
    "reli": execute_reli_rag,
}


@dataclass(frozen=True)
class CompareResult:
    compare_id: str
    query_ids: dict[str, int]
    errors: dict[str, str]


def run_compare(
    db: Session,
    question: str,
    *,
    k: int = DEFAULT_TOP_K,
    document_ids: Sequence[int] | None = None,
    benchmark_run_id: str | None = None,
) -> CompareResult:
    """Answer `question` with Basic RAG and RELI-RAG from one shared retrieval.

    Retrieves once, creates one `queries` row per mode (linked by `options["compare_id"]`,
    and tagged with `benchmark_run_id` if given), then runs both pipelines concurrently,
    each in its own session, so each branch gates, generates, and evaluates independently
    from the same chunks. A branch that raises is logged, its query is marked ERROR if the
    pipeline did not already decide its status, and its error is returned in `errors`; the
    other branch is unaffected.
    """
    chunks = retrieve(db, question, k=k, document_ids=document_ids)
    compare_id = uuid4().hex
    extra_options = {"compare_id": compare_id, "shared_retrieval": True}
    query_ids = {
        mode: create_query(db, question, mode=mode, k=k, document_ids=document_ids,
                           extra_options=extra_options, benchmark_run_id=benchmark_run_id).id
        for mode in BRANCHES
    }

    make_session = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    with ThreadPoolExecutor(max_workers=len(BRANCHES)) as pool:
        futures = {
            mode: pool.submit(_run_branch, make_session, execute, query_ids[mode], chunks)
            for mode, execute in BRANCHES.items()
        }
        errors = {mode: error for mode, future in futures.items()
                  if (error := future.result()) is not None}
    return CompareResult(compare_id=compare_id, query_ids=query_ids, errors=errors)


def _run_branch(
    make_session: Callable[[], Session],
    execute: Callable[..., Query],
    query_id: int,
    chunks: Sequence[RetrievedChunk],
) -> str | None:
    """Run one pipeline in its own session; the error message if it raised, else None."""
    with make_session() as db:
        try:
            execute(db, db.get(Query, query_id), chunks=chunks)
            return None
        except Exception as exc:
            if isinstance(exc, LLMError):
                logger.warning("Compare branch Claude call failed for query_id=%s: %s",
                               query_id, exc)
            else:
                logger.exception("Compare branch failed for query_id=%s", query_id)
            try:
                db.rollback()
                query = db.get(Query, query_id)
                if query is not None and query.final_status is None:
                    query.final_status = ERROR
                    db.commit()
            except Exception:
                db.rollback()
                logger.exception("Could not mark compare branch query_id=%s as ERROR", query_id)
            return str(exc) or type(exc).__name__
