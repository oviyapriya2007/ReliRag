"""RELI-RAG Day 3: evaluator sanity run on saved answers and controlled negative cases.

Usage (from the project root or backend/):
    python backend/sanity_evaluate_saved.py --dry-run [--answers ID ...] [--negatives]
    python backend/sanity_evaluate_saved.py [--answers ID ...] [--out DIR]
    python backend/sanity_evaluate_saved.py --negatives [--out DIR]

Without --answers or --negatives, the default saved answers are evaluated. --answers and
--negatives can be combined.

COST: every mode except --dry-run calls Claude (1-2 calls per evaluation) and consumes API
credits. --dry-run only reads the database and makes zero Claude calls.

Read-only: the database is opened in a read-only transaction that is always rolled back.
Nothing is inserted, updated, or deleted, and evaluation results are never persisted; they
are written to a timestamped JSON report instead.

Exit status: 0 when every check passes, 1 when any check fails (including evaluator errors),
2 when the selected data cannot be loaded (missing answers or evidence, database errors).
"""

import argparse
import json
import math
import re
import sys
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402
from sqlalchemy.orm import Session, selectinload  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Answer, DocumentChunk, RetrievalLog  # noqa: E402
from app.services.evaluator import (  # noqa: E402
    EVALUATOR_ERROR,
    IRRELEVANT_RETRIEVAL,
    MISSING_INFO,
    PARTIALLY_SUPPORTED,
    PASS_THRESHOLD,
    SUPPORTED,
    UNSUPPORTED,
    UNSUPPORTED_CLAIM,
    EvaluationResult,
    evaluate_answer,
)
from app.services.generator import ANSWERED, is_refusal, parse_citations  # noqa: E402
from app.services.retrieval import RetrievedChunk  # noqa: E402

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "data" / "eval_sanity"
DEFAULT_ANSWER_IDS = (6, 7, 9, 12, 13, 14, 15, 16, 18, 20)
# Saved answers whose retrieved chunks serve as evidence for the negative cases.
TCP_UDP_EVIDENCE_ANSWER_ID = 7
WRONG_EVIDENCE_ANSWER_ID = 15

VERDICTS = (SUPPORTED, PARTIALLY_SUPPORTED, UNSUPPORTED)
FAILURE_TYPES = (UNSUPPORTED_CLAIM, MISSING_INFO, IRRELEVANT_RETRIEVAL)

EVALUATED_PASS = "evaluated_pass"
EVALUATED_FAIL = "evaluated_fail"
OUTCOME_EVALUATOR_ERROR = "evaluator_error"

INTEGRITY = "integrity"
QUOTE_PRESENCE = "quote_presence"
SEMANTIC_SUPPORT = "semantic_support"
EXPECTATION = "expectation"
EVALUATOR = "evaluator_error"

_QUOTE_CHARS = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
                              "\u2013": "-", "\u2014": "-"})

TCP_UDP_QUESTION = "What is the main difference between TCP and UDP?"


class SetupError(Exception):
    """The selected data cannot be evaluated safely; nothing has been sent to Claude."""

    def __init__(self, problems: Sequence[str]):
        super().__init__("; ".join(problems))
        self.problems = list(problems)


@dataclass(frozen=True)
class EvidenceSet:
    answer_id: int
    query_id: int
    question: str
    answer_text: str | None
    status: str | None
    chunks: list[RetrievedChunk]


@dataclass(frozen=True)
class NegativeCase:
    name: str
    description: str
    question: str
    answer: str
    evidence_answer_id: int
    expect_pass: bool
    allowed_failure_types: tuple[str, ...] = ()
    # Claims matching any pattern (or every claim, with all_claims_false) are false given the
    # evidence and must get one of `allowed_false_verdicts`.
    false_claim_patterns: tuple[str, ...] = ()
    all_claims_false: bool = False
    allowed_false_verdicts: tuple[str, ...] = (UNSUPPORTED,)
    expect_low_context_relevance: bool = False


