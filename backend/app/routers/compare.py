from fastapi import APIRouter

router = APIRouter(prefix="/compare", tags=["compare"])


@router.post("")
def compare_answers():
    return {"results": []}
