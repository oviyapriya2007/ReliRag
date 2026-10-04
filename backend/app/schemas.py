from datetime import datetime

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    status: str


class DocumentUploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    total_pages: int | None
    total_chunks: int | None


class DocumentRead(DocumentUploadResponse):
    uploaded_at: datetime


class DocumentDeleteResponse(BaseModel):
    id: int
    filename: str
    deleted: bool
    message: str