NEGATIVE_CASES = (
    NegativeCase(
        name="udp_guarantees_delivery",
        description="Contradicted claim: the evidence says UDP has no built-in delivery guarantees.",
        question=TCP_UDP_QUESTION,
        answer="UDP guarantees delivery [1].",
        evidence_answer_id=TCP_UDP_EVIDENCE_ANSWER_ID,
        expect_pass=False,
        allowed_failure_types=(UNSUPPORTED_CLAIM,),
        false_claim_patterns=(r"\budp\b.*\bguarantee",),
    ),
    NegativeCase(
        name="mixed_true_false",
        description="One grounded TCP claim plus a contradicted UDP claim.",
        question=TCP_UDP_QUESTION,
        answer=("TCP provides a reliable, ordered byte stream [1]. "
                "UDP guarantees delivery and ordering [1]."),
        evidence_answer_id=TCP_UDP_EVIDENCE_ANSWER_ID,
        expect_pass=False,
        allowed_failure_types=(UNSUPPORTED_CLAIM,),
        false_claim_patterns=(r"\budp\b.*\bguarantee",),
    ),
    NegativeCase(
        name="overreach",
        description="Grounded statement extended with an ungrounded comparison.",
        question=TCP_UDP_QUESTION,
        answer="UDP sends independent datagrams and is always faster than TCP [1].",
        evidence_answer_id=TCP_UDP_EVIDENCE_ANSWER_ID,
        expect_pass=False,
        allowed_failure_types=(UNSUPPORTED_CLAIM,),
        false_claim_patterns=(r"\bfaster\b",),
        allowed_false_verdicts=(UNSUPPORTED, PARTIALLY_SUPPORTED),
    ),
    NegativeCase(
        name="off_topic",
        description="Grounded sentence that does not answer the DHCP question.",
        question="What information can DHCP provide to a client?",
        answer="DNS queries often use UDP [1].",
        evidence_answer_id=TCP_UDP_EVIDENCE_ANSWER_ID,
        expect_pass=False,
        allowed_failure_types=(MISSING_INFO,),
    ),
    NegativeCase(
        name="wrong_evidence",
        description="Correct TCP/UDP answer evaluated against unrelated (attachment safety) chunks.",
        question=TCP_UDP_QUESTION,
        answer=("TCP provides a reliable, ordered byte stream, while UDP sends independent "
                "datagrams without built-in delivery guarantees or ordering [1]."),
        evidence_answer_id=WRONG_EVIDENCE_ANSWER_ID,
        expect_pass=False,
        allowed_failure_types=(UNSUPPORTED_CLAIM, IRRELEVANT_RETRIEVAL),
        all_claims_false=True,
        expect_low_context_relevance=True,
    ),
    NegativeCase(
        name="grounded_control",
        description="Sentences copied from the TCP/UDP passage; should pass.",
        question=TCP_UDP_QUESTION,
        answer=("TCP provides a reliable, ordered byte stream using connection establishment, "
                "sequence numbers, acknowledgements, retransmission, and flow control [1]. "
                "UDP sends independent datagrams without built-in delivery guarantees or "
                "ordering [1]."),
        evidence_answer_id=TCP_UDP_EVIDENCE_ANSWER_ID,
        expect_pass=True,
    ),
)


@dataclass(frozen=True)
class Check:
    kind: str
    name: str
    ok: bool
    detail: str = ""


# --- database (read-only) ---------------------------------------------------------------

