"""RELI-RAG Day 2 A4: manual test of the generator (A1 retrieval -> A4 generation).

Usage (from the project root or backend/):
    python backend/test_generator.py "your question" [--k 5] [--doc-ids 1 2] [--show-prompt]

Makes a real Claude API call (costs tokens). Requires the database with at least one
ingested document, plus ANTHROPIC_API_KEY and CLAUDE_MODEL in .env.
Read-only: nothing is written to the database. Exits with status 0 on success, 1 on failure.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.db import SessionLocal  # noqa: E402
from app.services.generator import ANSWERED, build_prompt, generate_answer  # noqa: E402
from app.services.llm import LLMError  # noqa: E402
from app.services.retrieval import DEFAULT_TOP_K, retrieve  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Retrieve chunks and generate a cited answer.")
    parser.add_argument("question")
    parser.add_argument("--k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--doc-ids", type=int, nargs="*", default=None)
    parser.add_argument("--show-prompt", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        chunks = retrieve(db, args.question, k=args.k, document_ids=args.doc_ids)
    finally:
        db.close()

    print(f"Retrieved {len(chunks)} chunks:")
    for number, chunk in enumerate(chunks, start=1):
        print(f"  [{number}] sim={chunk.similarity:.4f} {chunk.document} p.{chunk.page} "
              f"chunk_id={chunk.chunk_id}")
    if args.show_prompt:
        print(f"\n--- prompt ---\n{build_prompt(args.question, chunks)}\n--------------")

    try:
        result = generate_answer(args.question, chunks)
    except LLMError as exc:
        print(f"\n[FAIL] {exc}")
        return 1

    print(f"\nStatus:    {result.status}")
    print(f"Citations: {result.citations}")
    if result.llm is not None:
        print(f"LLM:       model={result.llm.model} latency_ms={result.llm.latency_ms} "
              f"in={result.llm.input_tokens} out={result.llm.output_tokens} "
              f"attempts={result.llm.attempts}")
    if result.answer is not None:
        print(f"\n{result.answer}")
    for number, chunk in zip(result.citations, result.cited_chunks, strict=True):
        print(f"\n  [{number}] -> chunk_id={chunk.chunk_id} {chunk.document} p.{chunk.page}")

    if result.status == ANSWERED and not result.citations:
        print("\n[WARN] Answer has no valid citations")
    print(f"\n[OK] Generator returned {result.status}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
