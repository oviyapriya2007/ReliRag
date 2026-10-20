"""Offline tests for evidence verification and faithfulness scoring.

Usage (from the project root or backend/):
    python backend/test_evidence_verification.py

Covers the deterministic checks the evaluator applies to Claude's claim verdicts: quote
matching, numbers written as digits or words, negation and contradiction, limitation statements,
duplicate claims, faithfulness arithmetic, the 70% threshold, and agreement between the scored,
persisted, and returned claims. The passages are generic, made-up text.

Offline: Claude, retrieval, and the generator are mocked, and the app runs against an in-memory
SQLite database, so no API calls are made and the real database is never touched.
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

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Claim, Document, DocumentChunk, Evaluation  # noqa: E402
from app.services import answer_checks  # noqa: E402
from app.services.evaluator import (  # noqa: E402
    CHECK_EVIDENCE,
    CHECK_LIMITATION,
    CHECK_SUPPORT,
    CHECK_UNCITED,
    EVALUATOR_ERROR,
    PARTIALLY_SUPPORTED,
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
QUESTION = "What does the handbook say about the archive?"
PASSAGES = [
    "Section 1. The archive keeps monthly snapshots for seven years.",
    "Section 2. Snapshots are stored in a sepa-\nrate region, and the archive cannot be "
    "restored without an approval code.",
    "Section 3. The archive retries failed uploads automatically. Uploads use a three-step "
    "check.",
]


def chunks(texts=PASSAGES):
    return [RetrievedChunk(chunk_id=100 + index, document_id=1, document="handbook.pdf",
                           page=index + 1, text=text, similarity=0.9)
            for index, text in enumerate(texts)]


def claim(text, verdict=SUPPORTED, chunk_id=None, quote=None):
    return {"claim_text": text, "verdict": verdict, "evidence_chunk_id": chunk_id,
            "evidence_quote": quote}


def llm_result(text: str) -> LLMResult:
    return LLMResult(text=text, model=MODEL, input_tokens=10, output_tokens=10, latency_ms=1,
                     stop_reason="end_turn", attempts=1)


def reply(claims, limitations=None, answer_relevance=1.0, context_relevance=1.0) -> str:
    body = {"claims": claims, "answer_relevance": answer_relevance,
            "context_relevance": context_relevance, "feedback": "Checked."}
    if limitations is not None:
        body["limitations"] = limitations
    return json.dumps(body)


class ThresholdPinned(unittest.TestCase):
    def setUp(self):
        for name, value in {"evaluator_pass_threshold": 0.70,
                            "evaluator_max_parse_attempts": 2}.items():
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def evaluate(self, answer, *replies, retrieved=None):
        with patch("app.services.evaluator.call_claude",
                   side_effect=[r if isinstance(r, Exception) else llm_result(r)
                                for r in replies]):
            result = evaluate_answer(QUESTION, answer, retrieved or chunks())
        if result.faithfulness is not None:
            # Faithfulness always follows from exactly the claims that are reported.
            self.assertEqual(result.faithfulness,
                             compute_faithfulness([c.verdict for c in result.claims]))
            self.assertEqual(result.passed, result.failure_type is None)
        return result

    def only_claim(self, answer, judged_claim):
        result = self.evaluate(answer, reply([judged_claim]))
        self.assertEqual(len(result.claims), 1)
        return result, result.claims[0]


class QuoteMatchingTest(ThresholdPinned):
    def test_quote_with_different_punctuation_or_line_break_hyphenation_is_found(self):
        cases = {
            "line-break hyphenation": ("Snapshots are stored in a separate region [2].",
                                       "Snapshots are stored in a separate region"),
            "punctuation dropped": ("The archive cannot be restored without an approval code [2].",
                                    "region and the archive cannot be restored"),
        }
        for name, (answer, quote) in cases.items():
            with self.subTest(name):
                _, judged = self.only_claim(answer, claim(answer.split(" [")[0], SUPPORTED,
                                                          101, quote))
                self.assertNotEqual(judged.check, CHECK_EVIDENCE, judged.evidence_error)

    def test_quote_must_still_be_verbatim(self):
        for quote in ("The archive automatically retries failed uploads",  # reordered
                      "The archive retries failed downloads automatically",  # changed word
                      "The archive retries uploads automatically"):  # word dropped
            with self.subTest(quote=quote):
                result, judged = self.only_claim(
                    "The archive retries failed uploads automatically [3].",
                    claim("The archive retries failed uploads automatically.", SUPPORTED, 102,
                          quote))
                self.assertEqual((judged.verdict, judged.check), (UNSUPPORTED, CHECK_EVIDENCE))
                self.assertEqual(result.faithfulness, 0.0)

    def test_quote_occurs_helper(self):
        text = "Values are low-\nlatency and high-throughput, per the spec."
        self.assertTrue(answer_checks.quote_occurs("low-latency and high throughput", text))
        self.assertTrue(answer_checks.quote_occurs("Values are low latency", text))
        self.assertFalse(answer_checks.quote_occurs("high latency", text))
        self.assertFalse(answer_checks.quote_occurs("", text))
        self.assertFalse(answer_checks.quote_occurs("...", text))


class NumberTest(ThresholdPinned):
    def test_same_number_in_digits_or_words_is_supported(self):
        for text in ("The archive keeps monthly snapshots for 7 years.",
                     "The archive keeps monthly snapshots for seven years."):
            with self.subTest(text=text):
                _, judged = self.only_claim(f"{text[:-1]} [1].", claim(
                    text, SUPPORTED, 100, "The archive keeps monthly snapshots for seven years"))
                self.assertEqual(judged.verdict, SUPPORTED)

    def test_different_number_sharing_every_other_word_is_unsupported(self):
        for text in ("The archive keeps monthly snapshots for five years.",
                     "The archive keeps monthly snapshots for 5 years.",
                     "Uploads use a four-step check."):
            with self.subTest(text=text):
                chunk_id = 102 if "Uploads" in text else 100
                quote = ("Uploads use a three-step check" if chunk_id == 102
                         else "The archive keeps monthly snapshots for seven years")
                result, judged = self.only_claim(f"{text[:-1]} [{chunk_id - 99}].",
                                                 claim(text, SUPPORTED, chunk_id, quote))
                self.assertEqual((judged.verdict, judged.check), (UNSUPPORTED, CHECK_SUPPORT))
                self.assertIn("do not occur in the cited passage", judged.evidence_error)
                self.assertFalse(result.passed)

    def test_number_words(self):
        cases = {"twenty-five units": {"25"}, "sixty one": {"61"}, "two hundred items": set(),
                 "one of the steps": set(), "3 or three": {"3"}, "1,500 rows": {"1500"}}
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(answer_checks.numbers(text), expected)


class NegationTest(ThresholdPinned):
    def test_double_negation_paraphrase_is_supported(self):
        _, judged = self.only_claim(
            "Restoring the archive requires an approval code [2].",
            claim("Restoring the archive requires an approval code.", SUPPORTED, 101,
                  "the archive cannot be restored without an approval code"))
        self.assertEqual(judged.verdict, SUPPORTED)

    def test_quote_stating_the_opposite_is_unsupported(self):
        result, judged = self.only_claim(
            "The archive does not retry failed uploads automatically [3].",
            claim("The archive does not retry failed uploads automatically.", SUPPORTED, 102,
                  "The archive retries failed uploads automatically"))
        self.assertEqual((judged.verdict, judged.claude_verdict, judged.check),
                         (UNSUPPORTED, SUPPORTED, CHECK_SUPPORT))
        self.assertIn("opposite", judged.evidence_error)
        self.assertEqual(result.failure_type, UNSUPPORTED_CLAIM)

    def test_ambiguous_polarity_difference_is_only_partial(self):
        _, judged = self.only_claim(
            "Failed uploads never need a manual retry in the archive [3].",
            claim("Failed uploads never need a manual retry in the archive.", SUPPORTED, 102,
                  "The archive retries failed uploads automatically"))
        self.assertEqual(judged.verdict, PARTIALLY_SUPPORTED)
        self.assertIn("negation", judged.evidence_error)


class SupportAndEvidenceTest(ThresholdPinned):
    def test_keyword_overlap_alone_is_not_support(self):
        _, judged = self.only_claim(
            "The archive encrypts snapshots with rotating keys [1].",
            claim("The archive encrypts snapshots with rotating keys.", SUPPORTED, 100,
                  "The archive keeps monthly snapshots"))
        self.assertEqual(judged.verdict, PARTIALLY_SUPPORTED)

        _, judged = self.only_claim(
            "Rotating keys protect every regional backup [1].",
            claim("Rotating keys protect every regional backup.", SUPPORTED, 100,
                  "The archive keeps monthly snapshots"))
        self.assertEqual(judged.verdict, UNSUPPORTED)

    def test_partial_support_is_kept_partial(self):
        text = "The archive keeps snapshots, deletes them after each audit, and encrypts every copy."
        _, judged = self.only_claim(f"{text[:-1]} [1].", claim(
            text, SUPPORTED, 100, "The archive keeps monthly snapshots"))
        self.assertEqual(judged.verdict, PARTIALLY_SUPPORTED)

    def test_missing_or_unretrieved_evidence_is_unsupported(self):
        for bad in (claim("The archive keeps monthly snapshots for seven years."),
                    claim("The archive keeps monthly snapshots for seven years.", SUPPORTED, 999,
                          "The archive keeps monthly snapshots for seven years"),
                    claim("The archive keeps monthly snapshots for seven years.", SUPPORTED, 100,
                          "")):
            with self.subTest(bad=bad):
                _, judged = self.only_claim(
                    "The archive keeps monthly snapshots for seven years [1].", bad)
                self.assertEqual((judged.verdict, judged.check), (UNSUPPORTED, CHECK_EVIDENCE))

    def test_evidence_in_several_chunks(self):
        answer = ("The archive keeps monthly snapshots for seven years [1], and it retries "
                  "failed uploads automatically [3].")
        result = self.evaluate(answer, reply([
            claim("The archive keeps monthly snapshots for seven years.", SUPPORTED, 100,
                  "The archive keeps monthly snapshots for seven years"),
            claim("The archive retries failed uploads automatically.", SUPPORTED, 102,
                  "The archive retries failed uploads automatically"),
        ]))
        self.assertEqual([c.verdict for c in result.claims], [SUPPORTED, SUPPORTED])
        self.assertTrue(result.passed)

    def test_conflicting_passages_require_the_cited_one_to_state_the_claim(self):
        conflicting = chunks(["The archive keeps snapshots for seven years.",
                              "Older guidance: the archive keeps snapshots for five years."])
        answer = "The archive keeps snapshots for five years [{}]."
        for cited, chunk_id, quote, verdict in (
                (1, 100, "The archive keeps snapshots for seven years", UNSUPPORTED),
                (2, 101, "the archive keeps snapshots for five years", SUPPORTED)):
            with self.subTest(cited=cited):
                result = self.evaluate(answer.format(cited), reply([claim(
                    "The archive keeps snapshots for five years.", SUPPORTED, chunk_id, quote)]),
                    retrieved=conflicting)
                self.assertEqual(result.claims[0].verdict, verdict)

    def test_verification_errors_never_become_supported(self):
        cases = {
            "invalid replies": ("not json", reply([claim("x", "maybe", 100, "x")])),
            "Claude error": (LLMError("overloaded"),),
            "score out of range": (reply([], ["The passages do not say."], 1.5),
                                   reply([], ["The passages do not say."], 1.5)),
        }
        for name, replies in cases.items():
            with self.subTest(name):
                result = self.evaluate("The archive keeps monthly snapshots [1].", *replies)
                self.assertEqual((result.passed, result.failure_type, result.faithfulness,
                                  result.claims), (False, EVALUATOR_ERROR, None, []))


class LimitationAndDuplicateTest(ThresholdPinned):
    FACT = claim("The archive keeps monthly snapshots for seven years.", SUPPORTED, 100,
                 "The archive keeps monthly snapshots for seven years")
    FACT_SENTENCE = "The archive keeps monthly snapshots for seven years [1]."

    def test_negative_fact_labeled_a_limitation_is_scored(self):
        negative = "The archive does not compress snapshots."
        result = self.evaluate(f"{self.FACT_SENTENCE} {negative}",
                               reply([self.FACT], [negative]))
        added = result.claims[-1]
        self.assertEqual((added.claim_text, added.verdict, added.check),
                         (negative, UNSUPPORTED, CHECK_LIMITATION))
        self.assertEqual(result.faithfulness, 0.5)

    def test_uncited_negative_fact_is_scored(self):
        result = self.evaluate(f"{self.FACT_SENTENCE} The archive does not compress snapshots.",
                               reply([self.FACT]))
        self.assertEqual([(c.verdict, c.check) for c in result.claims],
                         [(SUPPORTED, None), (UNSUPPORTED, CHECK_UNCITED)])

    def test_genuine_limitations_are_not_scored(self):
        for limitation in ("The passages do not say how snapshots are compressed.",
                           "No information is given about compression.",
                           "It is unclear whether snapshots are compressed.",
                           "I could not find the compression method."):
            with self.subTest(limitation=limitation):
                result = self.evaluate(f"{self.FACT_SENTENCE} {limitation}",
                                       reply([self.FACT], [limitation]))
                self.assertEqual([c.claim_text for c in result.claims],
                                 [self.FACT["claim_text"]])
                self.assertEqual(result.faithfulness, 1.0)

    def test_repeated_claims_count_once_with_the_lowest_verdict(self):
        unsupported = claim("Snapshots are deleted every week.", UNSUPPORTED)
        result = self.evaluate(
            f"{self.FACT_SENTENCE} Snapshots are deleted every week [1].",
            reply([self.FACT, dict(self.FACT, claim_text=self.FACT["claim_text"].upper()),
                   unsupported, dict(unsupported, claim_text="snapshots are deleted every week")]))
        self.assertEqual([c.verdict for c in result.claims], [SUPPORTED, UNSUPPORTED])
        self.assertEqual(result.faithfulness, 0.5)
        self.assertIn("2 repeated claim(s) were counted once", result.feedback)

        weaker_copy = dict(self.FACT, verdict=PARTIALLY_SUPPORTED)
        result = self.evaluate(self.FACT_SENTENCE, reply([self.FACT, weaker_copy]))
        self.assertEqual([c.verdict for c in result.claims], [PARTIALLY_SUPPORTED])


class FaithfulnessThresholdTest(ThresholdPinned):
    FACTS = [
        ("The archive keeps monthly snapshots for seven years.", 100,
         "The archive keeps monthly snapshots for seven years"),
        ("Snapshots are stored in a separate region.", 101,
         "Snapshots are stored in a separate region"),
        ("The archive retries failed uploads automatically.", 102,
         "The archive retries failed uploads automatically"),
        ("Uploads use a three-step check.", 102, "Uploads use a three-step check"),
        ("The archive cannot be restored without an approval code.", 101,
         "the archive cannot be restored without an approval code"),
    ]

    def score(self, verdicts):
        citations = {100: 1, 101: 2, 102: 3}
        answer = " ".join(f"{text[:-1]} [{citations[chunk_id]}]."
                          for text, chunk_id, _ in self.FACTS)
        claims = [claim(text, verdict, chunk_id if verdict != UNSUPPORTED else None,
                        quote if verdict != UNSUPPORTED else None)
                  for (text, chunk_id, quote), verdict in zip(self.FACTS, verdicts)]
        return self.evaluate(answer, reply(claims))

    def test_below_at_and_above_70_percent(self):
        S, P, U = SUPPORTED, PARTIALLY_SUPPORTED, UNSUPPORTED
        cases = {
            "below (3.0 / 5 = 0.6)": ([S, S, S, U, U], 0.6, False),
            "exactly 70% (3.5 / 5)": ([S, S, S, P, U], 0.7, True),
            "above (4.0 / 5 = 0.8)": ([S, S, S, S, U], 0.8, True),
        }
        for name, (verdicts, faithfulness, passed) in cases.items():
            with self.subTest(name):
                result = self.score(verdicts)
                self.assertEqual([c.verdict for c in result.claims], verdicts)
                self.assertEqual(result.faithfulness, faithfulness)
                self.assertEqual(result.passed, passed)
                self.assertEqual(result.failure_type, None if passed else UNSUPPORTED_CLAIM)


class PersistedClaimsTest(unittest.TestCase):
    """The claims and scores returned by /query are the ones scored and stored."""

    def setUp(self):
        for name, value in {"claude_model": MODEL, "similarity_gate": 0.30,
                            "evaluator_pass_threshold": 0.70,
                            "evaluator_max_parse_attempts": 2}.items():
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                               poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        self.Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with self.Session() as db:
            document = Document(filename="handbook.pdf", total_pages=3, total_chunks=3)
            rows = [DocumentChunk(document=document, page_number=i + 1, chunk_index=i,
                                  content=text) for i, text in enumerate(PASSAGES)]
            db.add_all([document, *rows])
            db.commit()
            self.retrieved = [RetrievedChunk(chunk_id=row.id, document_id=document.id,
                                             document="handbook.pdf", page=i + 1, text=row.content,
                                             similarity=0.8 - 0.01 * i)
                              for i, row in enumerate(rows)]

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def test_api_claims_match_storage_and_scores(self):
        ids = [chunk.chunk_id for chunk in self.retrieved]
        answer = ("Snapshots are stored in a separate region [2]. The archive does not retry "
                  "failed uploads automatically [3]. The archive does not compress snapshots.")
        evaluator_reply = reply([
            claim("Snapshots are stored in a separate region.", SUPPORTED, ids[1],
                  "Snapshots are stored in a separate region"),
            claim("The archive does not retry failed uploads automatically.", SUPPORTED, ids[2],
                  "The archive retries failed uploads automatically"),
            claim("Snapshots are stored in a separate region", SUPPORTED, ids[1],
                  "Snapshots are stored in a separate region"),
        ], ["The archive does not compress snapshots."])
        with patch("app.services.similarity_gate.retrieve", return_value=self.retrieved), \
             patch("app.services.generator.call_claude", return_value=llm_result(answer)), \
             patch("app.services.evaluator.call_claude", return_value=llm_result(evaluator_reply)):
            response = self.client.post("/query", json={"question": QUESTION, "mode": "basic"})
        self.assertEqual(response.status_code, 200, response.text)
        evaluation = response.json()["attempts"][0]["evaluation"]

        verdicts = [c["verdict"] for c in evaluation["claims"]]
        self.assertEqual(verdicts, [SUPPORTED, UNSUPPORTED, UNSUPPORTED])
        self.assertEqual([c["check_name"] for c in evaluation["claims"]],
                         [None, CHECK_SUPPORT, CHECK_LIMITATION])
        self.assertAlmostEqual(evaluation["faithfulness"], 1 / 3)
        self.assertEqual(evaluation["faithfulness"], compute_faithfulness(verdicts))
        self.assertEqual(evaluation["failure_type"],
                         determine_failure_type(evaluation["faithfulness"],
                                                evaluation["answer_relevance"],
                                                evaluation["context_relevance"]))
        self.assertFalse(evaluation["passed"])

        with self.Session() as db:
            stored = db.scalars(select(Evaluation)).one()
            rows = db.scalars(select(Claim).where(Claim.evaluation_id == stored.id)
                              .order_by(Claim.id)).all()
            self.assertEqual((stored.faithfulness, stored.passed, stored.failure_type),
                             (evaluation["faithfulness"], evaluation["passed"],
                              evaluation["failure_type"]))
            self.assertEqual(
                [(r.claim_text, r.verdict, r.claude_verdict, r.evidence_chunk_id,
                  r.evidence_quote, r.evidence_error, r.check_name) for r in rows],
                [(c["claim_text"], c["verdict"], c["claude_verdict"], c["evidence_chunk_id"],
                  c["evidence_quote"], c["evidence_error"], c["check_name"])
                 for c in evaluation["claims"]])


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
