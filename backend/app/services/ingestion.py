import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import pymupdf
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

CHUNK_SIZE = 800
CHUNK_OVERLAP = 150
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_BATCH_SIZE = 32

_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str


@dataclass(frozen=True)
class Chunk:
    page_number: int
    chunk_index: int
    content: str


def normalize_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def extract_pages(source: str | Path | bytes) -> tuple[int, list[PageText]]:
    """Return the PDF's total page count and its non-empty pages (1-based numbers)."""
    if isinstance(source, bytes):
        pdf = pymupdf.open(stream=source, filetype="pdf")
    else:
        pdf = pymupdf.open(source)

    with pdf:
        pages = []
        for page in pdf:
            text = normalize_whitespace(page.get_text("text"))
            if text:
                pages.append(PageText(page_number=page.number + 1, text=text))
        return pdf.page_count, pages


def split_text(
    text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> list[str]:
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")

    pieces = []
    step = size - overlap
    for start in range(0, len(text), step):
        pieces.append(text[start : start + size])
        if start + size >= len(text):
            break
    return pieces


def chunk_pages(pages: list[PageText]) -> list[Chunk]:
    """Chunk each page on its own so no chunk spans two pages."""
    chunks = []
    for page in pages:
        for piece in split_text(page.text):
            chunks.append(
                Chunk(page_number=page.page_number, chunk_index=len(chunks), content=piece)
            )
    return chunks


@lru_cache(maxsize=1)
def get_embedding_model() -> "SentenceTransformer":
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL_NAME)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    embeddings = get_embedding_model().encode(
        texts,
        batch_size=EMBEDDING_BATCH_SIZE,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return embeddings.tolist()


def ingest_document(db: Session, document: Document, source: str | Path | bytes) -> Document:
    """Extract, chunk, embed and store a PDF for an existing `documents` row.

    Re-ingesting a document replaces its previous chunks.
    """
    total_pages, pages = extract_pages(source)
    chunks = chunk_pages(pages)
    embeddings = embed_texts([chunk.content for chunk in chunks])

    try:
        db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
        if chunks:
            db.execute(
                insert(DocumentChunk),
                [
                    {
                        "document_id": document.id,
                        "page_number": chunk.page_number,
                        "chunk_index": chunk.chunk_index,
                        "content": chunk.content,
                        "embedding": embedding,
                    }
                    for chunk, embedding in zip(chunks, embeddings, strict=True)
                ],
            )
        document.total_pages = total_pages
        document.total_chunks = len(chunks)
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(document)
    return document
