"""RELI-RAG Day 3: offline sanity tests for evaluator evidence checks and the sanity runner.

Usage (from the project root or backend/):
    python backend/test_evaluator_sanity.py

Offline: Claude is mocked, and `sanity_evaluate_saved.py` runs against an in-memory SQLite
database, so no API key, API credits, or PostgreSQL are needed.
Exits with status 0 when all tests pass, 1 otherwise.
"""

import contextlib
import dataclasses
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Must be set before `app` is imported so the app never connects to the real database.
os.environ["DATABASE_URL"] = "sqlite://"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import sanity_evaluate_saved as sanity  # noqa: E402
from app.db import Base  # noqa: E402
from app.models import Answer, Document, DocumentChunk, Evaluation, Query, RetrievalLog  # noqa: E402
from app.services.evaluator import (  # noqa: E402
    EVALUATOR_ERROR,
    MISSING_INFO,
    PARTIALLY_SUPPORTED,
    SUPPORTED,
    UNSUPPORTED,
    UNSUPPORTED_CLAIM,
    evaluate_answer,
)
from app.services.llm import LLMError, LLMResult  # noqa: E402
from app.services.retrieval import RetrievedChunk  # noqa: E402

MODEL = "claude-test-model"
QUESTION = "What is the main difference between TCP and UDP?"

# Text of benchmark chunks 97, 98 and 128 as stored by ingestion (98 overlaps the end of 97).
CHUNK_97 = (
    "RELI-RAG Benchmark Reference \u2022 Demo dataset Page 4 03. TCP and UDP TCP provides a "
    "reliable, ordered byte stream using connection establishment, sequence numbers, "
    "acknowledgements, retransmission, and flow control. UDP sends independent datagrams "
    "without built-in delivery guarantees or ordering. DNS queries often use UDP, while "
    "applications may use TCP for larger responses or specific operational needs. The "
    "application determines which transport is appropriate."
)
CHUNK_98 = (
    "atagrams without built-in delivery guarantees or ordering. \u2022 DNS queries often use "
    "UDP, while applications may use TCP for larger responses or specific operational needs. "
    "Evaluation note: A supported answer should stay within these statements, avoid adding "
    "ungrounded specifics, and identify when the source does not provide enough information."
)
CHUNK_128 = (
    "n endpoint tool is not a guarantee of safety; suspicious behavior still requires "
    "investigation and response."
)
CHUNKS = [
    RetrievedChunk(chunk_id=97, document_id=8, document="benchmark.pdf", page=4,
                   text=CHUNK_97, similarity=0.71),
    RetrievedChunk(chunk_id=98, document_id=8, document="benchmark.pdf", page=4,
                   text=CHUNK_98, similarity=0.55),
]
UDP_CASE = next(c for c in sanity.NEGATIVE_CASES if c.name == "udp_guarantees_delivery")


def llm_result(text: str) -> LLMResult:
    return LLMResult(text=text, model=MODEL, input_tokens=300, output_tokens=80,
                     latency_ms=5, stop_reason="end_turn", attempts=1)


def claim(text: str, verdict: str, chunk_id: int | None, quote: str | None) -> dict:
    return {"claim_text": text, "verdict": verdict, "evidence_chunk_id": chunk_id,
            "evidence_quote": quote}


def reply(claims: list[dict], answer_relevance: float = 0.9,
          context_relevance: float = 0.9) -> str:
    return json.dumps({"claims": claims, "answer_relevance": answer_relevance,
                       "context_relevance": context_relevance, "feedback": "Checked."})


TCP_CLAIM = claim("TCP provides a reliable, ordered byte stream.", SUPPORTED, 97,
                  "TCP provides a reliable, ordered byte stream")


def evaluate(*texts: str, chunks=CHUNKS, answer: str = "UDP guarantees delivery [1]."):
    """evaluate_answer with Claude returning `texts` in order; returns (result, Claude mock)."""
    with patch("app.services.evaluator.call_claude") as claude:
        claude.side_effect = [llm_result(text) for text in texts]
        result = evaluate_answer(QUESTION, answer, chunks)
    return result, claude


def failed(checks, kind=None):
    return [c for c in checks if not c.ok and (kind is None or c.kind == kind)]


