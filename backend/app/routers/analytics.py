from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import AnalyticsSummary
from app.services.analytics import DEFAULT_TOP_DOCUMENTS, build_summary

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary", response_model=AnalyticsSummary)
def get_summary(
    benchmark_run_id: str | None = Query(default=None, max_length=64),
    top_documents: int = Query(default=DEFAULT_TOP_DOCUMENTS, ge=1, le=50),
    db: Session = Depends(get_db),
):
    return build_summary(db, benchmark_run_id=benchmark_run_id, top_documents=top_documents)
