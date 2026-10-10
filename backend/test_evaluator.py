"""RELI-RAG Day 3: unit tests for the evaluator service.

Usage (from the project root or backend/):
    python backend/test_evaluator.py

Offline: Claude is mocked, so no API calls are made and no API key or database is needed.
Exits with status 0 when all tests pass, 1 otherwise.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Must be set before `app` is imported so the app never connects to the real database.
os.environ["DATABASE_URL"] = "sqlite://"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.services.evaluator import (  # noqa: E402
    EVALUATOR_ERROR,
    IRRELEVANT_RETRIEVAL,
    MISSING_INFO,
    PARTIALLY_SUPPORTED,
    RETRY_INSTRUCTION,
    SUPPORTED,
    UNSUPPORTED,
    UNSUPPORTED_CLAIM,
    compute_faithfulness,
    determine_failure_type,
    evaluate_answer,
)
from app.services.llm import LLMError, LLMResult  # noqa: E402
from app.services.retrieval import RetrievedChunk  # noqa: E402

MODEL = "claude-test-model"
QUESTION = "What does TCP provide?"
ANSWER = "TCP provides a reliable, ordered byte stream [1]. It uses a three-way handshake [2]."
CHUNKS = [
    RetrievedChunk(chunk_id=41, document_id=1, document="net.pdf", page=4,
                   text="TCP provides a reliable,\nordered byte stream between applications.",
                   similarity=0.9),
    RetrievedChunk(chunk_id=57, document_id=1, document="net.pdf", page=5,
                   text="Connections are opened with a three-way handshake (SYN, SYN-ACK, ACK).",
                   similarity=0.8),
]


def llm_result(text: str, input_tokens: int = 300, output_tokens: int = 80) -> LLMResult:
    return LLMResult(
        text=text, model=MODEL, input_tokens=input_tokens, output_tokens=output_tokens,
        latency_ms=5, stop_reason="end_turn", attempts=1,
    )


def claim(text: str, verdict: str, chunk_id: int | None, quote: str | None) -> dict:
    return {"claim_text": text, "verdict": verdict, "evidence_chunk_id": chunk_id,
            "evidence_quote": quote}


GOOD_CLAIMS = [
    claim("TCP provides a reliable, ordered byte stream.", SUPPORTED, 41,
          "TCP provides a reliable, ordered byte stream"),
    claim("TCP uses a three-way handshake.", SUPPORTED, 57, "three-way handshake"),
]


def reply(claims=GOOD_CLAIMS, answer_relevance=0.95, context_relevance=0.9,
          feedback="The answer is grounded and complete.") -> str:
    return json.dumps({"claims": claims, "answer_relevance": answer_relevance,
                       "context_relevance": context_relevance, "feedback": feedback})


class ScoreCalculationTest(unittest.TestCase):
    def test_faithfulness_formula(self):
        verdicts = [SUPPORTED, SUPPORTED, PARTIALLY_SUPPORTED, UNSUPPORTED]
        self.assertAlmostEqual(compute_faithfulness(verdicts), 2.5 / 4)
        self.assertEqual(compute_faithfulness([SUPPORTED] * 3), 1.0)
        self.assertEqual(compute_faithfulness([PARTIALLY_SUPPORTED] * 2), 0.5)
        self.assertEqual(compute_faithfulness([UNSUPPORTED]), 0.0)

    def test_zero_claims_does_not_divide_by_zero(self):
        self.assertEqual(compute_faithfulness([]), 0.0)

    def test_threshold_is_inclusive(self):
        self.assertIsNone(determine_failure_type(0.80, 0.80, 0.80))
        self.assertEqual(determine_failure_type(0.79, 0.80, 0.80), UNSUPPORTED_CLAIM)
        self.assertEqual(determine_failure_type(0.80, 0.79, 0.80), MISSING_INFO)
        self.assertEqual(determine_failure_type(0.80, 0.80, 0.79), IRRELEVANT_RETRIEVAL)

    def test_first_failing_score_sets_failure_type(self):
        self.assertEqual(determine_failure_type(0.5, 0.5, 0.5), UNSUPPORTED_CLAIM)
        self.assertEqual(determine_failure_type(1.0, 0.5, 0.5), MISSING_INFO)


class EvaluateAnswerTest(unittest.TestCase):
    def evaluate(self, *texts: str):
        """Run evaluate_answer with Claude returning `texts` in order; returns (result, mock)."""
        with patch("app.services.evaluator.call_claude") as claude:
            claude.side_effect = [llm_result(text) for text in texts]
            result = evaluate_answer(QUESTION, ANSWER, CHUNKS)
        return result, claude

    def test_passing_answer(self):
        result, claude = self.evaluate(reply())

        claude.assert_called_once()
        self.assertEqual(claude.call_args.kwargs["temperature"], 0)
        prompt = claude.call_args.args[0]
        self.assertIn("chunk_id=41", prompt)
        self.assertIn("chunk_id=57", prompt)
        self.assertTrue(result.passed)
        self.assertIsNone(result.failure_type)
        self.assertEqual(result.faithfulness, 1.0)
        self.assertEqual(result.answer_relevance, 0.95)
        self.assertEqual(result.context_relevance, 0.9)
        self.assertEqual([c.verdict for c in result.claims], [SUPPORTED, SUPPORTED])
        self.assertEqual([c.evidence_chunk_id for c in result.claims], [41, 57])
        self.assertEqual(result.feedback, "The answer is grounded and complete.")
        self.assertEqual((result.model, result.input_tokens, result.output_tokens,
                          result.llm_calls), (MODEL, 300, 80, 1))

    def test_partially_supported_claims_lower_faithfulness(self):
        claims = [GOOD_CLAIMS[0],
                  claim("TCP handshakes take three seconds.", PARTIALLY_SUPPORTED, 57,
                        "three-way handshake")]
        result, _ = self.evaluate(reply(claims))

        self.assertEqual(result.faithfulness, 0.75)
        self.assertFalse(result.passed)
        self.assertEqual(result.failure_type, UNSUPPORTED_CLAIM)

    def test_low_answer_relevance_is_missing_info(self):
        result, _ = self.evaluate(reply(answer_relevance=0.5))
        self.assertFalse(result.passed)
        self.assertEqual(result.failure_type, MISSING_INFO)

    def test_low_context_relevance_is_irrelevant_retrieval(self):
        result, _ = self.evaluate(reply(context_relevance=0.4))
        self.assertFalse(result.passed)
        self.assertEqual(result.failure_type, IRRELEVANT_RETRIEVAL)

    def test_unsupported_claim_without_evidence(self):
        claims = [GOOD_CLAIMS[0], claim("TCP was invented in 1999.", UNSUPPORTED, None, None)]
        result, _ = self.evaluate(reply(claims))

        self.assertEqual(result.faithfulness, 0.5)
        self.assertEqual(result.failure_type, UNSUPPORTED_CLAIM)
        self.assertIsNone(result.claims[1].evidence_error)

    def test_fenced_json_is_accepted_without_retry(self):
        result, claude = self.evaluate(f"```json\n{reply()}\n```")
        claude.assert_called_once()
        self.assertTrue(result.passed)

    def test_malformed_json_is_retried_once(self):
        result, claude = self.evaluate("Here is my evaluation: {not json", reply())

        self.assertEqual(claude.call_count, 2)
        retry_prompt = claude.call_args_list[1].args[0]
        self.assertTrue(retry_prompt.startswith(claude.call_args_list[0].args[0]))
        self.assertIn(RETRY_INSTRUCTION.splitlines()[1], retry_prompt)
        self.assertEqual(claude.call_args_list[1].kwargs["temperature"], 0)
        self.assertTrue(result.passed)
        self.assertEqual((result.input_tokens, result.output_tokens, result.llm_calls),
                         (600, 160, 2))

    def test_schema_violations_are_retried(self):
        invalid_replies = {
            "unknown verdict": reply([claim("TCP is reliable.", "maybe", 41, "reliable")]),
            "score above 1": reply(answer_relevance=1.5),
            "score as string": reply(context_relevance="0.9"),
            "missing field": json.dumps({"claims": GOOD_CLAIMS, "answer_relevance": 0.9}),
            "zero claims": reply(claims=[]),
        }
        for name, invalid in invalid_replies.items():
            with self.subTest(name):
                result, claude = self.evaluate(invalid, reply())
                self.assertEqual(claude.call_count, 2)
                self.assertTrue(result.passed)

    def test_invalid_retry_returns_evaluator_error(self):
        result, claude = self.evaluate("not json", "still not json")

        self.assertEqual(claude.call_count, 2)
        self.assertFalse(result.passed)
        self.assertEqual(result.failure_type, EVALUATOR_ERROR)
        self.assertIsNone(result.faithfulness)
        self.assertIsNone(result.answer_relevance)
        self.assertIsNone(result.context_relevance)
        self.assertEqual(result.claims, [])
        self.assertIn("Evaluation failed", result.feedback)
        self.assertEqual(result.llm_calls, 2)

    def test_claude_failure_returns_evaluator_error(self):
        with patch("app.services.evaluator.call_claude", side_effect=LLMError("timeout")):
            result = evaluate_answer(QUESTION, ANSWER, CHUNKS)

        self.assertFalse(result.passed)
        self.assertEqual(result.failure_type, EVALUATOR_ERROR)
        self.assertIn("timeout", result.feedback)
        self.assertEqual((result.model, result.llm_calls), (None, 0))

    def test_unwrapped_sdk_error_returns_evaluator_error(self):
        error = TypeError("Could not resolve authentication method")
        with patch("app.services.evaluator.call_claude", side_effect=error):
            result = evaluate_answer(QUESTION, ANSWER, CHUNKS)

        self.assertFalse(result.passed)
        self.assertEqual(result.failure_type, EVALUATOR_ERROR)
        self.assertIsNone(result.faithfulness)

    def test_retry_failure_keeps_first_attempt_usage(self):
        with patch("app.services.evaluator.call_claude") as claude:
            claude.side_effect = [llm_result("not json"), LLMError("overloaded")]
            result = evaluate_answer(QUESTION, ANSWER, CHUNKS)

        self.assertEqual(claude.call_count, 2)
        self.assertEqual(result.failure_type, EVALUATOR_ERROR)
        self.assertIn("overloaded", result.feedback)
        self.assertEqual((result.model, result.input_tokens, result.output_tokens,
                          result.llm_calls), (MODEL, 300, 80, 1))
        self.assertGreaterEqual(result.latency_ms, 0)

    def test_unknown_chunk_id_is_never_supported(self):
        claims = [GOOD_CLAIMS[0],
                  claim("TCP uses a three-way handshake.", SUPPORTED, 2, "three-way handshake")]
        result, _ = self.evaluate(reply(claims))

        bad = result.claims[1]
        self.assertEqual(bad.verdict, UNSUPPORTED)
        self.assertEqual(bad.claude_verdict, SUPPORTED)
        self.assertIsNone(bad.evidence_chunk_id)
        self.assertIsNone(bad.evidence_quote)
        self.assertIn("not one of the retrieved chunks", bad.evidence_error)
        self.assertEqual(result.faithfulness, 0.5)
        self.assertEqual(result.failure_type, UNSUPPORTED_CLAIM)
        self.assertIn("1 claim(s) cited evidence that could not be verified", result.feedback)

    def test_quote_missing_from_referenced_chunk_is_never_supported(self):
        cases = {
            "fabricated quote": claim("TCP uses a three-way handshake.", SUPPORTED, 57,
                                      "TCP always uses a four-way handshake"),
            "quote from another chunk": claim("TCP uses a three-way handshake.", SUPPORTED, 41,
                                              "three-way handshake"),
            "empty quote": claim("TCP uses a three-way handshake.", PARTIALLY_SUPPORTED, 57, "  "),
            "no evidence": claim("TCP uses a three-way handshake.", SUPPORTED, None, None),
        }
        for name, bad_claim in cases.items():
            with self.subTest(name):
                result, _ = self.evaluate(reply([GOOD_CLAIMS[0], bad_claim]))
                self.assertEqual(result.claims[1].verdict, UNSUPPORTED)
                self.assertIsNotNone(result.claims[1].evidence_error)
                self.assertEqual(result.faithfulness, 0.5)
                self.assertFalse(result.passed)

    def test_quote_match_ignores_whitespace_case_and_typographic_quotes(self):
        claims = [claim("TCP provides a reliable byte stream.", SUPPORTED, 41,
                        "tcp provides a reliable,   ordered BYTE stream"),
                  claim("Handshakes use SYN-ACK.", SUPPORTED, 57, "(SYN, SYN\u2013ACK, ACK)")]
        result, _ = self.evaluate(reply(claims))

        self.assertEqual([c.verdict for c in result.claims], [SUPPORTED, SUPPORTED])
        self.assertTrue(result.passed)

    def test_rejects_empty_inputs(self):
        with patch("app.services.evaluator.call_claude") as claude:
            for args in (("  ", ANSWER, CHUNKS), (QUESTION, "", CHUNKS), (QUESTION, ANSWER, [])):
                with self.subTest(args=args[:2]), self.assertRaises(ValueError):
                    evaluate_answer(*args)
        claude.assert_not_called()


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
