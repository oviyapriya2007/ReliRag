"""RELI-RAG Day 3: offline tests for the Messages API request built by the Claude client.

Usage (from the project root or backend/):
    python backend/test_llm_request.py

Offline: the Anthropic client is replaced by a fake whose `messages.create()` accepts exactly
the parameters of the installed SDK's `Messages.create()`, so an unsupported argument raises
the same TypeError as the real SDK. No API calls are made and no database is needed.
Exits with status 0 when all tests pass, 1 otherwise.
"""

import inspect
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# Must be set before `app` is imported so the app never connects to the real database.
os.environ["DATABASE_URL"] = "sqlite://"
# Pin the Claude and evaluator settings so a local .env cannot change the expected requests.
os.environ.update({
    "CLAUDE_MODEL": "claude-test-model",
    "CLAUDE_MAX_TOKENS": "1024",
    "EVALUATOR_MODEL": "",
    "EVALUATOR_MAX_TOKENS": "2048",
    "EVALUATOR_PASS_THRESHOLD": "0.80",
    "EVALUATOR_MAX_PARSE_ATTEMPTS": "2",
})

sys.path.insert(0, str(Path(__file__).resolve().parent))

from anthropic.resources.messages import Messages  # noqa: E402

from app.config import settings  # noqa: E402
from app.services import evaluator, generator  # noqa: E402
from app.services.evaluator import SUPPORTED, evaluate_answer  # noqa: E402
from app.services.generator import ANSWERED, generate_answer  # noqa: E402
from app.services.llm import call_claude  # noqa: E402
from app.services.query_pipeline import run_evaluation  # noqa: E402
from app.services.retrieval import RetrievedChunk  # noqa: E402

CREATE_SIGNATURE = inspect.signature(Messages.create)
SUPPORTED_ARGS = set(CREATE_SIGNATURE.parameters) - {"self"}
TEMPERATURE_ERROR = r"^Messages\.create\(\) got an unexpected keyword argument 'temperature'$"

MODEL = "claude-test-model"
PINNED_SETTINGS = {
    "claude_model": MODEL,
    "claude_max_tokens": 1024,
    "evaluator_model": None,
    "evaluator_max_tokens": 2048,
    "evaluator_pass_threshold": 0.80,
    "evaluator_max_parse_attempts": 2,
}
QUESTION = "What does TCP provide?"
ANSWER = "TCP provides a reliable, ordered byte stream [1]. It uses a three-way handshake [2]."
CHUNKS = [
    RetrievedChunk(chunk_id=41, document_id=1, document="net.pdf", page=4,
                   text="TCP provides a reliable, ordered byte stream between applications.",
                   similarity=0.9),
    RetrievedChunk(chunk_id=57, document_id=1, document="net.pdf", page=5,
                   text="TCP connections are opened with a three-way handshake (SYN, SYN-ACK, "
                        "ACK).",
                   similarity=0.8),
]
EVALUATOR_REPLY = json.dumps({
    "claims": [
        {"claim_text": "TCP provides a reliable, ordered byte stream.", "verdict": SUPPORTED,
         "evidence_chunk_id": 41, "evidence_quote": "TCP provides a reliable, ordered byte stream"},
        {"claim_text": "TCP uses a three-way handshake.", "verdict": SUPPORTED,
         "evidence_chunk_id": 57, "evidence_quote": "three-way handshake"},
    ],
    "answer_relevance": 0.95,
    "context_relevance": 0.9,
    "feedback": "The answer is grounded and complete.",
})


