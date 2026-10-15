"""RELI-RAG Day 4: offline tests for the corrector services (query rewrite, strict regeneration).

Usage (from the project root or backend/):
    python backend/test_corrector.py

Offline: Claude (rewriter and generator) and retrieval are mocked, and attempts are stored in an
in-memory SQLite database, so no API calls are made and the real database is never touched.
Exits with status 0 when all tests pass, 1 otherwise.
"""

import math
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# Must be set before `app` is imported so the app never connects to the real database.
os.environ["DATABASE_URL"] = "sqlite://"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import Base  # noqa: E402
from app.models import (  # noqa: E402
    Answer,
    Claim,
    Document,
    DocumentChunk,
    Evaluation,
    Query,
    RetrievalLog,
)
from app.services import generator  # noqa: E402
from app.services.corrector import (  # noqa: E402
    FAILURE_DESCRIPTIONS,
    MAX_REWRITE_CHARS,
    RETRY_TOP_K,
    REWRITE,
    REWRITE_MAX_TOKENS,
    REWRITE_SYSTEM_PROMPT,
    STRICT,
    choose_correction,
    rejected_claim_texts,
    rewrite_query,
)
from app.services.evaluator import (  # noqa: E402
    EVALUATOR_ERROR,
    IRRELEVANT_RETRIEVAL,
    MISSING_INFO,
    PARTIALLY_SUPPORTED,
    SUPPORTED,
    UNSUPPORTED,
    UNSUPPORTED_CLAIM,
)
from app.services.generator import (  # noqa: E402
    ANSWERED,
    MAX_STRICT_CLAIM_CHARS,
    MAX_STRICT_CLAIMS,
    build_strict_instructions,
    generate_answer,
)
from app.services.llm import LLMError, LLMResult  # noqa: E402
from app.services.query_pipeline import (  # noqa: E402
    ERROR,
    create_attempt_with_same_chunks,
    run_rewrite_attempt,
    run_strict_attempt,
)
from app.services.retrieval import RetrievedChunk, load_logged_chunks  # noqa: E402
from app.services.similarity_gate import INSUFFICIENT_EVIDENCE  # noqa: E402

MODEL = "claude-test-model"
PINNED_SETTINGS = {
    "claude_model": MODEL,
    "claude_max_tokens": 1024,
    "similarity_gate": 0.30,
    "evaluator_pass_threshold": 0.80,
}

QUESTION = "What is the allowance for item A?"
FEEDBACK = "The passages do not mention the allowance for item A."
FIRST_ANSWER = "Item A has an allowance of 100 units [1]."
REWRITTEN = "allowance amount for item A eligibility limits"
CHUNK_TEXTS = [
    "Section 1. Item A is available to eligible members.",
    "Section 2. Item B has an allowance of 50 units per year.",
    "Section 3. Requests for item A must be submitted in writing.",
]


def llm_result(text: str) -> LLMResult:
    return LLMResult(text=text, model=MODEL, input_tokens=100, output_tokens=20,
                     latency_ms=5, stop_reason="end_turn", attempts=1)


class PinnedSettingsTestCase(unittest.TestCase):
    def setUp(self):
        # `settings` is created once per process and may already hold .env values.
        for name, value in PINNED_SETTINGS.items():
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)


def evaluation(failure_type, context_relevance=0.9, passed=None):
    return SimpleNamespace(passed=failure_type is None if passed is None else passed,
                           failure_type=failure_type, context_relevance=context_relevance)


