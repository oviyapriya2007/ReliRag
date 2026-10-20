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
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Must be set before `app` is imported so the app never connects to the real database.
os.environ["DATABASE_URL"] = "sqlite://"
# Pin the evaluator settings so a local .env cannot change the expected results.
EVALUATOR_ENV = {
    "EVALUATOR_MODEL": "",
    "EVALUATOR_MAX_TOKENS": "2048",
    "EVALUATOR_PASS_THRESHOLD": "0.80",
    "EVALUATOR_MAX_PARSE_ATTEMPTS": "2",
}
os.environ.update(EVALUATOR_ENV)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pydantic import ValidationError  # noqa: E402

from app.config import Settings, settings  # noqa: E402
from app.services.evaluator import (  # noqa: E402
    EVALUATOR_ERROR,
    IRRELEVANT_RETRIEVAL,
    MAX_EVALUATOR_TOKENS,
    MISSING_INFO,
    PARTIALLY_SUPPORTED,
    RETRY_INSTRUCTION,
    SUPPORTED,
    TRUNCATION_INSTRUCTION,
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
                   text="TCP connections are opened with a three-way handshake (SYN, SYN-ACK, "
                        "ACK).",
                   similarity=0.8),
]


def llm_result(text: str, input_tokens: int = 300, output_tokens: int = 80,
               stop_reason: str = "end_turn") -> LLMResult:
    return LLMResult(
        text=text, model=MODEL, input_tokens=input_tokens, output_tokens=output_tokens,
        latency_ms=5, stop_reason=stop_reason, attempts=1,
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
        self.assertNotIn("temperature", claude.call_args.kwargs)
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
        self.assertNotIn("temperature", claude.call_args_list[1].kwargs)
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
                  claim("The handshake uses SYN, SYN-ACK, and ACK.", SUPPORTED, 57,
                        "(SYN, SYN\u2013ACK, ACK)")]
        result, _ = self.evaluate(reply(claims))

        self.assertEqual([c.verdict for c in result.claims], [SUPPORTED, SUPPORTED])
        self.assertTrue(result.passed)

    def test_rejects_empty_inputs(self):
        with patch("app.services.evaluator.call_claude") as claude:
            for args in (("  ", ANSWER, CHUNKS), (QUESTION, "", CHUNKS), (QUESTION, ANSWER, [])):
                with self.subTest(args=args[:2]), self.assertRaises(ValueError):
                    evaluate_answer(*args)
        claude.assert_not_called()


class EvaluatorSettingsTest(unittest.TestCase):
    def load(self, **env):
        """Settings from the process environment plus `env`, ignoring any .env file."""
        base = {k: v for k, v in os.environ.items() if k not in EVALUATOR_ENV}
        with patch.dict(os.environ, {**base, **env}, clear=True):
            return Settings(_env_file=None)

    def test_defaults(self):
        loaded = self.load()
        self.assertIsNone(loaded.evaluator_model)
        self.assertEqual(loaded.evaluator_max_tokens, 2048)
        self.assertEqual(loaded.evaluator_pass_threshold, 0.70)
        self.assertEqual(loaded.evaluator_max_parse_attempts, 2)
        self.assertEqual(loaded.claude_max_tokens, 1024)

    def test_environment_overrides(self):
        loaded = self.load(EVALUATOR_MODEL="eval-model", EVALUATOR_MAX_TOKENS="4096",
                           EVALUATOR_PASS_THRESHOLD="0.9", EVALUATOR_MAX_PARSE_ATTEMPTS="3",
                           CLAUDE_MODEL="gen-model")
        self.assertEqual(loaded.evaluator_model, "eval-model")
        self.assertEqual(loaded.claude_model, "gen-model")
        self.assertEqual(loaded.evaluator_max_tokens, 4096)
        self.assertEqual(loaded.evaluator_pass_threshold, 0.9)
        self.assertEqual(loaded.evaluator_max_parse_attempts, 3)

    def test_invalid_values_are_rejected(self):
        for name, value in (("EVALUATOR_PASS_THRESHOLD", "1.5"),
                            ("EVALUATOR_PASS_THRESHOLD", "-0.1"),
                            ("EVALUATOR_MAX_TOKENS", "0"),
                            ("EVALUATOR_MAX_PARSE_ATTEMPTS", "0")):
            with self.subTest(name=name, value=value), self.assertRaises(ValidationError):
                self.load(**{name: value})


