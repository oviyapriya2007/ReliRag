"""RELI-RAG Day 2 A2: manual test of the similarity gate.

Usage (from the project root or backend/):
    python backend/test_similarity_gate.py "your question" [--threshold 0.3] [--k 5]
                                           [--doc-ids 1 2] [--keep]

Requires the database to be running with at least one ingested document.
Creates a temporary `queries` row; it (and its answers/retrieval_log rows, via
ON DELETE CASCADE) is removed afterwards unless --keep is given.
Exits with status 0 on success, 1 on failure.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import delete, select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Answer, Query, RetrievalLog  # noqa: E402
from app.services.retrieval import DEFAULT_TOP_K  # noqa: E402
from app.services.similarity_gate import INSUFFICIENT_EVIDENCE, retrieve_with_gate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run retrieval + similarity gate once.")
    parser.add_argument("question")
    parser.add_argument("--threshold", type=float, default=None,
                        help=f"override SIMILARITY_GATE (currently {settings.similarity_gate})")
    parser.add_argument("--k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--doc-ids", type=int, nargs="*", default=None)
    parser.add_argument("--keep", action="store_true", help="keep the rows for inspection")
    args = parser.parse_args()

    db = SessionLocal()
    query_id: int | None = None
    try:
        query = Query(question=args.question, mode="reli")
        db.add(query)
        db.commit()
        query_id = query.id

        result = retrieve_with_gate(
            db, query, k=args.k, document_ids=args.doc_ids, threshold=args.threshold
        )

        top = f"{result.top_similarity:.4f}" if result.top_similarity is not None else "n/a"
        print(f"Question:       {args.question!r}")
        print(f"Threshold:      {result.threshold}")
        print(f"Top-1 sim:      {top}")
        print(f"Gate:           {'PASS' if result.passed else 'FAIL'}")
        print(f"Answer status:  {result.status}")
        print(f"Query status:   {query.final_status}")

        answer = db.get(Answer, result.answer_id)
        logs = db.scalars(
            select(RetrievalLog)
            .where(RetrievalLog.answer_id == result.answer_id)
            .order_by(RetrievalLog.rank)
        ).all()
        print(f"\nretrieval_log rows for answer_id={result.answer_id} (query_id={query_id}):")
        for log in logs:
            print(f"  rank={log.rank} chunk_id={log.chunk_id} similarity={log.similarity:.4f}")

        if answer is None or len(logs) != len(result.chunks):
            print(f"\n[FAIL] Expected {len(result.chunks)} retrieval_log rows, found {len(logs)}")
            return 1
        expected = None if result.passed else INSUFFICIENT_EVIDENCE
        if answer.status != expected or (not result.passed and query.final_status != expected):
            print(f"\n[FAIL] Expected status {expected}, got answer={answer.status} "
                  f"query={query.final_status}")
            return 1

        print(f"\n[OK] Gate {'passed' if result.passed else 'failed'}; "
              f"{len(logs)} retrieval rows logged.")
        return 0
    except Exception as exc:
        print(f"[FAIL] Similarity gate error: {exc!r}")
        return 1
    finally:
        db.rollback()
        if query_id is not None and not args.keep:
            db.execute(delete(Query).where(Query.id == query_id))
            db.commit()
            print(f"Cleaned up temporary query id={query_id}")
        db.close()


if __name__ == "__main__":
    sys.exit(main())