class EvidenceVerificationTest(unittest.TestCase):
    def assert_downgraded(self, result, index: int, error_fragment: str) -> None:
        bad = result.claims[index]
        self.assertEqual(bad.verdict, UNSUPPORTED)
        self.assertIsNone(bad.evidence_chunk_id)
        self.assertIsNone(bad.evidence_quote)
        self.assertIn(error_fragment, bad.evidence_error)

    def test_fabricated_quote_is_unsupported(self):
        result, _ = evaluate(reply([
            claim("UDP guarantees delivery.", SUPPORTED, 97, "UDP guarantees delivery"),
        ]))

        self.assert_downgraded(result, 0, "does not appear in chunk 97")
        self.assertEqual(result.claims[0].claude_verdict, SUPPORTED)
        self.assertEqual(result.faithfulness, 0.0)
        self.assertEqual(result.failure_type, UNSUPPORTED_CLAIM)
        self.assertEqual(sanity.outcome_label(result), sanity.EVALUATED_FAIL)

    def test_quote_from_wrong_chunk_is_unsupported(self):
        quote = "avoid adding ungrounded specifics"
        self.assertNotIn(quote, CHUNK_97)

        wrong, _ = evaluate(reply([claim("Answers avoid ungrounded specifics.", SUPPORTED, 97,
                                         quote)]))
        right, _ = evaluate(reply([claim("Answers avoid ungrounded specifics.", SUPPORTED, 98,
                                         quote)]))

        self.assert_downgraded(wrong, 0, "does not appear in chunk 97")
        self.assertEqual(right.claims[0].verdict, SUPPORTED)

    def test_unknown_chunk_id_is_unsupported(self):
        result, _ = evaluate(reply([
            claim("Endpoint tools do not guarantee safety.", SUPPORTED, 128,
                  "not a guarantee of safety"),
        ]))
        self.assert_downgraded(result, 0, "not one of the retrieved chunks")

    def test_missing_evidence_is_unsupported(self):
        cases = {
            "no chunk and no quote": (SUPPORTED, None, None, "no evidence given"),
            "chunk without quote": (SUPPORTED, 97, None, "no evidence_quote"),
            "quote without chunk": (SUPPORTED, None, "UDP sends independent datagrams",
                                    "without evidence_chunk_id"),
            "blank quote, partial": (PARTIALLY_SUPPORTED, 97, "   ", "no evidence_quote"),
        }
        for name, (verdict, chunk_id, quote, fragment) in cases.items():
            with self.subTest(name):
                result, _ = evaluate(reply([claim("UDP sends datagrams.", verdict, chunk_id,
                                                  quote)]))
                self.assert_downgraded(result, 0, fragment)
                self.assertEqual(result.faithfulness, 0.0)

    def test_invalid_evidence_never_increases_faithfulness(self):
        honest, _ = evaluate(reply([TCP_CLAIM, claim("UDP guarantees delivery.", UNSUPPORTED,
                                                     None, None)]))
        inflated, _ = evaluate(reply([TCP_CLAIM, claim("UDP guarantees delivery.", SUPPORTED,
                                                       97, "UDP guarantees delivery")]))

        self.assertEqual(honest.faithfulness, 0.5)
        self.assertEqual(inflated.faithfulness, 0.5)
        self.assertEqual([c.verdict for c in inflated.claims], [SUPPORTED, UNSUPPORTED])