def begin_read_only(db: Session) -> None:
    """Make the session's transaction read-only on PostgreSQL, so any write would fail."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SET TRANSACTION READ ONLY"))


def rebuild_chunks(answer_id: int, logs: Sequence[RetrievalLog]) -> list[RetrievedChunk]:
    """Rebuild an answer's retrieved chunks in rank order, so citation [n] is chunks[n-1]."""
    ordered = sorted(logs, key=lambda log: log.rank)
    if not ordered:
        raise SetupError([f"answer {answer_id} has no retrieval_log rows (no evidence)"])
    ranks = [log.rank for log in ordered]
    if ranks != list(range(1, len(ordered) + 1)):
        raise SetupError([f"answer {answer_id} has ranks {ranks}; citation numbers would not "
                          "map to chunk IDs"])

    chunks = []
    for log in ordered:
        chunk = log.chunk
        if chunk is None:
            raise SetupError([f"answer {answer_id}: chunk {log.chunk_id} (rank {log.rank}) "
                              "no longer exists"])
        chunks.append(RetrievedChunk(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            document=chunk.document.filename if chunk.document is not None else "unknown",
            page=chunk.page_number,
            text=chunk.content,
            similarity=log.similarity if log.similarity is not None else 0.0,
        ))
    return chunks


def load_evidence_sets(db: Session, answer_ids: Sequence[int]) -> dict[int, EvidenceSet]:
    stmt = (
        select(Answer)
        .where(Answer.id.in_(list(answer_ids)))
        .options(
            selectinload(Answer.query),
            selectinload(Answer.retrieval_logs)
            .selectinload(RetrievalLog.chunk)
            .selectinload(DocumentChunk.document),
        )
    )
    found = {answer.id: answer for answer in db.scalars(stmt)}

    problems, sets = [], {}
    for answer_id in answer_ids:
        answer = found.get(answer_id)
        if answer is None:
            problems.append(f"answer {answer_id} not found")
            continue
        try:
            chunks = rebuild_chunks(answer_id, answer.retrieval_logs)
        except SetupError as exc:
            problems.extend(exc.problems)
            continue
        sets[answer_id] = EvidenceSet(answer.id, answer.query_id, answer.query.question,
                                      answer.answer_text, answer.status, chunks)
    if problems:
        raise SetupError(problems)
    return sets


def load_inputs(answer_ids: Sequence[int], negatives: bool) -> dict[int, EvidenceSet]:
    needed = list(answer_ids)
    if negatives:
        needed += [case.evidence_answer_id for case in NEGATIVE_CASES]
    needed = list(dict.fromkeys(needed))

    try:
        with SessionLocal() as db:
            try:
                begin_read_only(db)
                sets = load_evidence_sets(db, needed)
            finally:
                db.rollback()
    except SQLAlchemyError as exc:
        raise SetupError([f"database error: {type(exc).__name__}: {exc}"]) from exc

    missing_text = [f"answer {i} has no answer text (status={sets[i].status})"
                    for i in answer_ids if not (sets[i].answer_text or "").strip()]
    if missing_text:
        raise SetupError(missing_text)
    return sets


# --- independent validation -------------------------------------------------------------

def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).translate(_QUOTE_CHARS)
    return " ".join(value.split()).casefold()


def _is_unit_score(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and 0.0 <= value <= 1.0)


def outcome_label(result: EvaluationResult | None) -> str:
    """evaluator_error is never reported as an ordinary evaluated failure."""
    if result is None or result.failure_type == EVALUATOR_ERROR:
        return OUTCOME_EVALUATOR_ERROR
    return EVALUATED_PASS if result.passed else EVALUATED_FAIL


def expected_failure_type(faithfulness: float, answer_relevance: float,
                          context_relevance: float, threshold: float) -> str | None:
    if faithfulness < threshold:
        return UNSUPPORTED_CLAIM
    if answer_relevance < threshold:
        return MISSING_INFO
    if context_relevance < threshold:
        return IRRELEVANT_RETRIEVAL
    return None


def quote_problem(claim, chunks_by_id: dict[int, RetrievedChunk]) -> str | None:
    """Why the claim's evidence is not present in its referenced retrieved chunk, or None."""
    if claim.evidence_chunk_id is None:
        return "no evidence_chunk_id"
    chunk = chunks_by_id.get(claim.evidence_chunk_id)
    if chunk is None:
        return (f"chunk {claim.evidence_chunk_id} is not among the retrieved chunk IDs "
                f"{sorted(chunks_by_id)}")
    quote = _normalize(claim.evidence_quote or "")
    if not quote:
        return f"no evidence_quote for chunk {claim.evidence_chunk_id}"
    if quote not in _normalize(chunk.text):
        return f"quote not found in chunk {claim.evidence_chunk_id}"
    return None


