"""Offline tests for answer completeness and correction quality.

Usage (from the project root or backend/):
    python backend/test_answer_completeness.py

Covers multi-part questions whose evidence supports all, some, or none of the requested parts,
what a REWRITE correction is told and given (the evaluator's feedback, and attempt 1's passages
when they were judged adequate), and that the final selection, scores, and stored diagnostics
stay consistent when a correction improves, fabricates, rephrases, or degrades an answer. The
documents, questions, and answers are synthetic and exist only in this file.

Offline: retrieval and every Claude caller are mocked, and the app runs against an in-memory
SQLite database, so no API calls are made and the real database is never touched.
Exits with status 0 when all tests pass, 1 otherwise.
"""

import json
import math
import os
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# Must be set before `app` is imported so the app never connects to the real database.
os.environ["DATABASE_URL"] = "sqlite://"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import test_final_selection as selection_fixtures  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Answer, Claim, Document, DocumentChunk, Evaluation  # noqa: E402
from app.services import generator  # noqa: E402
from app.services.attempt_selection import choose_final_attempt  # noqa: E402
from app.services.corrector import (  # noqa: E402
    FAILURE_DESCRIPTIONS,
    REWRITE,
    carry_over_chunks,
)
from app.services.evaluator import (  # noqa: E402
    IRRELEVANT_RETRIEVAL,
    MISSING_INFO,
    SUPPORTED,
    UNSUPPORTED,
    compute_faithfulness,
)
from app.services.generator import ANSWERED, build_correction_instructions  # noqa: E402
from app.services.llm import LLMResult  # noqa: E402
from app.services.retrieval import RetrievedChunk  # noqa: E402
from app.services.similarity_gate import INSUFFICIENT_EVIDENCE  # noqa: E402

MODEL = "claude-test-model"
QUESTION = "How much does the Widget plan cost, and how often does it renew?"
REWRITTEN = "Widget plan renewal interval"
TEXTS = [
    "Section 1. The Widget plan costs 12 credits per month.",
    "Section 2. Widget plan renewals happen every 30 days.",
    "Section 3. Support tickets are answered within one business day.",
    "Section 4. Cancelled plans keep their data for 90 days.",
]
PRICE, RENEWAL, SUPPORT, RETENTION = range(len(TEXTS))
PRICE_FACT = "The Widget plan costs 12 credits per month"
RENEWAL_FACT = "Widget plan renewals happen every 30 days"
LIMITATION = "The passages do not say how often the plan renews."
OMITTED_FEEDBACK = ("The answer gives the price but omits the renewal interval, which the "
                    "passages contain.")
ABSENT_FEEDBACK = ("The answer gives the price but not the renewal interval; the passages lack "
                   "it.")


def llm_result(text: str) -> LLMResult:
    return LLMResult(text=text, model=MODEL, input_tokens=10, output_tokens=10, latency_ms=1,
                     stop_reason="end_turn", attempts=1)