class ChooseCorrectionTest(PinnedSettingsTestCase):
    def test_retrieval_failures_are_rewritten(self):
        for failure_type in (MISSING_INFO, IRRELEVANT_RETRIEVAL):
            for context in (0.2, 0.95, None):
                with self.subTest(failure_type=failure_type, context=context):
                    self.assertEqual(choose_correction(evaluation(failure_type, context)), REWRITE)

    def test_unsupported_claim_with_adequate_context_is_strict(self):
        for context in (0.80, 0.9, 1.0):
            with self.subTest(context=context):
                self.assertEqual(choose_correction(evaluation(UNSUPPORTED_CLAIM, context)), STRICT)

    def test_unsupported_claim_with_weak_or_unknown_context_is_rewritten(self):
        for context in (0.79, 0.37, 0.0, None, math.nan):
            with self.subTest(context=context):
                self.assertEqual(choose_correction(evaluation(UNSUPPORTED_CLAIM, context)), REWRITE)

    def test_no_correction(self):
        cases = {
            "no evaluation": None,
            "passed": evaluation(None),
            "evaluator error": evaluation(EVALUATOR_ERROR, None, passed=False),
            "unknown failure type": evaluation("something_else", passed=False),
        }
        for name, case in cases.items():
            with self.subTest(name):
                self.assertIsNone(choose_correction(case))

    def test_threshold_defaults_to_evaluator_setting_and_can_be_overridden(self):
        weak_for_strict_setting = evaluation(UNSUPPORTED_CLAIM, 0.9)
        with patch.object(settings, "evaluator_pass_threshold", 0.95):
            self.assertEqual(choose_correction(weak_for_strict_setting), REWRITE)
        self.assertEqual(choose_correction(weak_for_strict_setting, threshold=0.9), STRICT)

    def test_rejected_claim_texts(self):
        claims = [SimpleNamespace(claim_text="a", verdict=SUPPORTED),
                  SimpleNamespace(claim_text="b", verdict=UNSUPPORTED),
                  SimpleNamespace(claim_text="c", verdict=PARTIALLY_SUPPORTED),
                  SimpleNamespace(claim_text="d", verdict=None)]
        self.assertEqual(rejected_claim_texts(claims), ["b", "c"])


class RewriteQueryTest(PinnedSettingsTestCase):
    def rewrite(self, reply=None, *, error=None, feedback=FEEDBACK, failure_type=MISSING_INFO,
                question=QUESTION):
        with patch("app.services.corrector.call_claude") as claude:
            if error is not None:
                claude.side_effect = error
            else:
                claude.return_value = llm_result(reply)
            result = rewrite_query(question, feedback, failure_type=failure_type)
        return result, claude

    def test_valid_rewrite(self):
        result, claude = self.rewrite(REWRITTEN)

        self.assertEqual((result.query, result.rewritten, result.fallback_reason),
                         (REWRITTEN, True, None))
        self.assertEqual(result.llm.model, MODEL)
        claude.assert_called_once()
        prompt = claude.call_args.args[0]
        self.assertIn(QUESTION, prompt)
        self.assertIn(FEEDBACK, prompt)
        self.assertIn(FAILURE_DESCRIPTIONS[MISSING_INFO], prompt)
        self.assertEqual(claude.call_args.kwargs,
                         {"system": REWRITE_SYSTEM_PROMPT, "max_tokens": REWRITE_MAX_TOKENS})

    def test_prompt_describes_failure_type_and_missing_feedback(self):
        _, claude = self.rewrite(REWRITTEN, feedback=None, failure_type=IRRELEVANT_RETRIEVAL)
        prompt = claude.call_args.args[0]
        self.assertIn(FAILURE_DESCRIPTIONS[IRRELEVANT_RETRIEVAL], prompt)
        self.assertIn("None given.", prompt)

    def test_reply_is_cleaned(self):
        cases = {
            f'Search query: "{REWRITTEN}"': REWRITTEN,
            f"\u201c{REWRITTEN}\u201d": REWRITTEN,
            f"  \n{REWRITTEN}   \n\n": REWRITTEN,
            "allowance   for\titem A": "allowance for item A",
            "members' allowance for item A": "members' allowance for item A",
            "x" * MAX_REWRITE_CHARS: "x" * MAX_REWRITE_CHARS,
        }
        for reply, expected in cases.items():
            with self.subTest(reply=reply[:40]):
                result, _ = self.rewrite(reply)
                self.assertEqual((result.query, result.rewritten), (expected, True))

    def test_invalid_reply_falls_back_to_original_question(self):
        cases = {
            "": "empty",
            "  \n\t ": "empty",
            '""': "empty",
            "Query:": "empty",
            f"{REWRITTEN}\nThis query targets the allowance section.": "multiple lines",
            "x" * (MAX_REWRITE_CHARS + 1): "too long",
            QUESTION: "unchanged",
            f"  {QUESTION.upper()}  ": "unchanged",
        }
        for reply, reason in cases.items():
            with self.subTest(reply=reply[:40]):
                result, _ = self.rewrite(reply)
                self.assertEqual((result.query, result.rewritten, result.fallback_reason),
                                 (QUESTION, False, reason))
                self.assertIsNotNone(result.llm)

    def test_claude_failure_falls_back_to_original_question(self):
        for error in (LLMError("overloaded"), TypeError("Could not resolve authentication")):
            with self.subTest(error=type(error).__name__):
                result, claude = self.rewrite(error=error)
                claude.assert_called_once()
                self.assertEqual((result.query, result.rewritten, result.llm),
                                 (QUESTION, False, None))
                self.assertIn("Claude call failed", result.fallback_reason)

    def test_empty_question_is_rejected_without_calling_claude(self):
        with patch("app.services.corrector.call_claude") as claude, \
             self.assertRaises(ValueError):
            rewrite_query("   ", FEEDBACK)
        claude.assert_not_called()


