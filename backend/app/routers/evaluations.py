from fastapi import APIRouter

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


@router.post("")
def create_evaluation():
    return {"message": "Evaluation not implemented yet", "evaluation_id": 1}


@router.get("")
def list_evaluations():
    return {"evaluations": []}


@router.get("/{evaluation_id}")
def get_evaluation(evaluation_id: int):
    return {"id": evaluation_id, "status": "mock", "metrics": {}}
