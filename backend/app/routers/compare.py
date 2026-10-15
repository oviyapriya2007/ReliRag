from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.query import _load_query, _to_response
from app.schemas import CompareRequest, CompareResponse
from app.services.compare import run_compare

router = APIRouter(prefix="/compare", tags=["compare"])


# Sync handler on purpose: retrieval blocks, and the branches run in their own worker threads.
@router.post("", response_model=CompareResponse)
def compare_answers(request: CompareRequest, db: Session = Depends(get_db)):
    """Answer one question with Basic RAG and RELI-RAG from a shared first retrieval.

    Returns 200 when at least one branch finished; a failed branch reports status ERROR.
    Returns 502 when both branches failed.
    """
    result = run_compare(db, request.question, k=request.k, document_ids=request.document_ids,
                         benchmark_run_id=request.benchmark_run_id)
    if len(result.errors) == len(result.query_ids):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Both comparison branches failed: "
            + "; ".join(f"{mode}: {error}" for mode, error in result.errors.items()),
        )
    return CompareResponse(
        compare_id=result.compare_id,
        benchmark_run_id=request.benchmark_run_id,
        question=request.question,
        basic=_to_response(_load_query(db, result.query_ids["basic"])),
        reli=_to_response(_load_query(db, result.query_ids["reli"])),
    )
