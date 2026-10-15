"""RELI-RAG Day 5 A3: run a benchmark through POST /compare and export per-question results.

Usage (from the project root, with the API running and the backend venv active):
    python scripts/run_benchmark.py                       # print the plan only, no API calls
    python scripts/run_benchmark.py --yes                 # run every question
    python scripts/run_benchmark.py --yes --ids Q01 Q02 --doc-ids 8 --output results.csv

Each question is sent to POST /compare with one `benchmark_run_id`, which the API stores on
both queries, so `GET /analytics/summary?benchmark_run_id=<run id>` reports just this run.
A live run calls Claude: about 4-7 calls per question (two answers, two evaluations, and at
most one correction), hence the explicit --yes.

Exits with status 0 when every question got a comparison, 1 if any request failed, and 2 for
invalid input.
"""

import argparse
import csv
import json
import re
import sys
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUESTIONS = ROOT / "data" / "benchmark.json"
DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_OUTPUT = "results.csv"
DEFAULT_TIMEOUT_SECONDS = 300.0
RUN_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")

VERDICTS = ("supported", "partially_supported", "unsupported")
SCORES = ("faithfulness", "answer_relevance", "context_relevance")
BRANCH_FIELDS = (
    "query_id", "status", "answer", "final_attempt", "attempts", *SCORES, "passed",
    "failure_type", "supported_claims", "partially_supported_claims", "unsupported_claims",
    "latency_ms",
)
CSV_FIELDS = (
    "question_id", "category", "answerable", "benchmark_run_id", "question", "compare_id",
    "http_status", "error", "elapsed_ms",
    *(f"basic_{field}" for field in BRANCH_FIELDS),
    *(f"reli_{field}" for field in BRANCH_FIELDS),
    "reli_correction_strategy", "reli_correction_outcome",
)
# Spreadsheet apps execute cells starting with these characters as formulas.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_TEXT_FIELDS = {"question", "error", "basic_answer", "reli_answer", "question_id", "category"}


class BenchmarkFileError(ValueError):
    pass


@dataclass(frozen=True)
class BenchmarkQuestion:
    id: str
    question: str
    category: str | None = None
    answerable: bool | None = None


def load_questions(path: Path) -> list[BenchmarkQuestion]:
    """Questions from `{"questions": [{"id", "question", "category"?, "answerable"?}, ...]}`."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkFileError(f"cannot read {path}: {exc}") from exc
    items = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise BenchmarkFileError(f'{path} must contain a non-empty "questions" list')

    questions, seen = [], set()
    for number, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise BenchmarkFileError(f"question {number} must be an object")
        qid, text = item.get("id"), item.get("question")
        if not isinstance(qid, str) or not qid.strip():
            raise BenchmarkFileError(f'question {number} needs a non-empty string "id"')
        if not isinstance(text, str) or not text.strip():
            raise BenchmarkFileError(f'question {qid} needs a non-empty string "question"')
        if qid in seen:
            raise BenchmarkFileError(f"duplicate question id {qid}")
        seen.add(qid)
        category, answerable = item.get("category"), item.get("answerable")
        questions.append(BenchmarkQuestion(
            id=qid.strip(), question=text.strip(),
            category=category if isinstance(category, str) else None,
            answerable=answerable if isinstance(answerable, bool) else None,
        ))
    return questions


def new_run_id(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"bench-{now:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"


# --- one response -> one row ----------------------------------------------------------------


def _final_attempt(branch: dict[str, Any]) -> dict[str, Any] | None:
    attempts = branch.get("attempts") or []
    number = branch.get("final_attempt_number")
    for attempt in attempts:
        if attempt.get("attempt_number") == number:
            return attempt
    return attempts[-1] if attempts else None


def _latency_ms(branch: dict[str, Any]) -> int | None:
    """Recorded Claude time: generation plus evaluation, summed over every attempt."""
    values = [value for attempt in branch.get("attempts") or []
              for value in ((attempt.get("timings") or {}).get("generate_ms"),
                            (attempt.get("timings") or {}).get("evaluate_ms"))
              if value is not None]
    return sum(values) if values else None


def branch_fields(branch: dict[str, Any] | None) -> dict[str, Any]:
    """CSV fields for one branch; scores and claim counts are the final attempt's."""
    fields: dict[str, Any] = dict.fromkeys(BRANCH_FIELDS)
    if not branch:
        return fields
    final = _final_attempt(branch)
    evaluation = (final or {}).get("evaluation")
    fields.update(query_id=branch.get("query_id"), status=branch.get("status"),
                  answer=branch.get("final_answer"),
                  final_attempt=final.get("attempt_number") if final else None,
                  attempts=len(branch.get("attempts") or []), latency_ms=_latency_ms(branch))
    if evaluation:
        fields.update({score: evaluation.get(score) for score in SCORES})
        fields.update(passed=evaluation.get("passed"), failure_type=evaluation.get("failure_type"))
        verdicts = [claim.get("verdict") for claim in evaluation.get("claims") or []]
        for verdict in VERDICTS:
            fields[f"{verdict}_claims"] = verdicts.count(verdict)
    return fields


