"""RELI-RAG Day 2 A1: manual test of the retrieval service.

Usage (from the project root or backend/):
    python backend/test_retrieval.py "your question" [--k 5] [--doc-ids 1 2]

Requires the database to be running with at least one ingested document.
Read-only: nothing is written to the database. Exits with status 0 on success, 1 on failure.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.db import SessionLocal  # noqa: E402
from app.services.retrieval import DEFAULT_TOP_K, retrieve  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a retrieval query against pgvector.")
    parser.add_argument("question")
    parser.add_argument("--k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--doc-ids", type=int, nargs="*", default=None)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        results = retrieve(db, args.question, k=args.k, document_ids=args.doc_ids)
    except Exception as exc:
        print(f"[FAIL] Retrieval error: {exc!r}")
        return 1
    finally:
        db.close()

    print(f"Question: {args.question!r}  k={args.k}  document_ids={args.doc_ids}")
    if not results:
        print("[FAIL] No chunks returned (has anything been ingested?)")
        return 1

    for rank, r in enumerate(results, start=1):
        print(
            f"\n#{rank} similarity={r.similarity:.4f} chunk_id={r.chunk_id} "
            f"document_id={r.document_id} document={r.document!r} page={r.page}"
        )
        print(f"   {r.text[:200]}{'...' if len(r.text) > 200 else ''}")

    similarities = [r.similarity for r in results]
    if similarities != sorted(similarities, reverse=True):
        print("\n[FAIL] Results are not ordered by descending similarity")
        return 1
    if args.doc_ids is not None and any(r.document_id not in args.doc_ids for r in results):
        print("\n[FAIL] Result outside the requested document_ids")
        return 1

    print(f"\n[OK] Retrieval returned {len(results)} chunks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