CHUNKS = [RetrievedChunk(chunk_id=i, document_id=1, document="doc.pdf", page=i, text=text,
                         similarity=0.9) for i, text in enumerate(CHUNK_TEXTS, start=1)]


class StrictGenerationTest(PinnedSettingsTestCase):
    def generate(self, **kwargs):
        with patch("app.services.generator.call_claude",
                   return_value=llm_result("Item A is available to eligible members [1].")) as claude:
            result = generate_answer(QUESTION, CHUNKS, **kwargs)
        return result, claude

    def test_default_request_is_unchanged(self):
        for kwargs in ({}, {"strict_instructions": None}, {"strict_instructions": "  \n "}):
            with self.subTest(kwargs=kwargs):
                _, claude = self.generate(**kwargs)
                self.assertEqual(claude.call_args.kwargs["system"], generator.SYSTEM_PROMPT)

    def test_strict_instructions_extend_system_prompt_with_same_context(self):
        instructions = build_strict_instructions(["Item A has an allowance of 100 units."])
        result, claude = self.generate(strict_instructions=instructions)

        self.assertEqual(result.status, ANSWERED)
        system = claude.call_args.kwargs["system"]
        self.assertTrue(system.startswith(generator.SYSTEM_PROMPT))
        self.assertTrue(system.endswith(instructions))
        self.assertIn("- Item A has an allowance of 100 units.", system)
        self.assertEqual(claude.call_args.args[0], generator.build_prompt(QUESTION, CHUNKS))

    def test_build_strict_instructions(self):
        instructions = build_strict_instructions(["  first\n claim ", "", "   ", "second claim"])
        self.assertIn("Rejected claims:\n- first claim\n- second claim\n", instructions)
        self.assertIn(INSUFFICIENT_EVIDENCE, instructions)
        self.assertNotIn("{claims}", instructions)

    def test_build_strict_instructions_without_claims(self):
        instructions = build_strict_instructions([])
        self.assertNotIn("Rejected claims", instructions)
        self.assertIn("State only what the passages say explicitly", instructions)

    def test_build_strict_instructions_caps_claims(self):
        claims = [f"claim {i}" for i in range(MAX_STRICT_CLAIMS + 5)] + ["y" * 10_000]
        instructions = build_strict_instructions(claims)
        self.assertEqual(instructions.count("\n- claim "), MAX_STRICT_CLAIMS)

        long_only = build_strict_instructions(["y" * 10_000])
        self.assertIn("- " + "y" * MAX_STRICT_CLAIM_CHARS + "\n", long_only)
        self.assertNotIn("y" * (MAX_STRICT_CLAIM_CHARS + 1), long_only)

    def test_claim_text_with_braces_is_kept_verbatim(self):
        self.assertIn("- uses {placeholder} syntax", build_strict_instructions(
            ["uses {placeholder} syntax"]))