class EvaluatorConfigurationTest(unittest.TestCase):
    def evaluate(self, *texts: str, **kwargs):
        with patch("app.services.evaluator.call_claude") as claude:
            claude.side_effect = [llm_result(text) for text in texts]
            result = evaluate_answer(QUESTION, ANSWER, CHUNKS, **kwargs)
        return result, claude

    def test_default_token_limit_and_model_fallback(self):
        _, claude = self.evaluate(reply())
        self.assertEqual(claude.call_args.kwargs["max_tokens"], 2048)
        self.assertIsNone(claude.call_args.kwargs["model"])

    def test_configured_model_and_token_limit(self):
        with patch.object(settings, "evaluator_model", "eval-model"), \
             patch.object(settings, "evaluator_max_tokens", 4096):
            _, claude = self.evaluate("not json", reply())
        for call in claude.call_args_list:
            self.assertEqual((call.kwargs["model"], call.kwargs["max_tokens"]),
                             ("eval-model", 4096))

    def test_unset_evaluator_model_uses_claude_model(self):
        response = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=reply())], model="gen-model",
            usage=SimpleNamespace(input_tokens=1, output_tokens=1), stop_reason="end_turn",
        )
        client = MagicMock()
        client.messages.create.return_value = response
        with patch.object(settings, "claude_model", "gen-model"), \
             patch.object(settings, "evaluator_model", None), \
             patch("app.services.llm.get_client", return_value=client):
            result = evaluate_answer(QUESTION, ANSWER, CHUNKS)
        self.assertEqual(client.messages.create.call_args.kwargs["model"], "gen-model")
        self.assertEqual(result.model, "gen-model")

    def test_configured_pass_threshold(self):
        with patch.object(settings, "evaluator_pass_threshold", 0.95):
            strict, _ = self.evaluate(reply())
            self.assertEqual(determine_failure_type(1.0, 0.95, 0.9), IRRELEVANT_RETRIEVAL)
        self.assertFalse(strict.passed)
        self.assertEqual(strict.failure_type, IRRELEVANT_RETRIEVAL)

        with patch.object(settings, "evaluator_pass_threshold", 0.5):
            lenient, _ = self.evaluate(reply(context_relevance=0.6))
        self.assertTrue(lenient.passed)

    def test_explicit_arguments_override_settings(self):
        with patch.object(settings, "evaluator_model", "eval-model"), \
             patch.object(settings, "evaluator_max_tokens", 4096), \
             patch.object(settings, "evaluator_pass_threshold", 0.5):
            result, claude = self.evaluate(reply(), threshold=0.95, max_tokens=512,
                                           model="arg-model")
        self.assertEqual((claude.call_args.kwargs["model"], claude.call_args.kwargs["max_tokens"]),
                         ("arg-model", 512))
        self.assertEqual(result.failure_type, IRRELEVANT_RETRIEVAL)

    def test_configured_parse_attempts(self):
        with patch.object(settings, "evaluator_max_parse_attempts", 1):
            single, claude = self.evaluate("not json")
        self.assertEqual(claude.call_count, 1)
        self.assertEqual(single.failure_type, EVALUATOR_ERROR)

        with patch.object(settings, "evaluator_max_parse_attempts", 3):
            third_time, claude = self.evaluate("not json", "still not json", reply())
        self.assertEqual(claude.call_count, 3)
        self.assertTrue(third_time.passed)


TCP_FACT = "TCP provides a reliable, ordered byte stream"
LIMITATION = "The passages do not say how fast TCP is."


