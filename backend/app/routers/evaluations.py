from fastapi import APIRouter, HTTPException, status

router = APIRouter(
    prefix="/evaluations",
    tags=["evaluations"],
    responses={status.HTTP_501_NOT_IMPLEMENTED: {"description": "Not implemented yet."}},
)

NOT_IMPLEMENTED_DETAIL = (
    "Standalone evaluation endpoints are not implemented yet. Per-answer evaluations are "
    "returned by POST /query and GET /query/{query_id}."
)


def _not_implemented() -> HTTPException:
    return HTTPException(status.HTTP_501_NOT_IMPLEMENTED, NOT_IMPLEMENTED_DETAIL)


@router.post("")
def create_evaluation():
    raise _not_implemented()


@router.get("")
def list_evaluations():
    raise _not_implemented()


@router.get("/{evaluation_id}")
def get_evaluation(evaluation_id: int):
    raise _not_implemented()