def validate_result(result: EvaluationResult, chunks: Sequence[RetrievedChunk],
                    threshold: float = PASS_THRESHOLD) -> list[Check]:
    """Re-check an evaluation without relying on the evaluator's own helpers.

    Quote-presence checks only show that a quote exists in the cited chunk; they say nothing
    about whether the quote supports the claim (see `check_negative_case`).
    """
    checks: list[Check] = []

    def add(kind: str, name: str, ok: bool, detail: str = "") -> None:
        checks.append(Check(kind, name, bool(ok), detail))

    scores = {"faithfulness": result.faithfulness,
              "answer_relevance": result.answer_relevance,
              "context_relevance": result.context_relevance}

    if result.failure_type == EVALUATOR_ERROR:
        add(INTEGRITY, "evaluator_error_has_null_scores",
            all(v is None for v in scores.values()), f"scores={scores}")
        add(INTEGRITY, "evaluator_error_has_no_claims", not result.claims,
            f"{len(result.claims)} claim(s)")
        add(INTEGRITY, "evaluator_error_not_passed", result.passed is False)
        add(EVALUATOR, "evaluated", False, result.feedback or "evaluator error")
        return checks

    invalid = {name: value for name, value in scores.items() if not _is_unit_score(value)}
    add(INTEGRITY, "scores_in_range", not invalid, f"invalid scores: {invalid}" if invalid else "")
    add(INTEGRITY, "has_claims", bool(result.claims), f"{len(result.claims)} claim(s)")
    add(INTEGRITY, "llm_called", result.llm_calls >= 1, f"llm_calls={result.llm_calls}")

    counts = Counter(claim.verdict for claim in result.claims)
    unknown = sorted(set(counts) - set(VERDICTS))
    add(INTEGRITY, "verdicts_known", not unknown, f"unknown verdicts: {unknown}" if unknown else "")
    add(INTEGRITY, "claim_counts", sum(counts[v] for v in VERDICTS) == len(result.claims),
        str(dict(counts)))

    if result.claims and _is_unit_score(result.faithfulness):
        expected = (counts[SUPPORTED] + 0.5 * counts[PARTIALLY_SUPPORTED]) / len(result.claims)
        add(INTEGRITY, "faithfulness_recomputed",
            math.isclose(expected, result.faithfulness, abs_tol=1e-9),
            f"expected {expected:.4f}, reported {result.faithfulness:.4f}")

    if not invalid:
        expected_failure = expected_failure_type(*scores.values(), threshold)
        add(INTEGRITY, "failure_type_matches_scores", result.failure_type == expected_failure,
            f"expected {expected_failure}, reported {result.failure_type}")
        add(INTEGRITY, "passed_matches_scores", result.passed == (expected_failure is None),
            f"passed={result.passed}")
    add(INTEGRITY, "failure_type_known",
        result.failure_type is None or result.failure_type in FAILURE_TYPES,
        f"failure_type={result.failure_type}")

    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    for index, claim in enumerate(result.claims, start=1):
        has_evidence = claim.evidence_chunk_id is not None or bool(claim.evidence_quote)
        if claim.verdict in (SUPPORTED, PARTIALLY_SUPPORTED) or has_evidence:
            problem = quote_problem(claim, chunks_by_id)
            add(QUOTE_PRESENCE, f"claim_{index}_evidence", problem is None,
                problem or f"quote present in chunk {claim.evidence_chunk_id}")
    return checks