class CompletenessTest(unittest.TestCase):
    def setUp(self):
        for name, value in {"claude_model": MODEL, "similarity_gate": 0.30,
                            "evaluator_model": None, "evaluator_pass_threshold": 0.70,
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
            document = Document(filename="plans.pdf", total_pages=4, total_chunks=4)
            rows = [DocumentChunk(document=document, page_number=i + 1, chunk_index=i,
                                  content=text) for i, text in enumerate(TEXTS)]
            db.add_all([document, *rows])
            db.commit()
            self.document_id = document.id
            self.ids = [row.id for row in rows]

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    # --- fixtures ---

    def chunks(self, *indexes):
        return [RetrievedChunk(chunk_id=self.ids[i], document_id=self.document_id,
                               document="plans.pdf", page=i + 1, text=TEXTS[i],
                               similarity=0.8 - 0.01 * rank)
                for rank, i in enumerate(indexes)]

    def fact(self, index, text=None, verdict=SUPPORTED, quote=None):
        quote = quote or (PRICE_FACT if index == PRICE else RENEWAL_FACT)
        return {"claim_text": f"{text or quote}.", "verdict": verdict,
                "evidence_chunk_id": self.ids[index], "evidence_quote": quote}

    @staticmethod
    def evaluation(claims, answer_relevance, context_relevance, feedback="Checked.",
                   limitations=()):
        return json.dumps({"claims": claims, "limitations": list(limitations),
                           "answer_relevance": answer_relevance,
                           "context_relevance": context_relevance, "feedback": feedback})

    def post(self, *, retrievals, answers, evaluations, rewrites=(REWRITTEN,)):
        """`answers` are generator replies in order; `evaluations` maps answer text to reply."""
        generations = []

        def generate(prompt, **kwargs):
            generations.append(SimpleNamespace(prompt=prompt, system=kwargs.get("system")))
            return llm_result(answers[len(generations) - 1])

        def evaluate(prompt, **_):
            answer = re.search(r"<answer>\n(.*?)\n</answer>", prompt, re.DOTALL).group(1)
            return llm_result(evaluations[answer])

        with patch("app.services.similarity_gate.retrieve", side_effect=list(retrievals)), \
             patch("app.services.generator.call_claude", side_effect=generate), \
             patch("app.services.evaluator.call_claude", side_effect=evaluate) as evaluator, \
             patch("app.services.corrector.call_claude",
                   side_effect=[llm_result(r) for r in rewrites]) as rewriter:
            response = self.client.post("/query", json={"question": QUESTION, "mode": "reli"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assert_consistent(body)
        return body, SimpleNamespace(generations=generations, evaluator=evaluator,
                                     rewriter=rewriter)

    def assert_consistent(self, body):
        """The reported attempt, its scores, the selection reason, and storage all agree."""
        self.assertEqual(self.client.get(f"/query/{body['query_id']}").json(), body)
        final = body["attempts"][body["final_attempt_number"] - 1]
        if body["status"] == ANSWERED:
            self.assertEqual(body["final_answer"], final["answer"])
            selection = choose_final_attempt(selection_fixtures.summaries(body))
            self.assertEqual(selection.attempt.attempt_number, body["final_attempt_number"])
            if len(body["attempts"]) > 1:
                self.assertEqual(body["selection_reason"], selection.reason)
        with self.Session() as db:
            for attempt in body["attempts"]:
                answer = db.scalars(select(Answer).where(
                    Answer.query_id == body["query_id"],
                    Answer.attempt_number == attempt["attempt_number"])).one()
                self.assertEqual((answer.status, answer.answer_text, answer.strategy),
                                 (attempt["status"], attempt["answer"], attempt["strategy"]))
                evaluation = attempt["evaluation"]
                if evaluation is None:
                    continue
                stored = db.scalars(select(Evaluation)
                                    .where(Evaluation.answer_id == answer.id)).one()
                rows = db.scalars(select(Claim).where(Claim.evaluation_id == stored.id)
                                  .order_by(Claim.id)).all()
                self.assertEqual([(r.claim_text, r.verdict) for r in rows],
                                 [(c["claim_text"], c["verdict"]) for c in evaluation["claims"]])
                self.assertEqual((stored.faithfulness, stored.passed),
                                 (evaluation["faithfulness"], evaluation["passed"]))
                self.assertEqual(evaluation["faithfulness"], compute_faithfulness(
                    [c["verdict"] for c in evaluation["claims"]]))
                available = {r["chunk_id"] for r in attempt["retrieval"]}
                for item in evaluation["claims"]:
                    self.assertIn(item["evidence_chunk_id"], available | {None})

    def logged(self, attempt):
        return [(r["chunk_id"], r["filename"], r["page_number"]) for r in attempt["retrieval"]]

    def source(self, index):
        return (self.ids[index], "plans.pdf", index + 1)

    # --- evidence covers all, some, or none of the question ---

    def test_evidence_supporting_every_part_is_answered_without_correction(self):
        answer = f"{PRICE_FACT} [1]. {RENEWAL_FACT} [2]."
        body, calls = self.post(
            retrievals=[self.chunks(PRICE, RENEWAL)], answers=[answer],
            evaluations={answer: self.evaluation(
                [self.fact(PRICE), self.fact(RENEWAL)], 1.0, 1.0)})

        self.assertEqual((body["status"], body["final_attempt_number"], len(body["attempts"])),
                         (ANSWERED, 1, 1))
        self.assertTrue(body["attempts"][0]["evaluation"]["passed"])
        self.assertEqual(len(calls.generations), 1)
        self.assertEqual(calls.generations[0].system, generator.SYSTEM_PROMPT)
        self.assertIn("Address every part of the question", generator.SYSTEM_PROMPT)
        calls.rewriter.assert_not_called()

    def test_evidence_supporting_only_some_parts_gives_a_limited_answer(self):
        answer = f"{PRICE_FACT} [1]. {LIMITATION}"
        retry = f"{PRICE_FACT} [2]. {LIMITATION}"
        partial = self.evaluation([self.fact(PRICE)], 0.5, 0.5, ABSENT_FEEDBACK, [LIMITATION])
        body, calls = self.post(
            retrievals=[self.chunks(PRICE, SUPPORT), self.chunks(RETENTION)],
            answers=[answer, retry], evaluations={answer: partial, retry: partial})

        first, second = body["attempts"]
        # The correction was told what was missing and that it must not guess.
        system = calls.generations[1].system
        self.assertIn(ABSENT_FEEDBACK, system)
        self.assertIn(FAILURE_DESCRIPTIONS[MISSING_INFO], system)
        self.assertIn(FAILURE_DESCRIPTIONS[IRRELEVANT_RETRIEVAL], system)
        self.assertIn("instead of guessing", system)
        # Weak passages: only the one backing a claim is carried over.
        self.assertEqual(self.logged(second), [self.source(RETENTION), self.source(PRICE)])
        # Neither attempt invents the renewal interval; the equal retry does not replace attempt 1.
        self.assertEqual((body["final_attempt_number"], body["final_answer"]), (1, answer))
        self.assertEqual((first["evaluation"]["passed"], first["evaluation"]["failure_type"]),
                         (False, MISSING_INFO))
        self.assertIn("tie", body["selection_reason"])

    def test_evidence_supporting_no_requested_part_is_insufficient_evidence(self):
        body, calls = self.post(retrievals=[self.chunks(SUPPORT, RETENTION)],
                                answers=[INSUFFICIENT_EVIDENCE], evaluations={}, rewrites=())

        self.assertEqual((body["status"], len(body["attempts"]),
                          body["attempts"][0]["evaluation"]), (INSUFFICIENT_EVIDENCE, 1, None))
        calls.evaluator.assert_not_called()
        calls.rewriter.assert_not_called()

    # --- corrections ---

    def omitted_renewal(self, retry_answer, retry_evaluation, retry_retrieval=(SUPPORT,)):
        """Attempt 1 leaves out the renewal interval although its passages contain it."""
        answer = f"{PRICE_FACT} [1]."
        return self.post(
            retrievals=[self.chunks(PRICE, RENEWAL), self.chunks(*retry_retrieval)],
            answers=[answer, retry_answer],
            evaluations={answer: self.evaluation([self.fact(PRICE)], 0.5, 0.9, OMITTED_FEEDBACK),
                         retry_answer: retry_evaluation})

    def test_correction_completes_an_answer_from_the_kept_passage(self):
        # Attempt 2's own retrieval misses the renewal passage; it is kept from attempt 1.
        retry = f"{PRICE_FACT} [2]. {RENEWAL_FACT} [3]."
        body, calls = self.omitted_renewal(retry, self.evaluation(
            [self.fact(PRICE), self.fact(RENEWAL)], 1.0, 0.9))

        first, second = body["attempts"]
        self.assertEqual(self.logged(second), [self.source(SUPPORT), self.source(PRICE),
                                               self.source(RENEWAL)])
        self.assertIn(TEXTS[RENEWAL], calls.generations[1].prompt)
        self.assertEqual(calls.generations[1].system, f"{generator.SYSTEM_PROMPT}\n\n" +
                         build_correction_instructions(FAILURE_DESCRIPTIONS[MISSING_INFO],
                                                       OMITTED_FEEDBACK))
        self.assertEqual(second["strategy"], REWRITE)
        self.assertEqual((body["final_attempt_number"], body["final_answer"]), (2, retry))
        self.assertTrue(second["evaluation"]["passed"])
        self.assertEqual([c["evidence_chunk_id"] for c in second["evaluation"]["claims"]],
                         [self.ids[PRICE], self.ids[RENEWAL]])

    def test_correction_that_invents_details_is_not_rewarded(self):
        retry = f"{PRICE_FACT} [2]. Widget plan renewals happen every 7 days [3]."
        body, _ = self.omitted_renewal(retry, self.evaluation(
            [self.fact(PRICE),
             self.fact(RENEWAL, "Widget plan renewals happen every 7 days")], 1.0, 0.9))

        second = body["attempts"][1]
        invented = second["evaluation"]["claims"][1]
        self.assertEqual((invented["verdict"], invented["claude_verdict"]), (UNSUPPORTED, SUPPORTED))
        self.assertIn("number(s) 7", invented["evidence_error"])
        self.assertEqual(body["final_attempt_number"], 1)
        self.assertIn("Attempt 1 was selected over attempt 2", body["selection_reason"])

    def test_rephrased_correction_does_not_replace_the_original(self):
        retry = "The monthly cost of the Widget plan is 12 credits [2]."
        body, _ = self.omitted_renewal(retry, self.evaluation(
            [self.fact(PRICE, "The monthly cost of the Widget plan is 12 credits")], 0.5, 0.9,
            OMITTED_FEEDBACK))

        self.assertEqual(body["final_attempt_number"], 1)
        self.assertIn("earlier attempt is kept on a tie", body["selection_reason"])

    def test_worse_correction_keeps_the_original(self):
        retry = "Support tickets are answered within one business day [1]."
        body, _ = self.omitted_renewal(retry, self.evaluation(
            [{"claim_text": "Support tickets are answered within one business day.",
              "verdict": SUPPORTED, "evidence_chunk_id": self.ids[SUPPORT],
              "evidence_quote": "Support tickets are answered within one business day"}],
            0.1, 0.9))

        self.assertEqual((body["final_attempt_number"], body["final_answer"]),
                         (1, f"{PRICE_FACT} [1]."))
        self.assertIn("less complete", body["selection_reason"])


class CorrectionInputsTest(unittest.TestCase):
    def test_correction_instructions(self):
        text = build_correction_instructions("  The answer was incomplete. ",
                                             "Omits   part\n two." + "x" * 2000)
        self.assertIn("Problems: The answer was incomplete.", text)
        feedback = re.search(r"Evaluator feedback: (.*)\n", text).group(1)
        self.assertTrue(feedback.startswith("Omits part two.x"))
        self.assertEqual(len(feedback), generator.MAX_CORRECTION_FEEDBACK_CHARS)
        self.assertIn("they are not evidence", text)
        self.assertIn("Evaluator feedback: None given.", build_correction_instructions("P", None))

    def test_carry_over_chunks(self):
        chunks = [RetrievedChunk(chunk_id=i, document_id=1, document="d.pdf", page=i, text="t",
                                 similarity=0.5) for i in (1, 2, 3)]
        claims = [SimpleNamespace(verdict=SUPPORTED, evidence_chunk_id=3),
                  SimpleNamespace(verdict=UNSUPPORTED, evidence_chunk_id=None)]

        def evaluation(context_relevance):
            return SimpleNamespace(context_relevance=context_relevance, claims=claims)

        with patch.object(settings, "evaluator_pass_threshold", 0.70):
            self.assertEqual([c.chunk_id for c in carry_over_chunks(chunks, evaluation(0.70))],
                             [3, 1, 2])
            for weak in (0.69, None, math.nan):
                with self.subTest(context_relevance=weak):
                    self.assertEqual(
                        [c.chunk_id for c in carry_over_chunks(chunks, evaluation(weak))], [3])
        self.assertEqual(carry_over_chunks(chunks, None), [])


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