class FakeMessages:
    """Stands in for `client.messages`, enforcing the installed SDK's `create()` signature."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests: list[dict] = []

    def create(self, **kwargs):
        try:
            CREATE_SIGNATURE.bind(self, **kwargs)
        except TypeError as exc:
            raise TypeError(f"Messages.create() {exc}") from None
        self.requests.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.replies.pop(0))],
            model=kwargs["model"],
            usage=SimpleNamespace(input_tokens=100, output_tokens=20),
            stop_reason="end_turn",
        )


class FakeAnthropic:
    def __init__(self, *replies: str):
        self.messages = FakeMessages(replies)


class RequestTestCase(unittest.TestCase):
    def setUp(self):
        # `settings` is created once per process. When another test module imports `app`
        # first (e.g. `unittest discover` or pytest), it has already been loaded from .env
        # and the environment pins above come too late, so pin the live object as well.
        for name, value in PINNED_SETTINGS.items():
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def fake_claude(self, *replies: str) -> FakeMessages:
        """Route `call_claude` to a fake client that returns `replies` in order."""
        client = FakeAnthropic(*replies)
        patcher = patch("app.services.llm.get_client", return_value=client)
        patcher.start()
        self.addCleanup(patcher.stop)
        return client.messages

    def assert_supported(self, request: dict):
        self.assertLessEqual(set(request), SUPPORTED_ARGS)
        self.assertNotIn("temperature", request)


class FakeClientTest(RequestTestCase):
    def test_installed_sdk_has_no_temperature_parameter(self):
        self.assertNotIn("temperature", SUPPORTED_ARGS)
        self.assertLessEqual({"model", "max_tokens", "messages", "system"}, SUPPORTED_ARGS)

    def test_fake_reproduces_the_sdk_temperature_error(self):
        messages = FakeMessages(["unused"])
        with self.assertRaisesRegex(TypeError, TEMPERATURE_ERROR):
            messages.create(model=MODEL, max_tokens=16,
                            messages=[{"role": "user", "content": "hi"}], temperature=0)
        self.assertEqual(messages.requests, [])


class CallClaudeRequestTest(RequestTestCase):
    def test_request_uses_only_supported_arguments(self):
        messages = self.fake_claude("pong")
        result = call_claude("ping", system="Be brief.", max_tokens=64)

        self.assertEqual(messages.requests, [{
            "model": MODEL,
            "max_tokens": 64,
            "messages": [{"role": "user", "content": "ping"}],
            "system": "Be brief.",
        }])
        self.assertEqual((result.text, result.model, result.attempts), ("pong", MODEL, 1))

    def test_temperature_is_no_longer_accepted(self):
        messages = self.fake_claude("pong")
        with self.assertRaises(TypeError):
            call_claude("ping", temperature=0)
        self.assertEqual(messages.requests, [])


class EvaluatorRequestTest(RequestTestCase):
    def test_evaluation_no_longer_fails_with_temperature_error(self):
        messages = self.fake_claude(EVALUATOR_REPLY)
        result = evaluate_answer(QUESTION, ANSWER, CHUNKS)

        self.assertIsNone(result.failure_type)
        self.assertTrue(result.passed)
        self.assertEqual(result.faithfulness, 1.0)
        self.assertEqual(result.feedback, "The answer is grounded and complete.")
        self.assertEqual(len(messages.requests), 1)
        request = messages.requests[0]
        self.assert_supported(request)
        self.assertEqual(request["model"], MODEL)
        self.assertEqual(request["max_tokens"], 2048)
        self.assertEqual(request["system"], evaluator.SYSTEM_PROMPT)
        self.assertEqual(request["messages"],
                         [{"role": "user",
                           "content": evaluator.build_prompt(QUESTION, ANSWER, CHUNKS)}])

    def test_parse_retry_request_is_also_supported(self):
        messages = self.fake_claude("not json", EVALUATOR_REPLY)
        result = evaluate_answer(QUESTION, ANSWER, CHUNKS)

        self.assertTrue(result.passed)
        self.assertEqual(result.llm_calls, 2)
        self.assertEqual(len(messages.requests), 2)
        for request in messages.requests:
            self.assert_supported(request)
        self.assertIn("Your previous reply was rejected",
                      messages.requests[1]["messages"][0]["content"])

    def test_configured_evaluator_model_and_token_limit_are_sent(self):
        messages = self.fake_claude(EVALUATOR_REPLY)
        with patch.object(settings, "evaluator_model", "eval-model"), \
             patch.object(settings, "evaluator_max_tokens", 4096):
            result = evaluate_answer(QUESTION, ANSWER, CHUNKS)

        self.assertTrue(result.passed)
        self.assert_supported(messages.requests[0])
        self.assertEqual((messages.requests[0]["model"], messages.requests[0]["max_tokens"]),
                         ("eval-model", 4096))

    def test_query_pipeline_evaluation_is_not_evaluator_error(self):
        messages = self.fake_claude(EVALUATOR_REPLY)
        result = run_evaluation(QUESTION, ANSWER, CHUNKS)

        self.assertIsNone(result.failure_type)
        self.assertTrue(result.passed)
        self.assert_supported(messages.requests[0])


class GeneratorRequestTest(RequestTestCase):
    def test_generation_request_uses_only_supported_arguments(self):
        messages = self.fake_claude(ANSWER)
        result = generate_answer(QUESTION, CHUNKS)

        self.assertEqual(result.status, ANSWERED)
        self.assertEqual(result.citations, [1, 2])
        self.assertEqual(len(messages.requests), 1)
        request = messages.requests[0]
        self.assert_supported(request)
        self.assertEqual(request["model"], MODEL)
        self.assertEqual(request["max_tokens"], 1024)
        self.assertEqual(request["system"], generator.SYSTEM_PROMPT)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
