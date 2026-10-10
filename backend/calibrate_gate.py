"""RELI-RAG A6: similarity gate calibration.

Runs A1 retrieval (top-1 only, no Claude calls) for covered and out-of-scope questions,
prints each question's top-1 similarity, and suggests a SIMILARITY_GATE value that
separates the two groups. Read-only: nothing is written to the database, and
SIMILARITY_GATE is never changed automatically.

Usage (from the project root or backend/):
    python backend/calibrate_gate.py                                # built-in placeholder questions
    python backend/calibrate_gate.py --questions questions.json     # {"covered": [...], "out_of_scope": [...]}
    python backend/calibrate_gate.py --questions data/benchmark.json --doc-ids 8   # benchmark format
    python backend/calibrate_gate.py --covered "q1" "q2" --out-of-scope "q3" "q4"
    python backend/calibrate_gate.py --doc-ids 7                    # restrict retrieval to documents

Exits with status 0 when calibration ran, 1 on error.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.services.retrieval import retrieve  # noqa: E402

COVERED = "covered"
OUT_OF_SCOPE = "out_of_scope"

# data/benchmark.json categories -> calibration groups. Ambiguous questions are treated as
# out-of-scope here: the gate should not admit them as answerable.
BENCHMARK_CATEGORIES = {
    "clearly_covered": COVERED,
    "multipart_comparison": COVERED,
    "ambiguous_tricky": OUT_OF_SCOPE,
    "out_of_scope": OUT_OF_SCOPE,
}

# ---------------------------------------------------------------------------
# PLACEHOLDER QUESTIONS: written for the sample data/test.pdf ("Sample PDF Created
# for testing PDFObject", mostly lorem ipsum). Replace with Person B's calibration
# set via --questions once it exists.
# ---------------------------------------------------------------------------
PLACEHOLDER_QUESTIONS = {
    COVERED: [
        "How many pages long is the sample PDF?",
        "What was this sample PDF created for testing?",
        "Are the pages of this PDF long or short?",
        "What does the document say about three long minutes?",
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit?",
    ],
    OUT_OF_SCOPE: [
        "What is the capital of Mongolia?",
        "How do I bake sourdough bread at home?",
        "Who won the 2018 FIFA World Cup?",
        "Explain how photosynthesis works in plants.",
        "How many days of annual leave do full-time employees get?",
    ],
}


@dataclass(frozen=True)
class Score:
    question: str
    category: str
    similarity: float


def _string_list(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(q, str) and q.strip() for q in value):
        raise ValueError(f"{name!r} must be a list of non-empty strings")
    return [q.strip() for q in value]


def parse_questions_file(data: object) -> dict[str, list[str]]:
    """Group questions from either supported JSON format into covered / out-of-scope.

    - Simple: {"covered": [...], "out_of_scope": [...]}
    - Benchmark (data/benchmark.json): {"questions": [{"id", "category", "question"}, ...]}
    """
    if not isinstance(data, dict):
        raise ValueError("questions file must contain a JSON object")

    if "questions" not in data:
        return {
            COVERED: _string_list(data.get(COVERED, []), COVERED),
            OUT_OF_SCOPE: _string_list(data.get(OUT_OF_SCOPE, []), OUT_OF_SCOPE),
        }

    entries = data["questions"]
    if not isinstance(entries, list):
        raise ValueError("'questions' must be a list")

    questions: dict[str, list[str]] = {COVERED: [], OUT_OF_SCOPE: []}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"question #{index} must be an object")
        label = entry.get("id", f"#{index}")
        category = entry.get("category")
        if category not in BENCHMARK_CATEGORIES:
            raise ValueError(
                f"question {label} has invalid or missing category {category!r}; "
                f"expected one of {sorted(BENCHMARK_CATEGORIES)}"
            )
        question = entry.get("question")
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"question {label} has a missing or empty 'question' field")
        questions[BENCHMARK_CATEGORIES[category]].append(question.strip())
    return questions


def load_questions(args: argparse.Namespace) -> dict[str, list[str]]:
    if args.questions:
        data = json.loads(Path(args.questions).read_text(encoding="utf-8-sig"))
        questions = parse_questions_file(data)
    elif args.covered or args.out_of_scope:
        questions = {COVERED: args.covered or [], OUT_OF_SCOPE: args.out_of_scope or []}
    else:
        print("Using built-in PLACEHOLDER questions (pass --questions to use a real set).\n")
        questions = PLACEHOLDER_QUESTIONS

    if not questions[COVERED] or not questions[OUT_OF_SCOPE]:
        raise ValueError("need at least one covered and one out-of-scope question")
    return questions


def score_questions(
    questions: dict[str, list[str]], document_ids: list[int] | None
) -> list[Score]:
    scores = []
    db = SessionLocal()
    try:
        for category in (COVERED, OUT_OF_SCOPE):
            for question in questions[category]:
                top = retrieve(db, question, k=1, document_ids=document_ids)
                if not top:
                    raise RuntimeError(f"no chunks retrieved for {question!r} (nothing ingested?)")
                scores.append(Score(question, category, top[0].similarity))
    finally:
        db.close()
    return scores


def print_table(scores: list[Score]) -> None:
    width = min(max(len(s.question) for s in scores), 70)
    print(f"{'question':<{width}} | {'category':<12} | top-1 similarity")
    print(f"{'-' * width}-+-{'-' * 12}-+-{'-' * 16}")
    for s in sorted(scores, key=lambda s: s.similarity, reverse=True):
        question = s.question if len(s.question) <= width else s.question[: width - 3] + "..."
        print(f"{question:<{width}} | {s.category:<12} | {s.similarity:.4f}")


def gate_errors(scores: list[Score], gate: float) -> tuple[int, int]:
    """Return (covered questions rejected, out-of-scope questions admitted) at `gate`."""
    rejected = sum(1 for s in scores if s.category == COVERED and s.similarity < gate)
    admitted = sum(1 for s in scores if s.category == OUT_OF_SCOPE and s.similarity >= gate)
    return rejected, admitted


def suggest_gate(lowest_covered: float, highest_out: float) -> float:
    midpoint = (lowest_covered + highest_out) / 2
    rounded = round(midpoint, 2)
    return rounded if highest_out < rounded <= lowest_covered else round(midpoint, 4)


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate the similarity gate (no Claude calls).")
    parser.add_argument(
        "--questions",
        help='JSON file: {"covered": [...], "out_of_scope": [...]} or the data/benchmark.json format',
    )
    parser.add_argument("--covered", nargs="*", default=None)
    parser.add_argument("--out-of-scope", nargs="*", default=None)
    parser.add_argument("--doc-ids", type=int, nargs="*", default=None)
    args = parser.parse_args()

    try:
        scores = score_questions(load_questions(args), args.doc_ids)
    except Exception as exc:
        print(f"[FAIL] Calibration error: {exc!r}")
        return 1

    print_table(scores)

    covered = [s for s in scores if s.category == COVERED]
    out_of_scope = [s for s in scores if s.category == OUT_OF_SCOPE]
    lowest_covered = min(covered, key=lambda s: s.similarity)
    highest_out = max(out_of_scope, key=lambda s: s.similarity)

    print(f"\nLowest covered score:       {lowest_covered.similarity:.4f}  ({lowest_covered.question!r})")
    print(f"Highest out-of-scope score: {highest_out.similarity:.4f}  ({highest_out.question!r})")

    current = settings.similarity_gate
    rejected, admitted = gate_errors(scores, current)
    print(f"\nCurrent SIMILARITY_GATE={current}: rejects {rejected}/{len(covered)} covered, "
          f"admits {admitted}/{len(out_of_scope)} out-of-scope")

    if lowest_covered.similarity > highest_out.similarity:
        gate = suggest_gate(lowest_covered.similarity, highest_out.similarity)
        margin = lowest_covered.similarity - highest_out.similarity
        print(f"\n[SEPARABLE] Suggested SIMILARITY_GATE={gate} "
              f"(midpoint of the gap, margin {margin:.4f}).")
        print(f"Set it manually in .env: SIMILARITY_GATE={gate}")
    else:
        overlap = highest_out.similarity - lowest_covered.similarity
        print(f"\n[NOT SEPARABLE] Scores overlap by {overlap:.4f}; no threshold separates the groups.")
        print("Review the questions/documents above, or choose a gate by trading off the two error types.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