class StatementChecksTest(unittest.TestCase):
    """Limitation statements (H2), evidence support (H3), and citations (H6)."""

    def setUp(self):
        patcher = patch.object(settings, "evaluator_pass_threshold", 0.80)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def evaluate(answer: str, claims, limitations=None, answer_relevance=0.95,
                 context_relevance=0.9):
        body = {"claims": claims, "answer_relevance": answer_relevance,
                "context_relevance": context_relevance, "feedback": "Checked."}
        if limitations is not None:
            body["limitations"] = limitations
        with patch("app.services.evaluator.call_claude",
                   return_value=llm_result(json.dumps(body))):
            return evaluate_answer(QUESTION, answer, CHUNKS)

    def tcp_claim(self, verdict=SUPPORTED):
        return claim(f"{TCP_FACT}.", verdict, 41, TCP_FACT)

    # --- H2: limitation statements -------------------------------------------------------

    def test_limitation_statement_is_not_an_unsupported_claim(self):
        result = self.evaluate(f"{TCP_FACT} [1]. {LIMITATION}", [self.tcp_claim()], [LIMITATION])

        self.assertTrue(result.passed)
        self.assertEqual(result.faithfulness, 1.0)
        self.assertEqual([c.claim_text for c in result.claims], [f"{TCP_FACT}."])
        self.assertIn("1 limitation statement(s) were not scored", result.feedback)

    def test_factual_statement_labeled_a_limitation_is_unsupported(self):
        for mislabeled in ("TCP was standardized in 1981.",
                           "The passages do not give a date, but TCP was standardized in 1981."):
            with self.subTest(mislabeled=mislabeled):
                result = self.evaluate(f"{TCP_FACT} [1]. {mislabeled}", [self.tcp_claim()],
                                       [mislabeled])

                self.assertEqual(result.faithfulness, 0.5)
                self.assertEqual(result.failure_type, UNSUPPORTED_CLAIM)
                added = result.claims[-1]
                self.assertEqual((added.claim_text, added.verdict, added.claude_verdict),
                                 (mislabeled, UNSUPPORTED, None))
                self.assertIn("labeled as limitations assert facts", result.feedback)

    def test_limitations_do_not_make_an_incomplete_answer_complete(self):
        only = self.evaluate(LIMITATION, [], [LIMITATION], answer_relevance=0.9)
        self.assertEqual((only.faithfulness, only.answer_relevance), (1.0, 0.0))
        self.assertEqual(only.failure_type, MISSING_INFO)
        self.assertFalse(only.passed)

        partial = self.evaluate(f"{TCP_FACT} [1]. {LIMITATION}", [self.tcp_claim()],
                                [LIMITATION], answer_relevance=0.5)
        self.assertEqual(partial.answer_relevance, 0.5)
        self.assertEqual(partial.failure_type, MISSING_INFO)

    def test_reply_without_claims_or_limitations_is_invalid(self):
        with patch("app.services.evaluator.call_claude", return_value=llm_result(json.dumps(
                {"claims": [], "limitations": [], "answer_relevance": 0.9,
                 "context_relevance": 0.9, "feedback": "x"}))):
            result = evaluate_answer(QUESTION, ANSWER, CHUNKS)
        self.assertEqual(result.failure_type, EVALUATOR_ERROR)

    # --- H3: evidence support ------------------------------------------------------------

    def test_quote_that_supports_the_claim_keeps_its_verdict(self):
        result = self.evaluate(f"{TCP_FACT} [1].", [self.tcp_claim()])
        self.assertEqual((result.claims[0].verdict, result.claims[0].evidence_error),
                         (SUPPORTED, None))

    def test_quote_that_exists_but_does_not_support_the_claim(self):
        cases = {
            "unrelated quote": (claim("Connections are encrypted with TLS.", SUPPORTED, 57,
                                      "Connections are opened"), UNSUPPORTED,
                                "does not support the claim"),
            "number not in passage": (claim("TCP delivers a reliable byte stream within 5 ms.",
                                            SUPPORTED, 41, TCP_FACT), UNSUPPORTED,
                                      "number(s) 5"),
            "only part supported": (claim(
                "TCP provides an ordered stream with encryption, compression, multiplexing and "
                "congestion pricing.", SUPPORTED, 41, TCP_FACT), PARTIALLY_SUPPORTED,
                "only part of the claim"),
            "quote states the opposite": (claim("TCP does not provide an ordered byte stream.",
                                                SUPPORTED, 41, TCP_FACT), UNSUPPORTED,
                                          "states the opposite"),
            "negation differs": (claim("Applications cannot receive an ordered byte stream.",
                                       SUPPORTED, 41, TCP_FACT), PARTIALLY_SUPPORTED, "negation"),
        }
        for name, (bad_claim, verdict, reason) in cases.items():
            with self.subTest(name):
                result = self.evaluate(ANSWER, [bad_claim])
                judged = result.claims[0]
                self.assertEqual((judged.verdict, judged.claude_verdict), (verdict, SUPPORTED))
                self.assertIn(reason, judged.evidence_error)
                self.assertLess(result.faithfulness, 1.0)
                if verdict == UNSUPPORTED:
                    self.assertIsNone(judged.evidence_quote)

    def test_support_checks_never_raise_a_verdict(self):
        result = self.evaluate(f"{TCP_FACT} [1].", [self.tcp_claim(PARTIALLY_SUPPORTED)])
        self.assertEqual(result.claims[0].verdict, PARTIALLY_SUPPORTED)
        self.assertEqual(result.faithfulness, 0.5)

    def test_invalid_or_missing_evidence_is_still_unsupported(self):
        for bad in (claim(f"{TCP_FACT}.", SUPPORTED, 41, "TCP provides an unordered stream"),
                    claim(f"{TCP_FACT}.", SUPPORTED, None, None)):
            with self.subTest(bad=bad):
                result = self.evaluate(f"{TCP_FACT} [1].", [bad])
                self.assertEqual(result.claims[0].verdict, UNSUPPORTED)
                self.assertEqual(result.faithfulness, 0.0)

    # --- H6: citations -------------------------------------------------------------------

    def test_relevant_citations_pass(self):
        result = self.evaluate(ANSWER, GOOD_CLAIMS)
        self.assertTrue(result.passed)
        self.assertEqual([c.verdict for c in result.claims], [SUPPORTED, SUPPORTED])

    def test_citation_of_a_passage_without_the_evidence_is_downgraded(self):
        result = self.evaluate(f"{TCP_FACT} [2].", [self.tcp_claim()])

        self.assertEqual(result.claims[0].verdict, PARTIALLY_SUPPORTED)
        self.assertIn("do not contain the evidence", result.claims[0].evidence_error)
        self.assertFalse(result.passed)
        self.assertIn("missing, invalid, or unrelated citation", result.feedback)

    def test_invalid_citation_numbers_are_reported_not_ignored(self):
        answer = f"{TCP_FACT} [7]. UDP has optional extension headers for every packet [9]."
        result = self.evaluate(answer, [self.tcp_claim()])

        self.assertEqual(result.claims[0].verdict, PARTIALLY_SUPPORTED)
        self.assertIn("[7]", result.claims[0].evidence_error)
        added = result.claims[1]
        self.assertEqual((added.verdict, added.claude_verdict), (UNSUPPORTED, None))
        self.assertIn("[9]", added.evidence_error)
        self.assertIn("passage number(s) [7, 9] that do not exist", result.feedback)
        self.assertFalse(result.passed)

    def test_uncited_factual_statements_are_flagged(self):
        claimed = self.evaluate(f"{TCP_FACT}.", [self.tcp_claim()])
        self.assertEqual(claimed.claims[0].verdict, PARTIALLY_SUPPORTED)
        self.assertIn("no citation", claimed.claims[0].evidence_error)

        unclaimed = self.evaluate(f"{TCP_FACT} [1]. UDP sends independent datagrams quickly.",
                                  [self.tcp_claim()])
        added = unclaimed.claims[-1]
        self.assertEqual((added.claim_text, added.verdict),
                         ("UDP sends independent datagrams quickly.", UNSUPPORTED))
        self.assertEqual(unclaimed.faithfulness, 0.5)
        self.assertIn("without a valid citation", unclaimed.feedback)

    def test_limitations_headings_and_lead_ins_need_no_citation(self):
        answer = ("Here is what the passages say about transport protocols:\n"
                  "## Reliable transport\n"
                  f"{TCP_FACT} [1].\n{LIMITATION}")
        result = self.evaluate(answer, [self.tcp_claim()], [LIMITATION])

        self.assertEqual(len(result.claims), 1)
        self.assertTrue(result.passed)

    def test_mixed_answer_scores_only_the_factual_parts(self):
        answer = (f"{TCP_FACT} [1]. It uses a three-way handshake [1]. {LIMITATION} "
                  "UDP is always faster than TCP.")
        result = self.evaluate(answer, GOOD_CLAIMS, [LIMITATION])

        verdicts = {c.claim_text: c.verdict for c in result.claims}
        self.assertEqual(verdicts["TCP provides a reliable, ordered byte stream."], SUPPORTED)
        # The handshake evidence is in passage [2], but the sentence cites [1].
        self.assertEqual(verdicts["TCP uses a three-way handshake."], PARTIALLY_SUPPORTED)
        self.assertEqual(verdicts["UDP is always faster than TCP."], UNSUPPORTED)
        self.assertNotIn(LIMITATION, verdicts)
        self.assertAlmostEqual(result.faithfulness, 1.5 / 3)