def correction_outcome(reli: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """(strategy, outcome) of RELI-RAG's correction.

    Outcomes: not_needed (attempt 1 passed), not_triggered (no attempt 2: attempt 1 was not
    answered, or not usably evaluated), successful (attempt 2 reported and passed), improved
    (attempt 2 reported but still failing), failed (attempt 1 kept).
    """
    if not reli:
        return None, None
    attempts = reli.get("attempts") or []
    if len(attempts) < 2:
        evaluation = attempts[0].get("evaluation") if attempts else None
        return None, "not_needed" if evaluation and evaluation.get("passed") else "not_triggered"
    strategy = attempts[1].get("strategy")
    final = _final_attempt(reli)
    if final is not None and final.get("attempt_number") == 2:
        passed = (final.get("evaluation") or {}).get("passed") is True
        return strategy, "successful" if passed else "improved"
    return strategy, "failed"


def build_row(question: BenchmarkQuestion, run_id: str, *, http_status: int | None,
              body: dict[str, Any] | None, error: str | None, elapsed_ms: int) -> dict[str, Any]:
    row: dict[str, Any] = {
        "question_id": question.id, "category": question.category,
        "answerable": question.answerable, "benchmark_run_id": run_id,
        "question": question.question, "compare_id": (body or {}).get("compare_id"),
        "http_status": http_status, "error": error, "elapsed_ms": elapsed_ms,
    }
    for mode in ("basic", "reli"):
        branch = (body or {}).get(mode)
        row.update({f"{mode}_{key}": value for key, value in branch_fields(branch).items()})
    strategy, outcome = correction_outcome((body or {}).get("reli"))
    row.update(reli_correction_strategy=strategy, reli_correction_outcome=outcome)
    return row


# --- running --------------------------------------------------------------------------------


def _error_detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if detail is None:
        detail = response.text[:300] or response.reason_phrase
    elif not isinstance(detail, str):
        detail = json.dumps(detail)[:300]
    return f"HTTP {response.status_code}: {detail}"


def compare_question(client: httpx.Client, question: BenchmarkQuestion, run_id: str, *,
                     k: int | None = None, document_ids: Sequence[int] | None = None,
                     clock: Callable[[], float] = time.perf_counter) -> dict[str, Any]:
    """POST one question to /compare; never raises for HTTP or network errors."""
    payload: dict[str, Any] = {"question": question.question, "benchmark_run_id": run_id}
    if k is not None:
        payload["k"] = k
    if document_ids is not None:
        payload["document_ids"] = list(document_ids)

    started = clock()
    http_status, body, error = None, None, None
    try:
        response = client.post("/compare", json=payload)
        http_status = response.status_code
        if response.is_success:
            body = response.json()
            if not isinstance(body, dict):
                body, error = None, "Unexpected response: not a JSON object"
            elif body.get("benchmark_run_id") != run_id:
                error = (f"API did not confirm benchmark_run_id {run_id!r} "
                         f"(got {body.get('benchmark_run_id')!r}); is the API up to date?")
        else:
            error = _error_detail(response)
    except httpx.HTTPError as exc:
        error = f"{type(exc).__name__}: {exc}"
    except ValueError as exc:
        error = f"Invalid JSON response: {exc}"
    elapsed_ms = round((clock() - started) * 1000)
    return build_row(question, run_id, http_status=http_status, body=body, error=error,
                     elapsed_ms=elapsed_ms)


def run_benchmark(client: httpx.Client, questions: Iterable[BenchmarkQuestion], run_id: str, *,
                  k: int | None = None, document_ids: Sequence[int] | None = None,
                  on_row: Callable[[dict[str, Any]], None] | None = None) -> list[dict[str, Any]]:
    rows = []
    for question in questions:
        row = compare_question(client, question, run_id, k=k, document_ids=document_ids)
        rows.append(row)
        if on_row is not None:
            on_row(row)
    return rows


# --- output ---------------------------------------------------------------------------------


def _csv_value(field: str, value: Any) -> Any:
    if value is None:
        return ""
    if field in _TEXT_FIELDS and isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def write_csv(rows: Iterable[dict[str, Any]], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(field, row.get(field)) for field in CSV_FIELDS})


