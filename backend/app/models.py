from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.db import Base

EMBEDDING_DIM = 384
# Deterministic evaluator checks that can change a claim's verdict (Claim.check_name).
CLAIM_CHECK_NAMES = ("evidence", "support", "citation", "uncited", "limitation", "contradiction")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    total_pages: Mapped[int | None] = mapped_column(Integer)
    total_chunks: Mapped[int | None] = mapped_column(Integer)
    # Set instead of deleting a document that past answer attempts retrieved from: it is hidden
    # from listings and retrieval, but its chunks stay so that history remains intact.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("document_id", "chunk_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    page_number: Mapped[int | None] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    document: Mapped[Document] = relationship(back_populates="chunks")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    queries: Mapped[list["Query"]] = relationship(back_populates="conversation")


class Query(Base):
    __tablename__ = "queries"
    __table_args__ = (
        CheckConstraint("mode IN ('basic', 'reli')", name="ck_queries_mode"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    options: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    final_status: Mapped[str | None] = mapped_column(String(32))
    final_attempt_number: Mapped[int | None] = mapped_column(Integer)
    benchmark_run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[Conversation | None] = relationship(back_populates="queries")
    answers: Mapped[list["Answer"]] = relationship(
        back_populates="query",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Answer.attempt_number",
    )


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (UniqueConstraint("query_id", "attempt_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    query_id: Mapped[int] = mapped_column(
        ForeignKey("queries.id", ondelete="CASCADE"), index=True, nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    answer_text: Mapped[str | None] = mapped_column(Text)
    retrieval_query: Mapped[str | None] = mapped_column(Text)
    strategy: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(128))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)

    query: Mapped[Query] = relationship(back_populates="answers")
    retrieval_logs: Mapped[list["RetrievalLog"]] = relationship(
        back_populates="answer",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RetrievalLog.rank",
    )
    evaluations: Mapped[list["Evaluation"]] = relationship(
        back_populates="answer",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Evaluation.id",
    )


class RetrievalLog(Base):
    __tablename__ = "retrieval_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    answer_id: Mapped[int] = mapped_column(
        ForeignKey("answers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), index=True, nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    similarity: Mapped[float | None] = mapped_column(Float)

    answer: Mapped[Answer] = relationship(back_populates="retrieval_logs")
    chunk: Mapped[DocumentChunk] = relationship()


class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    answer_id: Mapped[int] = mapped_column(
        ForeignKey("answers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    faithfulness: Mapped[float | None] = mapped_column(Float)
    answer_relevance: Mapped[float | None] = mapped_column(Float)
    context_relevance: Mapped[float | None] = mapped_column(Float)
    passed: Mapped[bool | None] = mapped_column()
    failure_type: Mapped[str | None] = mapped_column(String(64))
    feedback: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(128))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)

    answer: Mapped[Answer] = relationship(back_populates="evaluations")
    claims: Mapped[list["Claim"]] = relationship(
        back_populates="evaluation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Claim.id",
    )


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(primary_key=True)
    evaluation_id: Mapped[int] = mapped_column(
        ForeignKey("evaluations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    verdict: Mapped[str | None] = mapped_column(String(32))
    evidence_chunk_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="SET NULL"), index=True
    )
    evidence_quote: Mapped[str | None] = mapped_column(Text)
    # Verification details; NULL for claims saved before they were recorded. `claude_verdict`
    # is Claude's verdict before the deterministic checks (NULL for a claim a check added),
    # `evidence_error` why a check changed the claim, and `check_name` which check did.
    claude_verdict: Mapped[str | None] = mapped_column(String(32))
    evidence_error: Mapped[str | None] = mapped_column(Text)
    check_name: Mapped[str | None] = mapped_column(String(16))
    # The evidence Claude gave, even if a check rejected it; never support. Not a foreign key:
    # a rejected chunk ID may name a chunk that was not retrieved or does not exist.
    claude_evidence_chunk_id: Mapped[int | None] = mapped_column(Integer)
    claude_evidence_quote: Mapped[str | None] = mapped_column(Text)

    evaluation: Mapped[Evaluation] = relationship(back_populates="claims")
    evidence_chunk: Mapped[DocumentChunk | None] = relationship()

    @validates("check_name")
    def _validate_check_name(self, _key: str, value: str | None) -> str | None:
        if value is not None and value not in CLAIM_CHECK_NAMES:
            raise ValueError(f"check_name must be one of {CLAIM_CHECK_NAMES} or None, not {value!r}")
        return value
