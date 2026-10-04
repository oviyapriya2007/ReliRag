"""RELI-RAG Day 2 A3: manual test of the Claude client wrapper.

Usage (from the project root or backend/):
    python backend/test_llm_client.py ["prompt"] [--system "..."] [--max-tokens 64]

Makes a real Claude API call (costs tokens). Requires ANTHROPIC_API_KEY and
CLAUDE_MODEL in .env. Exits with status 0 on success, 1 on failure.
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.services.llm import LLMError, call_claude  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Send one prompt to Claude.")
    parser.add_argument("prompt", nargs="?", default="Reply with exactly: pong")
    parser.add_argument("--system", default=None)
    parser.add_argument("--max-tokens", type=int, default=64)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    try:
        result = call_claude(args.prompt, system=args.system, max_tokens=args.max_tokens)
    except LLMError as exc:
        print(f"[FAIL] {exc}")
        return 1

    print(f"Model:         {result.model}")
    print(f"Attempts:      {result.attempts}")
    print(f"Latency:       {result.latency_ms} ms")
    print(f"Input tokens:  {result.input_tokens}")
    print(f"Output tokens: {result.output_tokens}")
    print(f"Stop reason:   {result.stop_reason}")
    print(f"\n{result.text}")

    if not result.text or result.input_tokens <= 0 or result.output_tokens <= 0:
        print("\n[FAIL] Empty response or missing usage data")
        return 1
    print("\n[OK] Claude call succeeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
