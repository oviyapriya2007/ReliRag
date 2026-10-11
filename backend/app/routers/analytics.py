from fastapi import APIRouter, HTTPException, status

router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
    responses={status.HTTP_501_NOT_IMPLEMENTED: {"description": "Not implemented yet."}},
)

NOT_IMPLEMENTED_DETAIL = "Analytics are not implemented yet."


@router.get("/summary")
def get_summary():
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, NOT_IMPLEMENTED_DETAIL)
