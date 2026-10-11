from fastapi import APIRouter, HTTPException, status

router = APIRouter(
    prefix="/compare",
    tags=["compare"],
    responses={status.HTTP_501_NOT_IMPLEMENTED: {"description": "Not implemented yet."}},
)

NOT_IMPLEMENTED_DETAIL = "Answer comparison is not implemented yet."


@router.post("")
def compare_answers():
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, NOT_IMPLEMENTED_DETAIL)
