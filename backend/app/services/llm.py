import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 1


class LLMError(Exception):
    """Raised when a Claude call fails or the client is misconfigured."""


@dataclass(frozen=True)
class LLMResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    stop_reason: str | None
    attempts: int


@lru_cache(maxsize=1)
def get_client() -> anthropic.Anthropic:
    api_key = settings.anthropic_api_key
    # Retries are handled in call_claude so every attempt is timed and logged.
    return anthropic.Anthropic(
        api_key=api_key.get_secret_value() if api_key else None,
        timeout=settings.claude_timeout_seconds,
        max_retries=0,
    )


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (anthropic.APIConnectionError, anthropic.RateLimitError)):
        return True
    return isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500


def _response_text(response: Any) -> str:
    return "".join(block.text for block in response.content if block.type == "text")


def call_claude(
    messages: str | Sequence[dict[str, Any]],
    *,
    system: str | None = None,
    max_tokens: int | None = None,
    model: str | None = None,
    temperature: float | None = None,
) -> LLMResult:
    """Send one Messages API request to Claude, retrying once on transient failures.

    `messages` is either a single user prompt or a list of Messages API message dicts.
    `temperature=None` leaves the API default in place.
    `latency_ms` covers all attempts, including the backoff delay.
    """
    model = model or settings.claude_model
    if not model:
        raise LLMError("CLAUDE_MODEL is not configured")
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]

    request: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens or settings.claude_max_tokens,
        "messages": list(messages),
    }
    if system:
        request["system"] = system
    if temperature is not None:
        request["temperature"] = temperature

    client = get_client()
    started = time.perf_counter()
    for attempt in range(1, MAX_RETRIES + 2):
        attempt_started = time.perf_counter()
        try:
            response = client.messages.create(**request)
        except anthropic.AnthropicError as exc:
            attempt_ms = round((time.perf_counter() - attempt_started) * 1000)
            retry = attempt <= MAX_RETRIES and _is_retryable(exc)
            logger.warning(
                "Claude call failed: model=%s attempt=%d latency_ms=%d error=%r retry=%s",
                model, attempt, attempt_ms, exc, retry,
            )
            if not retry:
                raise LLMError(f"Claude call failed after {attempt} attempt(s): {exc}") from exc
            time.sleep(settings.claude_retry_backoff_seconds * 2 ** (attempt - 1))
            continue

        result = LLMResult(
            text=_response_text(response),
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=round((time.perf_counter() - started) * 1000),
            stop_reason=response.stop_reason,
            attempts=attempt,
        )
        logger.info(
            "Claude call ok: model=%s attempt=%d latency_ms=%d input_tokens=%d output_tokens=%d",
            result.model, attempt, result.latency_ms, result.input_tokens, result.output_tokens,
        )
        return result

    raise AssertionError("unreachable")