def check_negative_case(case: NegativeCase, result: EvaluationResult | None) -> list[Check]:
    """Expectation and semantic-support checks for a controlled negative case."""
    if outcome_label(result) == OUTCOME_EVALUATOR_ERROR:
        return []

    checks: list[Check] = []

    def add(kind: str, name: str, ok: bool, detail: str = "") -> None:
        checks.append(Check(kind, name, bool(ok), detail))

    if case.expect_pass:
        add(EXPECTATION, "passes", result.passed, f"failure_type={result.failure_type}")
    else:
        add(EXPECTATION, "fails", not result.passed, f"passed={result.passed}")
        add(EXPECTATION, "failure_type_allowed",
            result.failure_type in case.allowed_failure_types,
            f"got {result.failure_type}, allowed {list(case.allowed_failure_types)}")
    if case.expect_low_context_relevance:
        add(EXPECTATION, "context_relevance_below_threshold",
            _is_unit_score(result.context_relevance) and result.context_relevance < PASS_THRESHOLD,
            f"context_relevance={result.context_relevance}")

    if not (case.all_claims_false or case.false_claim_patterns):
        return checks

    patterns = [re.compile(pattern, re.IGNORECASE) for pattern in case.false_claim_patterns]
    false_claims = [claim for claim in result.claims
                    if case.all_claims_false or any(p.search(claim.claim_text) for p in patterns)]
    add(EXPECTATION, "false_claim_identified", bool(false_claims),
        "" if false_claims else
        f"no claim matched {case.false_claim_patterns}; review the claims manually")

    for claim in false_claims:
        detail = f"{claim.verdict}: {claim.claim_text!r}"
        if claim.verdict == SUPPORTED and claim.evidence_error is None and claim.evidence_quote:
            detail += (f"; its quote is present in chunk {claim.evidence_chunk_id}, but quote "
                       "presence is not proof of entailment")
        add(SEMANTIC_SUPPORT, "false_claim_not_supported",
            claim.verdict in case.allowed_false_verdicts,
            f"{detail} (allowed: {list(case.allowed_false_verdicts)})")
    return checks


# --- evaluation and reporting -----------------------------------------------------------

def run_evaluation(question: str, answer: str,
                   chunks: Sequence[RetrievedChunk]) -> tuple[EvaluationResult | None, str | None]:
    try:
        return evaluate_answer(question, answer, chunks), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def chunk_summary(chunks: Sequence[RetrievedChunk]) -> list[dict]:
    return [{"rank": rank, "chunk_id": c.chunk_id, "document": c.document, "page": c.page,
             "similarity": c.similarity} for rank, c in enumerate(chunks, start=1)]


def evaluation_record(result: EvaluationResult | None, error: str | None,
                      chunks: Sequence[RetrievedChunk]) -> dict:
    if result is None:
        checks = [Check(EVALUATOR, "evaluated", False, f"evaluate_answer raised {error}")]
        return {"outcome": OUTCOME_EVALUATOR_ERROR, "exception": error, "scores": None,
                "passed": None, "failure_type": None, "feedback": None, "claims": [],
                "verdict_counts": {}, "usage": None, "checks": checks}

    rank_by_id = {c.chunk_id: rank for rank, c in enumerate(chunks, start=1)}
    return {
        "outcome": outcome_label(result),
        "scores": {"faithfulness": result.faithfulness,
                   "answer_relevance": result.answer_relevance,
                   "context_relevance": result.context_relevance},
        "passed": result.passed,
        "failure_type": result.failure_type,
        "feedback": result.feedback,
        "claims": [
            {"index": index, "claim_text": c.claim_text, "verdict": c.verdict,
             "claude_verdict": c.claude_verdict, "evidence_chunk_id": c.evidence_chunk_id,
             "evidence_rank": rank_by_id.get(c.evidence_chunk_id),
             "evidence_quote": c.evidence_quote, "evidence_error": c.evidence_error}
            for index, c in enumerate(result.claims, start=1)
        ],
        "verdict_counts": dict(Counter(c.verdict for c in result.claims)),
        "usage": {"model": result.model, "input_tokens": result.input_tokens,
                  "output_tokens": result.output_tokens, "latency_ms": result.latency_ms,
                  "llm_calls": result.llm_calls},
        "checks": validate_result(result, chunks),
    }