class KnownLimitationTest(unittest.TestCase):
    """Quote verification proves presence, not entailment.

    The evaluator only checks that an evidence quote occurs in the cited retrieved chunk.
    If Claude marks a false claim as supported and cites a genuine but irrelevant quote,
    the claim stays supported. The sanity runner reports this as a semantic-support
    failure for negative cases instead of treating quote presence as proof.
    """

    def udp_supported_with_genuine_quote(self):
        return evaluate(reply([
            claim("UDP guarantees delivery.", SUPPORTED, 97, "UDP sends independent datagrams"),
        ]))[0]

    def test_genuine_quote_passes_presence_check_without_entailment(self):
        result = self.udp_supported_with_genuine_quote()

        self.assertEqual(result.claims[0].verdict, SUPPORTED)
        self.assertIsNone(result.claims[0].evidence_error)
        self.assertEqual(result.faithfulness, 1.0)
        self.assertTrue(result.passed)
        self.assertEqual(failed(sanity.validate_result(result, CHUNKS)), [])

    def test_sanity_runner_flags_it_as_semantic_support_failure(self):
        result = self.udp_supported_with_genuine_quote()

        semantic = failed(sanity.check_negative_case(UDP_CASE, result), sanity.SEMANTIC_SUPPORT)
        self.assertEqual(len(semantic), 1)
        self.assertIn("not proof of entailment", semantic[0].detail)
        self.assertIn("chunk 97", semantic[0].detail)

    def test_contradicted_claim_judged_unsupported_passes_semantic_check(self):
        result, _ = evaluate(reply([claim("UDP guarantees delivery.", UNSUPPORTED, None, None)]))

        self.assertEqual(failed(sanity.check_negative_case(UDP_CASE, result)), [])
        self.assertEqual(failed(sanity.validate_result(result, CHUNKS)), [])

    def test_unmatched_false_claim_needs_manual_review(self):
        result, _ = evaluate(reply([claim("UDP ensures arrival.", SUPPORTED, 97,
                                          "UDP sends independent datagrams")]))

        names = [c.name for c in failed(sanity.check_negative_case(UDP_CASE, result))]
        self.assertIn("false_claim_identified", names)


class FailureDistinctionTest(unittest.TestCase):
    def assert_evaluator_error(self, result) -> None:
        self.assertEqual(sanity.outcome_label(result), sanity.OUTCOME_EVALUATOR_ERROR)
        self.assertEqual(result.failure_type, EVALUATOR_ERROR)
        self.assertFalse(result.passed)
        self.assertIsNone(result.faithfulness)
        self.assertIsNone(result.answer_relevance)
        self.assertIsNone(result.context_relevance)
        self.assertEqual(result.claims, [])

        checks = sanity.validate_result(result, CHUNKS)
        self.assertEqual(failed(checks, sanity.INTEGRITY), [])
        self.assertEqual([c.name for c in failed(checks)], ["evaluated"])
        self.assertEqual(sanity.check_negative_case(UDP_CASE, result), [])

    def test_evaluator_failures_are_evaluator_errors(self):
        failures = {
            "invalid JSON twice": ["not json", "still not json"],
            "LLMError": LLMError("overloaded"),
            "unwrapped TypeError": TypeError("Could not resolve authentication method"),
        }
        for name, side_effect in failures.items():
            with self.subTest(name), patch("app.services.evaluator.call_claude") as claude:
                claude.side_effect = ([llm_result(t) for t in side_effect]
                                      if isinstance(side_effect, list) else side_effect)
                self.assert_evaluator_error(evaluate_answer(QUESTION, "UDP is fast [1].", CHUNKS))

    def test_evaluated_failure_has_numeric_scores_and_failure_type(self):
        result, _ = evaluate(reply([TCP_CLAIM], answer_relevance=0.4),
                             answer="TCP provides a reliable, ordered byte stream [1].")

        self.assertEqual(sanity.outcome_label(result), sanity.EVALUATED_FAIL)
        self.assertEqual(result.failure_type, MISSING_INFO)
        for score in (result.faithfulness, result.answer_relevance, result.context_relevance):
            self.assertIsInstance(score, float)
        self.assertEqual(failed(sanity.validate_result(result, CHUNKS)), [])

    def test_runner_reports_raised_evaluator_exception_as_evaluator_error(self):
        with patch.object(sanity, "evaluate_answer", side_effect=RuntimeError("boom")):
            result, error = sanity.run_evaluation(QUESTION, "UDP is fast [1].", CHUNKS)
        record = sanity.finalize(sanity.evaluation_record(result, error, CHUNKS))

        self.assertEqual(record["outcome"], sanity.OUTCOME_EVALUATOR_ERROR)
        self.assertIsNone(record["scores"])
        self.assertEqual([c["kind"] for c in record["failed_checks"]], [sanity.EVALUATOR])

    def test_validator_flags_inconsistent_results(self):
        good, _ = evaluate(reply([TCP_CLAIM]),
                           answer="TCP provides a reliable, ordered byte stream [1].")
        self.assertEqual(failed(sanity.validate_result(good, CHUNKS)), [])

        bad_quote = dataclasses.replace(good.claims[0], evidence_quote="UDP guarantees delivery")
        tampered = {
            "evaluator_error_has_null_scores": dataclasses.replace(
                good, failure_type=EVALUATOR_ERROR, passed=False),
            "faithfulness_recomputed": dataclasses.replace(good, faithfulness=0.9),
            "scores_in_range": dataclasses.replace(good, answer_relevance=1.5),
            "failure_type_matches_scores": dataclasses.replace(good, context_relevance=0.2),
            "claim_1_evidence": dataclasses.replace(good, claims=[bad_quote]),
        }
        for expected_check, result in tampered.items():
            with self.subTest(expected_check):
                names = [c.name for c in failed(sanity.validate_result(result, CHUNKS))]
                self.assertIn(expected_check, names)


class SanityRunnerTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                               poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        self.Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

        with self.Session() as db:
            document = Document(id=8, filename="benchmark.pdf", total_pages=10, total_chunks=4)
            chunks = {
                cid: DocumentChunk(id=cid, document=document, page_number=4, chunk_index=i,
                                   content=content)
                for i, (cid, content) in enumerate(
                    [(97, CHUNK_97), (98, CHUNK_98), (128, CHUNK_128)])
            }
            db.add(document)
            db.add_all(chunks.values())

            def saved(answer_id, text, status, logs):
                query = Query(id=answer_id, question=QUESTION, mode="basic", final_status=status)
                answer = Answer(id=answer_id, query=query, attempt_number=1, answer_text=text,
                                status=status, model=MODEL)
                db.add_all([query, answer])
                db.flush()
                db.add_all(RetrievalLog(answer_id=answer_id, chunk_id=cid, rank=rank,
                                        similarity=0.5) for rank, cid in logs)

            # Logs inserted out of rank order on purpose.
            saved(7, "TCP provides a reliable, ordered byte stream [1].", "ANSWERED",
                  [(2, 98), (1, 97)])
            saved(15, "INSUFFICIENT_EVIDENCE  The passages cover attachments [1].", "ANSWERED",
                  [(1, 128)])
            saved(30, None, "INSUFFICIENT_EVIDENCE", [(1, 97)])
            saved(31, "Answer without evidence.", "ANSWERED", [])
            saved(32, "Answer with a rank gap [1].", "ANSWERED", [(1, 97), (3, 98)])
            db.commit()

        session_patch = patch.object(sanity, "SessionLocal", self.Session)
        session_patch.start()
        self.addCleanup(session_patch.stop)

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)

    def run_main(self, *argv: str, claude_side_effect=None):
        output = io.StringIO()
        with patch("app.services.evaluator.call_claude") as claude, \
             contextlib.redirect_stdout(output):
            if claude_side_effect is not None:
                claude.side_effect = claude_side_effect
            code = sanity.main([*argv, "--out", str(self.out)])
        return code, output.getvalue(), claude

    def db_snapshot(self):
        with self.Session() as db:
            return (db.scalar(select(func.count()).select_from(Evaluation)),
                    db.scalars(select(Answer.answer_text).order_by(Answer.id)).all(),
                    db.scalar(select(func.count()).select_from(RetrievalLog)))

    def test_rebuilds_chunks_in_rank_order(self):
        sets = sanity.load_inputs([7], negatives=False)
        self.assertEqual([c.chunk_id for c in sets[7].chunks], [97, 98])
        self.assertEqual(sets[7].question, QUESTION)

    def test_dry_run_makes_no_claude_calls_and_writes_nothing(self):
        before = self.db_snapshot()
        code, output, claude = self.run_main("--dry-run", "--answers", "7", "15", "--negatives")

        self.assertEqual(code, 0)
        claude.assert_not_called()
        self.assertIn("[1]=97, [2]=98; cited [1]", output)
        self.assertIn("legacy refusal text", output)
        self.assertIn("[DRY RUN] No Claude calls were made", output)
        self.assertIn("8 evaluation(s)", output)
        self.assertEqual(list(self.out.iterdir()), [])
        self.assertEqual(self.db_snapshot(), before)

    def test_unloadable_selection_fails_before_claude(self):
        cases = {
            "missing answer": ("999", "answer 999 not found"),
            "no answer text": ("30", "answer 30 has no answer text"),
            "no evidence": ("31", "answer 31 has no retrieval_log rows"),
            "rank gap": ("32", "answer 32 has ranks [1, 3]; citation numbers would not map"),
        }
        for name, (answer_id, message) in cases.items():
            with self.subTest(name):
                code, output, claude = self.run_main("--answers", "7", answer_id)
                self.assertEqual(code, 2)
                self.assertIn(f"[SETUP ERROR] {message}", output)
                claude.assert_not_called()
                self.assertEqual(list(self.out.iterdir()), [])

    def test_database_error_fails_safely(self):
        error = OperationalError("SELECT 1", {}, Exception("connection refused"))
        with patch.object(sanity, "SessionLocal", side_effect=error):
            code, output, claude = self.run_main("--answers", "7")

        self.assertEqual(code, 2)
        self.assertIn("[SETUP ERROR] database error: OperationalError", output)
        claude.assert_not_called()

    def test_real_run_writes_report_and_leaves_database_unchanged(self):
        before = self.db_snapshot()
        code, output, claude = self.run_main(
            "--answers", "7", claude_side_effect=[llm_result(reply([TCP_CLAIM]))])

        self.assertEqual(code, 0, output)
        claude.assert_called_once()
        self.assertIn("[COST]", output)
        [report_path] = list(self.out.iterdir())
        self.assertRegex(report_path.name, r"^sanity_\d{8}_\d{6}\.json$")
        report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertTrue(report["read_only"])
        [record] = report["saved_answers"]
        self.assertEqual(record["outcome"], sanity.EVALUATED_PASS)
        self.assertEqual(record["scores"], {"faithfulness": 1.0, "answer_relevance": 0.9,
                                            "context_relevance": 0.9})
        self.assertEqual([c["chunk_id"] for c in record["chunks"]], [97, 98])
        self.assertEqual(record["claims"][0]["evidence_chunk_id"], 97)
        self.assertEqual(record["claims"][0]["evidence_rank"], 1)
        self.assertEqual(record["usage"]["input_tokens"], 300)
        self.assertTrue(record["ok"])
        self.assertTrue(report["summary"]["ok"])
        self.assertEqual(self.db_snapshot(), before)

    def test_negatives_separate_semantic_failures_from_evaluator_errors(self):
        def fake_claude(prompt, **kwargs):
            if "<answer>\nUDP guarantees delivery [1].\n</answer>" in prompt:
                return llm_result(reply([claim("UDP guarantees delivery.", SUPPORTED, 97,
                                               "UDP sends independent datagrams")]))
            if "chunk_id=128" in prompt:
                return llm_result("not json")
            return llm_result(reply([claim("Some claim.", UNSUPPORTED, None, None)]))

        before = self.db_snapshot()
        code, output, _ = self.run_main("--negatives", claude_side_effect=fake_claude)

        self.assertEqual(code, 1)
        report = json.loads(next(self.out.iterdir()).read_text(encoding="utf-8"))
        self.assertEqual(report["saved_answers"], [])
        records = {r["case"]: r for r in report["negatives"]}
        self.assertEqual(set(records), {c.name for c in sanity.NEGATIVE_CASES})

        udp = records["udp_guarantees_delivery"]
        self.assertEqual(udp["outcome"], sanity.EVALUATED_PASS)
        self.assertIn(sanity.SEMANTIC_SUPPORT, [c["kind"] for c in udp["failed_checks"]])

        wrong = records["wrong_evidence"]
        self.assertEqual(wrong["outcome"], sanity.OUTCOME_EVALUATOR_ERROR)
        self.assertEqual([c["kind"] for c in wrong["failed_checks"]], [sanity.EVALUATOR])

        summary = report["summary"]
        self.assertIn("udp_guarantees_delivery", summary["semantic_support_failures"])
        self.assertEqual(summary["evaluator_errors"], ["wrong_evidence"])
        self.assertNotIn("wrong_evidence", summary["expectation_failures"])
        self.assertEqual(self.db_snapshot(), before)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