class AttemptCorrectionTest(PinnedSettingsTestCase):
    """Attempt 2 helpers against a saved, evaluated attempt 1."""

    def setUp(self):
        super().setUp()
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        self.Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

        with self.Session() as db:
            document = Document(filename="handbook.pdf", total_pages=3, total_chunks=3)
            chunks = [DocumentChunk(document=document, page_number=i + 1, chunk_index=i,
                                    content=text) for i, text in enumerate(CHUNK_TEXTS)]
            query = Query(question=QUESTION, mode="reli", final_status=ANSWERED)
            first = Answer(query=query, attempt_number=1, answer_text=FIRST_ANSWER,
                           retrieval_query=QUESTION, status=ANSWERED, model=MODEL,
                           latency_ms=40, input_tokens=500, output_tokens=30)
            db.add_all([document, *chunks, query, first])
            db.flush()
            # Rank order deliberately differs from chunk id order.
            for rank, (chunk, similarity) in enumerate(
                    [(chunks[2], 0.62), (chunks[0], 0.55), (chunks[1], 0.41)], start=1):
                db.add(RetrievalLog(answer=first, chunk_id=chunk.id, rank=rank,
                                    similarity=similarity))
            db.add(Evaluation(
                answer=first, faithfulness=0.5, answer_relevance=0.9, context_relevance=0.85,
                passed=False, failure_type=UNSUPPORTED_CLAIM, feedback=FEEDBACK, model=MODEL,
                latency_ms=20, input_tokens=300, output_tokens=60,
                claims=[Claim(claim_text="Item A is available to eligible members.",
                              verdict=SUPPORTED, evidence_chunk_id=chunks[0].id,
                              evidence_quote="Item A is available to eligible members"),
                        Claim(claim_text="Item A has an allowance of 100 units.",
                              verdict=UNSUPPORTED)],
            ))
            db.commit()
            self.query_id, self.first_id = query.id, first.id
            self.chunk_ids = [chunk.id for chunk in chunks]
            self.ranked_chunk_ids = [self.chunk_ids[2], self.chunk_ids[0], self.chunk_ids[1]]

        self.before = self.snapshot()
        # Strict regeneration and chunk reuse must never retrieve or embed again.
        for target in ("app.services.similarity_gate.retrieve", "app.services.retrieval.embed_query"):
            patcher = patch(target, side_effect=AssertionError(f"{target} must not be called"))
            patcher.start()
            self.addCleanup(patcher.stop)

    def snapshot(self) -> dict:
        with self.Session() as db:
            query = db.get(Query, self.query_id)
            first = db.get(Answer, self.first_id)
            return {
                "final_status": query.final_status,
                "answer": (first.attempt_number, first.status, first.answer_text,
                           first.retrieval_query, first.model, first.latency_ms,
                           first.input_tokens, first.output_tokens),
                "logs": [(log.chunk_id, log.rank, log.similarity) for log in first.retrieval_logs],
                "evaluations": [
                    (e.id, e.passed, e.failure_type, e.faithfulness, e.answer_relevance,
                     e.context_relevance, e.feedback,
                     [(c.claim_text, c.verdict, c.evidence_chunk_id, c.evidence_quote)
                      for c in e.claims])
                    for e in first.evaluations
                ],
            }

    def assert_first_attempt_unchanged(self):
        self.assertEqual(self.snapshot(), self.before)

    def answers(self) -> list[Answer]:
        with self.Session() as db:
            return db.scalars(select(Answer).where(Answer.query_id == self.query_id)
                              .order_by(Answer.attempt_number)).all()

    def logs(self, answer_id: int) -> list[tuple]:
        with self.Session() as db:
            return [(log.chunk_id, log.rank, log.similarity) for log in db.scalars(
                select(RetrievalLog).where(RetrievalLog.answer_id == answer_id)
                .order_by(RetrievalLog.rank))]

    def test_load_logged_chunks_in_rank_order(self):
        with self.Session() as db:
            chunks = load_logged_chunks(db, self.first_id)

        self.assertEqual([c.chunk_id for c in chunks], self.ranked_chunk_ids)
        self.assertEqual([c.similarity for c in chunks], [0.62, 0.55, 0.41])
        self.assertEqual([c.text for c in chunks], [CHUNK_TEXTS[2], CHUNK_TEXTS[0], CHUNK_TEXTS[1]])
        self.assertEqual({(c.document, c.document_id) for c in chunks}, {("handbook.pdf", 1)})
        self.assertEqual([c.page for c in chunks], [3, 1, 2])

    def test_create_attempt_with_same_chunks_copies_logs(self):
        with self.Session() as db:
            source = db.get(Answer, self.first_id)
            attempt = create_attempt_with_same_chunks(db, source, attempt_number=2)
            source_chunks = load_logged_chunks(db, self.first_id)
            second_id = attempt.answer.id

        self.assertEqual(attempt.chunks, source_chunks)
        self.assertEqual(self.logs(second_id), self.logs(self.first_id))
        first, second = self.answers()
        self.assertEqual((second.id, second.attempt_number, second.retrieval_query, second.status,
                          second.answer_text, second.model),
                         (second_id, 2, QUESTION, None, None, None))
        self.assert_first_attempt_unchanged()

    def test_source_without_logged_chunks_is_rejected(self):
        with self.Session() as db:
            source = Answer(query_id=self.query_id, attempt_number=3, status=INSUFFICIENT_EVIDENCE)
            db.add(source)
            db.commit()
            with self.assertRaises(ValueError):
                create_attempt_with_same_chunks(db, source, attempt_number=4)

        self.assertEqual([a.attempt_number for a in self.answers()], [1, 3])
        self.assert_first_attempt_unchanged()

    def run_strict(self, claude_reply=None, claude_error=None):
        with self.Session() as db, \
             patch("app.services.generator.call_claude") as claude:
            if claude_error is not None:
                claude.side_effect = claude_error
            else:
                claude.return_value = llm_result(claude_reply)
            source = db.get(Answer, self.first_id)
            evaluation = source.evaluations[-1]
            rejected = rejected_claim_texts(evaluation.claims)
            if claude_error is not None:
                with self.assertRaises(type(claude_error)):
                    run_strict_attempt(db, source, attempt_number=2, rejected_claims=rejected)
                attempt = None
            else:
                attempt = run_strict_attempt(db, source, attempt_number=2,
                                             rejected_claims=rejected)
            chunks = load_logged_chunks(db, self.first_id)
        return attempt, claude, chunks

    def test_strict_regeneration_reuses_chunks_and_keeps_first_attempt(self):
        strict_answer = "Item A is available to eligible members [2]."
        attempt, claude, chunks = self.run_strict(strict_answer)

        claude.assert_called_once()
        self.assertEqual(claude.call_args.args[0], generator.build_prompt(QUESTION, chunks))
        system = claude.call_args.kwargs["system"]
        self.assertTrue(system.startswith(generator.SYSTEM_PROMPT))
        self.assertIn("- Item A has an allowance of 100 units.", system)
        self.assertNotIn("- Item A is available to eligible members.", system)
        self.assertEqual(attempt.chunks, chunks)

        first, second = self.answers()
        self.assertEqual((second.attempt_number, second.status, second.answer_text, second.model,
                          second.retrieval_query),
                         (2, ANSWERED, strict_answer, MODEL, QUESTION))
        self.assertEqual(self.logs(second.id), self.logs(self.first_id))
        with self.Session() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Evaluation)), 1)
        self.assert_first_attempt_unchanged()

    def test_strict_regeneration_refusal_is_insufficient_evidence(self):
        self.run_strict(INSUFFICIENT_EVIDENCE)

        first, second = self.answers()
        self.assertEqual((second.status, second.answer_text, second.model),
                         (INSUFFICIENT_EVIDENCE, None, MODEL))
        self.assert_first_attempt_unchanged()

    def test_strict_regeneration_claude_error_keeps_first_attempt(self):
        self.run_strict(claude_error=LLMError("overloaded"))

        first, second = self.answers()
        self.assertEqual((second.attempt_number, second.status, second.answer_text), (2, ERROR, None))
        self.assertEqual(self.logs(second.id), self.logs(self.first_id))
        self.assert_first_attempt_unchanged()

    def run_rewrite(self, rewriter, similarity=0.8, generator_reply="Item A is available [1].",
                    attempt_number=2):
        """Run attempt 2 via rewrite with mocked rewriter, retrieval, and generator Claude."""
        retrieved = [RetrievedChunk(chunk_id=self.chunk_ids[0], document_id=1,
                                    document="handbook.pdf", page=1, text=CHUNK_TEXTS[0],
                                    similarity=similarity)]
        with self.Session() as db, \
             patch("app.services.corrector.call_claude") as rewrite_claude, \
             patch("app.services.similarity_gate.retrieve", return_value=retrieved) as retrieve, \
             patch("app.services.generator.call_claude",
                   return_value=llm_result(generator_reply)) as claude:
            if isinstance(rewriter, Exception):
                rewrite_claude.side_effect = rewriter
            else:
                rewrite_claude.return_value = llm_result(rewriter)
            query = db.get(Query, self.query_id)
            attempt = run_rewrite_attempt(db, query, attempt_number=attempt_number,
                                          feedback=FEEDBACK, failure_type=IRRELEVANT_RETRIEVAL)
        return attempt, retrieve, claude

    def test_rewrite_attempt_retrieves_with_rewritten_query_and_larger_k(self):
        attempt, retrieve, claude = self.run_rewrite(REWRITTEN)

        retrieve.assert_called_once()
        self.assertEqual(retrieve.call_args.args[1], REWRITTEN)
        self.assertEqual(retrieve.call_args.kwargs, {"k": RETRY_TOP_K, "document_ids": None})
        self.assertEqual(RETRY_TOP_K, 8)
        self.assertTrue(attempt.rewrite.rewritten)
        self.assertTrue(claude.call_args.args[0].endswith(f"Question: {QUESTION}"))

        first, second = self.answers()
        self.assertEqual((second.attempt_number, second.retrieval_query, second.status),
                         (2, REWRITTEN, ANSWERED))
        self.assertEqual(self.logs(second.id), [(self.chunk_ids[0], 1, 0.8)])
        self.assert_first_attempt_unchanged()

    def test_rejected_rewrite_retrieves_original_question(self):
        for attempt_number, rewriter in enumerate((LLMError("overloaded"), "", QUESTION), start=2):
            with self.subTest(rewriter=rewriter):
                attempt, retrieve, _ = self.run_rewrite(rewriter, attempt_number=attempt_number)

                self.assertEqual(retrieve.call_args.args[1], QUESTION)
                self.assertEqual(retrieve.call_args.kwargs["k"], RETRY_TOP_K)
                self.assertFalse(attempt.rewrite.rewritten)
                self.assertEqual(attempt.answer.retrieval_query, QUESTION)
                self.assert_first_attempt_unchanged()

    def test_rewrite_attempt_gate_rejection_keeps_first_attempt(self):
        _, _, claude = self.run_rewrite(REWRITTEN, similarity=0.05)

        claude.assert_not_called()
        first, second = self.answers()
        self.assertEqual((second.status, second.answer_text), (INSUFFICIENT_EVIDENCE, None))
        self.assert_first_attempt_unchanged()


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
