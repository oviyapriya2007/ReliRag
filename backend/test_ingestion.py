"""RELI-RAG A4: end-to-end test of the ingestion service.

Usage (from the project root or backend/):
    python backend/test_ingestion.py

Requires the database to be running. Exits with status 0 on success, 1 on failure.
The temporary document (and its chunks, via ON DELETE CASCADE) is always removed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import delete, select, text  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import EMBEDDING_DIM, Document, DocumentChunk  # noqa: E402
from app.services.ingestion import ingest_document  # noqa: E402

PDF_PATH = Path(r"D:\relirag\data\test.pdf")


def ensure_schema() -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)


def main() -> int:
    if not PDF_PATH.is_file():
        print(f"[FAIL] Test PDF not found: {PDF_PATH}")
        return 1

    ensure_schema()

    db = SessionLocal()
    document_id: int | None = None
    try:
        document = Document(filename=PDF_PATH.name)
        db.add(document)
        db.commit()
        document_id = document.id
        print(f"Created temporary document id={document_id} for {PDF_PATH}")

        ingest_document(db, document, PDF_PATH)
        db.commit()

        print(f"Total pages:  {document.total_pages}")
        print(f"Total chunks: {document.total_chunks}")

        chunks = db.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
        ).all()

        print(f"\n{'page':>5} {'chunk':>6} {'chars':>6} {'dim':>5}")
        for chunk in chunks:
            dim = len(chunk.embedding) if chunk.embedding is not None else 0
            print(f"{chunk.page_number:>5} {chunk.chunk_index:>6} {len(chunk.content):>6} {dim:>5}")

        if len(chunks) != document.total_chunks:
            print(f"[FAIL] Found {len(chunks)} chunks but total_chunks={document.total_chunks}")
            return 1
        if not chunks:
            print("[FAIL] No chunks were created (is the PDF text-based?)")
            return 1
        bad = [c.chunk_index for c in chunks if c.embedding is None or len(c.embedding) != EMBEDDING_DIM]
        if bad:
            print(f"[FAIL] Chunks without a {EMBEDDING_DIM}-dim embedding: {bad}")
            return 1

        print(f"\n[OK] Ingestion test passed: {len(chunks)} chunks stored.")
        return 0
    except Exception as exc:
        print(f"[FAIL] Ingestion test error: {exc!r}")
        return 1
    finally:
        db.rollback()
        if document_id is not None:
            db.execute(delete(Document).where(Document.id == document_id))
            db.commit()
            print(f"Cleaned up temporary document id={document_id}")
        db.close()


if __name__ == "__main__":
    sys.exit(main())