def finalize(record: dict) -> dict:
    checks = record.pop("checks")
    record["ok"] = all(check.ok for check in checks)
    record["failed_checks"] = [asdict(check) for check in checks if not check.ok]
    record["checks_run"] = len(checks)
    return record


def evaluate_saved(evidence: EvidenceSet) -> dict:
    result, error = run_evaluation(evidence.question, evidence.answer_text, evidence.chunks)
    record = {
        "answer_id": evidence.answer_id,
        "query_id": evidence.query_id,
        "question": evidence.question,
        "answer_status": evidence.status,
        "legacy_refusal_text": is_refusal(evidence.answer_text),
        "answer_text": evidence.answer_text,
        "chunks": chunk_summary(evidence.chunks),
        **evaluation_record(result, error, evidence.chunks),
    }
    return finalize(record)


def evaluate_negative(case: NegativeCase, evidence: EvidenceSet) -> dict:
    result, error = run_evaluation(case.question, case.answer, evidence.chunks)
    record = {
        "case": case.name,
        "description": case.description,
        "question": case.question,
        "answer_text": case.answer,
        "evidence_answer_id": evidence.answer_id,
        "expect_pass": case.expect_pass,
        "allowed_failure_types": list(case.allowed_failure_types),
        "chunks": chunk_summary(evidence.chunks),
        **evaluation_record(result, error, evidence.chunks),
    }
    record["checks"] += check_negative_case(case, result)
    return finalize(record)


def summarize(records: Sequence[dict]) -> dict:
    def label(record: dict) -> str:
        return record.get("case") or f"answer {record['answer_id']}"

    def with_failed(kind: str) -> list[str]:
        return [label(r) for r in records if any(c["kind"] == kind for c in r["failed_checks"])]

    return {
        "evaluations": len(records),
        "outcomes": dict(Counter(r["outcome"] for r in records)),
        "evaluator_errors": [label(r) for r in records if r["outcome"] == OUTCOME_EVALUATOR_ERROR],
        "integrity_failures": with_failed(INTEGRITY),
        "quote_presence_failures": with_failed(QUOTE_PRESENCE),
        "semantic_support_failures": with_failed(SEMANTIC_SUPPORT),
        "expectation_failures": with_failed(EXPECTATION),
        "ok": all(r["ok"] for r in records),
    }


