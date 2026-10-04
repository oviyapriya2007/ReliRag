from pathlib import Path

import pymupdf
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Document
from app.schemas import DocumentDeleteResponse, DocumentRead, DocumentUploadResponse
from app.services.ingestion import ingest_document

router = APIRouter(prefix="/documents", tags=["documents"])

MAX_UPLOAD_BYTES = settings.max_upload_mb * 1024 * 1024
PDF_CONTENT_TYPES = {"application/pdf", "application/x-pdf", "application/octet-stream"}
PDF_MAGIC = b"%PDF-"


def _read_pdf_upload(file: UploadFile) -> tuple[str, bytes]:
    filename = Path(file.filename or "").name
    if not filename.lower().endswith(".pdf") or file.content_type not in PDF_CONTENT_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PDF files are accepted.")

    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"File exceeds the {settings.max_upload_mb} MB limit.",
        )
    if not data.startswith(PDF_MAGIC):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "File is not a valid PDF.")
    return filename, data


def _discard(db: Session, document: Document) -> None:
    db.rollback()
    db.delete(document)
    db.commit()


# Sync handler on purpose: FastAPI runs it in a worker thread, so the
# CPU-bound parsing and embedding don't block the event loop.
@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)):
    try:
        filename, data = _read_pdf_upload(file)
    finally:
        file.file.close()

    document = Document(filename=filename)
    db.add(document)
    db.commit()

    try:
        ingest_document(db, document, data)
    except pymupdf.FileDataError:
        _discard(db, document)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The PDF could not be read.")
    except Exception:
        _discard(db, document)
        raise

    if not document.total_chunks:
        _discard(db, document)
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "No extractable text found in the PDF (it may be scanned images).",
        )

    return document


@router.get("", response_model=list[DocumentRead])
def list_documents(db: Session = Depends(get_db)):
    return db.scalars(select(Document).order_by(Document.uploaded_at.desc())).all()


@router.delete("/{document_id}", response_model=DocumentDeleteResponse)
def delete_document(document_id: int, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Document {document_id} not found.")

    filename, chunk_count = document.filename, document.total_chunks or 0
    db.delete(document)
    db.commit()

    return DocumentDeleteResponse(
        id=document_id,
        filename=filename,
        deleted=True,
        message=f"Deleted document '{filename}' and {chunk_count} chunks.",
    )
