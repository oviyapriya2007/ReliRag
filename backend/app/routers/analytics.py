from fastapi import APIRouter

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/summary")
def get_summary():
    return {"total_documents": 0, "total_queries": 0, "total_evaluations": 0}