def write_report(report: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"sanity_{datetime.now():%Y%m%d_%H%M%S}"
    for suffix in ("", *(f"_{n}" for n in range(1, 100))):
        path = out_dir / f"{stem}{suffix}.json"
        try:
            with path.open("x", encoding="utf-8") as handle:
                json.dump(report, handle, indent=2, ensure_ascii=False)
            return path
        except FileExistsError:
            continue
    raise RuntimeError(f"could not find an unused report name in {out_dir}")


def print_record(record: dict) -> None:
    name = record.get("case") or f"answer {record['answer_id']}"
    scores = record["scores"]
    if scores is None or record["outcome"] == OUTCOME_EVALUATOR_ERROR:
        line = f"[{name}] {record['outcome']}: {record.get('exception') or record['feedback']}"
    else:
        counts = record["verdict_counts"]
        line = (f"[{name}] {record['outcome']} failure_type={record['failure_type']} "
                f"faith={scores['faithfulness']:.2f} ans={scores['answer_relevance']:.2f} "
                f"ctx={scores['context_relevance']:.2f} claims={len(record['claims'])} "
                f"(S{counts.get(SUPPORTED, 0)} P{counts.get(PARTIALLY_SUPPORTED, 0)} "
                f"U{counts.get(UNSUPPORTED, 0)})")
    if record.get("legacy_refusal_text"):
        line += " [legacy refusal text]"
    print(line)
    for check in record["failed_checks"]:
        print(f"    FAIL {check['kind']}/{check['name']}: {check['detail']}")


def print_selection(answer_ids: Sequence[int], negatives: bool,
                    sets: dict[int, EvidenceSet]) -> None:
    for answer_id in answer_ids:
        evidence = sets[answer_id]
        mapping = ", ".join(f"[{rank}]={c.chunk_id}" for rank, c in enumerate(evidence.chunks, 1))
        cited = parse_citations(evidence.answer_text or "", len(evidence.chunks))
        flags = []
        if evidence.status != ANSWERED:
            flags.append(f"status={evidence.status}")
        if is_refusal(evidence.answer_text or ""):
            flags.append("legacy refusal text")
        print(f"answer {answer_id} (query {evidence.query_id}): {evidence.question!r}"
              f"{' [' + '; '.join(flags) + ']' if flags else ''}")
        print(f"    evidence {mapping}; cited {cited}")
    if negatives:
        for case in NEGATIVE_CASES:
            ids = [c.chunk_id for c in sets[case.evidence_answer_id].chunks]
            print(f"negative {case.name}: evidence from answer {case.evidence_answer_id} {ids}")


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only evaluator sanity run. Real modes call Claude and consume API "
                    "credits; --dry-run makes no Claude calls.")
    parser.add_argument("--answers", type=int, nargs="+", metavar="ID",
                        help=f"saved answer IDs (default: {' '.join(map(str, DEFAULT_ANSWER_IDS))})")
    parser.add_argument("--negatives", action="store_true",
                        help="also evaluate the controlled negative cases")
    parser.add_argument("--dry-run", action="store_true",
                        help="load and print the selection only; zero Claude calls")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help=f"report directory (default: {DEFAULT_OUT})")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run_saved = args.answers is not None or not args.negatives
    answer_ids = list(dict.fromkeys(args.answers or DEFAULT_ANSWER_IDS)) if run_saved else []

    try:
        sets = load_inputs(answer_ids, args.negatives)
    except SetupError as exc:
        for problem in exc.problems:
            print(f"[SETUP ERROR] {problem}")
        print("No Claude calls were made.")
        return 2

    print_selection(answer_ids, args.negatives, sets)
    total = len(answer_ids) + (len(NEGATIVE_CASES) if args.negatives else 0)
    if args.dry_run:
        print(f"\n[DRY RUN] No Claude calls were made. A real run would perform {total} "
              f"evaluation(s), each making 1-2 Claude calls ({settings.claude_model}).")
        return 0

    print(f"\n[COST] Running {total} real evaluation(s) with {settings.claude_model}; each makes "
          "1-2 Claude calls and consumes API credits. Nothing is written to the database.\n")
    saved_records = [evaluate_saved(sets[answer_id]) for answer_id in answer_ids]
    negative_records = ([evaluate_negative(case, sets[case.evidence_answer_id])
                         for case in NEGATIVE_CASES] if args.negatives else [])
    records = saved_records + negative_records
    for record in records:
        print_record(record)

    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "read_only": True,
        "claude_model": settings.claude_model,
        "pass_threshold": PASS_THRESHOLD,
        "note": ("quote_presence checks only confirm a quote occurs in its cited chunk; "
                 "semantic_support checks (negative cases) test whether false claims were "
                 "still judged supported."),
        "saved_answers": saved_records,
        "negatives": negative_records,
        "summary": summarize(records),
    }
    path = write_report(report, args.out)
    summary = report["summary"]
    print(f"\nOutcomes: {summary['outcomes']}")
    for key in ("evaluator_errors", "integrity_failures", "quote_presence_failures",
                "semantic_support_failures", "expectation_failures"):
        if summary[key]:
            print(f"{key}: {summary[key]}")
    print(f"Report: {path}")
    print("[OK] All sanity checks passed." if summary["ok"] else "[FAIL] Some sanity checks failed.")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