class TruncationAndExtractionTest(unittest.TestCase):
    """Evaluator replies cut off at the token budget, and JSON embedded in prose."""

    def setUp(self):
        for name, value in {"evaluator_max_tokens": 2048, "evaluator_max_parse_attempts": 2,
                            "evaluator_pass_threshold": 0.80}.items():
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def evaluate(self, *replies, **kwargs):
        """Claude returns `replies` in order: LLMResults, exceptions, or text (end_turn)."""
        with patch("app.services.evaluator.call_claude") as claude:
            claude.side_effect = [r if isinstance(r, (LLMResult, Exception)) else llm_result(r)
                                  for r in replies]
            result = evaluate_answer(QUESTION, ANSWER, CHUNKS, **kwargs)
        return result, claude

    @staticmethod
    def truncated(text: str = '{"claims": [{"claim_text": "TCP provides a rel') -> LLMResult:
        return llm_result(text, output_tokens=2048, stop_reason="max_tokens")

    @staticmethod
    def budgets(claude) -> list[int]:
        return [call.kwargs["max_tokens"] for call in claude.call_args_list]

    def assert_evaluator_error(self, result):
        self.assertFalse(result.passed)
        self.assertEqual(result.failure_type, EVALUATOR_ERROR)
        self.assertIsNone(result.faithfulness)
        self.assertEqual(result.claims, [])

    def test_truncated_reply_is_retried_with_a_larger_budget(self):
        result, claude = self.evaluate(self.truncated(), reply())

        self.assertTrue(result.passed)
        self.assertEqual(self.budgets(claude), [2048, 4096])
        first_prompt, retry_prompt = (call.args[0] for call in claude.call_args_list)
        self.assertEqual(retry_prompt, f"{first_prompt}\n\n{TRUNCATION_INSTRUCTION}")
        self.assertEqual(result.llm_calls, 2)

    def test_truncated_reply_is_never_parsed_even_if_it_looks_valid(self):
        result, claude = self.evaluate(*[llm_result(reply(), stop_reason="max_tokens")] * 3)

        self.assertEqual(self.budgets(claude), [2048, 4096, MAX_EVALUATOR_TOKENS])
        self.assert_evaluator_error(result)

    def test_persistent_truncation_stops_at_the_ceiling(self):
        result, claude = self.evaluate(self.truncated(), self.truncated(), self.truncated())

        self.assertEqual(self.budgets(claude), [2048, 4096, MAX_EVALUATOR_TOKENS])
        self.assert_evaluator_error(result)
        self.assertIn("truncated", result.feedback)
        self.assertEqual(result.llm_calls, 3)

    def test_truncation_at_the_ceiling_is_not_retried_with_the_same_budget(self):
        result, claude = self.evaluate(self.truncated(), max_tokens=MAX_EVALUATOR_TOKENS)

        self.assertEqual(self.budgets(claude), [MAX_EVALUATOR_TOKENS])
        self.assert_evaluator_error(result)

    def test_truncation_retries_do_not_use_up_parse_attempts(self):
        with patch.object(settings, "evaluator_max_parse_attempts", 1):
            passed, claude = self.evaluate(self.truncated(), reply())
            failed, failed_claude = self.evaluate(self.truncated(), "not json", reply())

        self.assertTrue(passed.passed)
        self.assertEqual(claude.call_count, 2)
        self.assert_evaluator_error(failed)
        self.assertEqual(self.budgets(failed_claude), [2048, 4096])

    def test_claude_failure_after_truncation_is_evaluator_error(self):
        result, _ = self.evaluate(self.truncated(), LLMError("overloaded"))

        self.assert_evaluator_error(result)
        self.assertIn("overloaded", result.feedback)

    def test_json_surrounded_by_prose_is_accepted(self):
        cases = {
            "prose": f"Here is the evaluation:\n{reply()}\nLet me know if you need more.",
            "fenced inside prose": f"Sure.\n```json\n{reply()}\n```\nDone.",
        }
        for name, text in cases.items():
            with self.subTest(name):
                result, claude = self.evaluate(text)
                claude.assert_called_once()
                self.assertTrue(result.passed)
                self.assertEqual(result.faithfulness, 1.0)

    def test_ambiguous_or_invalid_embedded_json_is_rejected(self):
        cases = {
            "two objects": f"First: {reply()}\nSecond: {reply(answer_relevance=0.1)}",
            "schema violation in prose": f"Result: {reply(answer_relevance=1.5)}",
            "broken object in prose": "Result: {not json} and nothing else",
        }
        for name, text in cases.items():
            with self.subTest(name):
                result, claude = self.evaluate(text, text)
                self.assertEqual(claude.call_count, 2)
                self.assert_evaluator_error(result)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
