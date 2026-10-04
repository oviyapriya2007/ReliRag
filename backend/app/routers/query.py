from fastapi import APIRouter

router = APIRouter(prefix="/query", tags=["query"])


@router.post("")
def run_query():
    return {"answer": "Mock answer", "sources": []}