def _fmt(value: Any, width: int) -> str:
    if value is None:
        text = "-"
    elif isinstance(value, bool):
        text = "yes" if value else "no"
    elif isinstance(value, float):
        text = f"{value:.2f}"
    else:
        text = str(value)
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "~"


TABLE_COLUMNS = (
    ("ID", "question_id", 6), ("Category", "category", 16),
    ("Basic", "basic_status", 21), ("B.faith", "basic_faithfulness", 7),
    ("B.pass", "basic_passed", 6), ("RELI", "reli_status", 21),
    ("R.faith", "reli_faithfulness", 7), ("R.pass", "reli_passed", 6),
    ("Correction", "reli_correction_outcome", 13), ("ms", "elapsed_ms", 7), ("Error", "error", 40),
)


def format_table(rows: Sequence[dict[str, Any]]) -> str:
    lines = ["  ".join(_fmt(title, width).ljust(width) for title, _, width in TABLE_COLUMNS)]
    lines.append("  ".join("-" * width for _, _, width in TABLE_COLUMNS))
    for row in rows:
        lines.append("  ".join(_fmt(row.get(key), width).ljust(width)
                               for _, key, width in TABLE_COLUMNS).rstrip())
    return "\n".join(lines)


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Run totals; pass counts are over the rows whose final answer was evaluated."""
    ok = [row for row in rows if row["error"] is None]
    outcomes = [row["reli_correction_outcome"] for row in ok]
    summary: dict[str, Any] = {
        "questions": len(rows), "completed": len(ok), "errors": len(rows) - len(ok),
        "corrections_triggered": sum(o in ("successful", "improved", "failed") for o in outcomes),
        "corrections_successful": outcomes.count("successful"),
    }
    for mode in ("basic", "reli"):
        evaluated = [row for row in ok if row[f"{mode}_passed"] is not None]
        latencies = [row[f"{mode}_latency_ms"] for row in ok
                     if row[f"{mode}_latency_ms"] is not None]
        summary[f"{mode}_passed"] = sum(row[f"{mode}_passed"] is True for row in evaluated)
        summary[f"{mode}_evaluated"] = len(evaluated)
        summary[f"{mode}_avg_latency_ms"] = (sum(latencies) / len(latencies)
                                             if latencies else None)
    return summary


def format_summary(summary: dict[str, Any], run_id: str) -> str:
    def latency(mode):
        value = summary[f"{mode}_avg_latency_ms"]
        return "-" if value is None else f"{value:.0f} ms"

    return "\n".join([
        f"Run {run_id}: {summary['completed']}/{summary['questions']} questions compared, "
        f"{summary['errors']} error(s)",
        f"  Basic RAG: {summary['basic_passed']}/{summary['basic_evaluated']} final answers "
        f"passed; avg Claude latency {latency('basic')}",
        f"  RELI-RAG:  {summary['reli_passed']}/{summary['reli_evaluated']} final answers "
        f"passed; avg Claude latency {latency('reli')}",
        f"  Corrections: {summary['corrections_triggered']} triggered, "
        f"{summary['corrections_successful']} successful",
        f"  Analytics: GET /analytics/summary?benchmark_run_id={run_id}",
    ])


# --- CLI ------------------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run benchmark questions through POST /compare (calls Claude with --yes).")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS,
                        help=f"benchmark JSON file (default: {DEFAULT_QUESTIONS})")
    parser.add_argument("--api-url", default=DEFAULT_API_URL,
                        help=f"API base URL (default: {DEFAULT_API_URL})")
    parser.add_argument("--output", type=Path, default=Path(DEFAULT_OUTPUT),
                        help=f"per-question CSV (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--run-id", help="benchmark run id (default: generated, unique)")
    parser.add_argument("--ids", nargs="+", help="only these question ids")
    parser.add_argument("--limit", type=int, help="only the first N questions")
    parser.add_argument("--k", type=int, help="chunks to retrieve (default: the API's)")
    parser.add_argument("--doc-ids", type=int, nargs="+", help="restrict to these document ids")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS,
                        help=f"seconds per request (default: {DEFAULT_TIMEOUT_SECONDS:.0f})")
    parser.add_argument("--yes", action="store_true",
                        help="actually call the API (and Claude); otherwise print the plan only")
    return parser.parse_args(argv)


def select_questions(questions: list[BenchmarkQuestion], ids: Sequence[str] | None,
                     limit: int | None) -> list[BenchmarkQuestion]:
    if ids:
        known = {question.id for question in questions}
        unknown = [qid for qid in ids if qid not in known]
        if unknown:
            raise BenchmarkFileError(f"unknown question id(s): {', '.join(unknown)}")
        questions = [question for question in questions if question.id in set(ids)]
    if limit is not None:
        if limit < 1:
            raise BenchmarkFileError("--limit must be at least 1")
        questions = questions[:limit]
    return questions


def main(argv: Sequence[str] | None = None, *, client: httpx.Client | None = None) -> int:
    args = parse_args(argv)
    run_id = args.run_id or new_run_id()
    if not RUN_ID_RE.match(run_id):
        print("error: --run-id must be 1-64 characters of A-Z a-z 0-9 . _ : -", file=sys.stderr)
        return 2
    try:
        questions = select_questions(load_questions(args.questions), args.ids, args.limit)
    except BenchmarkFileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"Benchmark run {run_id}: {len(questions)} question(s) from {args.questions}")
    if not args.yes:
        print(f"Plan only: this would POST each question to {args.api_url}/compare "
              f"(about {4 * len(questions)}-{7 * len(questions)} Claude calls) and write "
              f"{args.output}. Re-run with --yes to start.")
        return 0

    def progress(row):
        status = row["error"] or f"basic={row['basic_status']} reli={row['reli_status']}"
        print(f"  [{row['question_id']}] {status} ({row['elapsed_ms']} ms)", flush=True)

    owns_client = client is None
    client = client or httpx.Client(base_url=args.api_url, timeout=args.timeout)
    try:
        rows = run_benchmark(client, questions, run_id, k=args.k, document_ids=args.doc_ids,
                             on_row=progress)
    finally:
        if owns_client:
            client.close()

    write_csv(rows, args.output)
    print()
    print(format_table(rows))
    print()
    print(format_summary(summarize(rows), run_id))
    print(f"  CSV: {args.output}")
    return 0 if all(row["error"] is None for row in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
