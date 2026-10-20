"""Offline tests for semantic claim verification, contradictions across retrieved passages, and
evidence preservation through the correction pipeline.

Usage (from the project root or backend/):
    python backend/test_evidence_semantics.py

The evaluator (Claude) judges meaning; these tests mock its replies and check that the
deterministic layer verifies them against the evidence actually retrieved: it must not accept a
claim whose name, quantity, qualifier, or relationship differs from the evidence, must not
override a verified paraphrase, must record contradicting passages with their source, and must
judge every attempt only against the chunks that attempt had. Documents are synthetic.

Offline: retrieval and every Claude caller are mocked, and the app runs against an in-memory
SQLite database, so no API calls are made and the real database is never touched.
Exits with status 0 when all tests pass, 1 otherwise.
"""

import json
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

from app.config import settings  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Answer, Claim, Document, DocumentChunk, Evaluation  # noqa: E402
from app.services.corrector import REWRITE, supporting_chunks  # noqa: E402
from app.services.evaluator import (  # noqa: E402
    CHECK_EVIDENCE,
    CHECK_SUPPORT,
    EVALUATOR_ERROR,
    MISSING_INFO,
    PARTIALLY_SUPPORTED,
    SUPPORTED,
    SYSTEM_PROMPT,
    UNSUPPORTED,
    ClaimVerdict,
    compute_faithfulness,
    determine_failure_type,
    evaluate_answer,
)
from app.services.generator import ANSWERED  # noqa: E402
from app.services.llm import LLMResult  # noqa: E402
from app.services.retrieval import RetrievedChunk  # noqa: E402
from app.services.similarity_gate import INSUFFICIENT_EVIDENCE  # noqa: E402

MODEL = "claude-test-model"
QUESTION = "What does Product A cost and how quickly does it ship?"
# (document, page, text) for each synthetic chunk.
CHUNKS = [
    ("catalog.pdf", 1, "Product A costs 40 dollars."),
    ("catalog.pdf", 2, "Product A ships within 2 days."),
    ("notice.pdf", 3, "Product A ships within 5 days."),
    ("notice.pdf", 4, "During holidays, Product A ships within 5 days."),
    ("notice.pdf", 5, "Product B ships within 5 days."),
    ("staff.pdf", 6, "Bob reports to Alice. Some customers prefer express shipping."),
]
PRICE, FAST, SLOW, HOLIDAY, OTHER_PRODUCT, STAFF = range(len(CHUNKS))


def llm_result(text: str) -> LLMResult:
    return LLMResult(text=text, model=MODEL, input_tokens=10, output_tokens=10, latency_ms=1,
                     stop_reason="end_turn", attempts=1)


def evidence(chunk_id, quote):
    return {"evidence_chunk_id": chunk_id, "evidence_quote": quote}


def claim(text, verdict=SUPPORTED, chunk_id=None, quote=None, additional=(), conflicting=()):
    return {"claim_text": text, "verdict": verdict, "evidence_chunk_id": chunk_id,
            "evidence_quote": quote, "additional_evidence": list(additional),
            "conflicting_evidence": list(conflicting)}


def reply(claims, answer_relevance=1.0, context_relevance=1.0) -> str:
    return json.dumps({"claims": claims, "answer_relevance": answer_relevance,
                       "context_relevance": context_relevance, "feedback": "Checked."})


def retrieved(indexes, ids=None, similarity=0.8) -> list[RetrievedChunk]:
    ids = ids or list(range(100, 100 + len(CHUNKS)))
    return [RetrievedChunk(chunk_id=ids[i], document_id=1 + ["catalog.pdf", "notice.pdf",
                                                             "staff.pdf"].index(CHUNKS[i][0]),
                           document=CHUNKS[i][0], page=CHUNKS[i][1], text=CHUNKS[i][2],
                           similarity=similarity - 0.01 * rank)
            for rank, i in enumerate(indexes)]


ID = {index: 100 + index for index in range(len(CHUNKS))}


class Pinned(unittest.TestCase):
    def setUp(self):
        for name, value in {"claude_model": MODEL, "similarity_gate": 0.30,
                            "evaluator_model": None, "evaluator_pass_threshold": 0.70,
                            "evaluator_max_parse_attempts": 2}.items():
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)


class SemanticVerificationTest(Pinned):
    def judge(self, answer, judged_claim, indexes=(PRICE, FAST, SLOW, HOLIDAY, OTHER_PRODUCT,
                                                     STAFF)):
        with patch("app.services.evaluator.call_claude",
                   return_value=llm_result(reply([judged_claim]))):
            result = evaluate_answer(QUESTION, answer, retrieved(indexes))
        self.assertEqual(result.faithfulness,
                         compute_faithfulness([c.verdict for c in result.claims]))
        return result.claims[0]

    def test_paraphrase_with_different_wording_keeps_the_evaluators_verdict(self):
        for verdict in (SUPPORTED, PARTIALLY_SUPPORTED):
            with self.subTest(verdict=verdict):
                judged = self.judge("Delivery of Product A takes at most 2 days [2].",
                                    claim("Delivery of Product A takes at most 2 days.",
                                          verdict, ID[FAST], "Product A ships within 2 days"))
                self.assertEqual((judged.verdict, judged.check), (verdict, None))

    def test_wrong_subject_with_matching_words_is_unsupported(self):
        judged = self.judge("Product B ships within 2 days [2].",
                            claim("Product B ships within 2 days.", SUPPORTED, ID[FAST],
                                  "Product A ships within 2 days"))
        self.assertEqual((judged.verdict, judged.check), (UNSUPPORTED, CHECK_SUPPORT))
        self.assertIn("about A, not B", judged.evidence_error)

    def test_reversed_relationship_is_not_accepted(self):
        judged = self.judge("Alice reports to Bob [6].",
                            claim("Alice reports to Bob.", SUPPORTED, ID[STAFF],
                                  "Bob reports to Alice"))
        self.assertEqual(judged.verdict, PARTIALLY_SUPPORTED)
        self.assertEqual(self.judge("Alice reports to Bob [6].",
                                    claim("Alice reports to Bob.", UNSUPPORTED)).verdict,
                         UNSUPPORTED)

    def test_wrong_quantity_or_qualifier_is_not_accepted(self):
        cases = {
            "quantity": ("Product A ships within 3 days.", ID[FAST],
                         "Product A ships within 2 days", UNSUPPORTED, "number(s) 3"),
            "generalized": ("Product A always ships within 2 days.", ID[FAST],
                            "Product A ships within 2 days", PARTIALLY_SUPPORTED, "generalizes"),
            "hedge dropped": ("Customers prefer express shipping.", ID[STAFF],
                              "customers prefer express shipping", PARTIALLY_SUPPORTED,
                              "qualified"),
        }
        for name, (text, chunk_id, quote, verdict, reason) in cases.items():
            with self.subTest(name):
                judged = self.judge(f"{text[:-1]} [1].", claim(text, SUPPORTED, chunk_id, quote),
                                    indexes=[{ID[FAST]: FAST, ID[STAFF]: STAFF}[chunk_id]])
                self.assertEqual(judged.verdict, verdict)
                self.assertIn(reason, judged.evidence_error)

    def test_claim_supported_by_several_chunks_together(self):
        text = "Product A costs 40 dollars and ships within 2 days."
        answer = f"{text[:-1]} [1][2]."
        together = self.judge(answer, claim(text, SUPPORTED, ID[PRICE], "Product A costs 40 dollars",
                                            [evidence(ID[FAST], "Product A ships within 2 days")]),
                              indexes=[PRICE, FAST])
        self.assertEqual((together.verdict, together.additional_evidence),
                         (SUPPORTED, ((ID[FAST], "Product A ships within 2 days"),)))
        alone = self.judge(answer, claim(text, SUPPORTED, ID[PRICE], "Product A costs 40 dollars"),
                           indexes=[PRICE, FAST])
        self.assertEqual(alone.verdict, UNSUPPORTED)

    def test_contradicting_passage_is_recorded_with_its_source(self):
        judged = self.judge("Product A ships within 2 days [2].", claim(
            "Product A ships within 2 days.", SUPPORTED, ID[FAST], "Product A ships within 2 days",
            conflicting=[evidence(ID[SLOW], "Product A ships within 5 days")]))
        self.assertEqual((judged.verdict, judged.check), (PARTIALLY_SUPPORTED, CHECK_SUPPORT))
        self.assertEqual(judged.conflicting_evidence,
                         ((ID[SLOW], "Product A ships within 5 days"),))
        self.assertIn(f'contradicted by chunk {ID[SLOW]} (notice.pdf, page 3): '
                      f'"Product A ships within 5 days"', judged.evidence_error)

    def test_reported_conflicts_that_do_not_hold_up_are_ignored(self):
        cases = {
            "different subject": evidence(ID[OTHER_PRODUCT], "Product B ships within 5 days"),
            "quote not in chunk": evidence(ID[SLOW], "Product A ships within 9 days"),
            "chunk not retrieved": evidence(999, "Product A ships within 5 days"),
            "its own evidence": evidence(ID[FAST], "Product A ships within 2 days"),
            "unrelated passage": evidence(ID[PRICE], "Product A costs 40 dollars"),
        }
        for name, conflict in cases.items():
            with self.subTest(name):
                judged = self.judge("Product A ships within 2 days [2].", claim(
                    "Product A ships within 2 days.", SUPPORTED, ID[FAST],
                    "Product A ships within 2 days", conflicting=[conflict]))
                self.assertEqual((judged.verdict, judged.conflicting_evidence), (SUPPORTED, ()))

    def test_different_conditions_are_left_to_the_evaluator(self):
        self.assertIn("same conditions", SYSTEM_PROMPT)
        self.assertIn("do not conflict", SYSTEM_PROMPT)
        judged = self.judge("Product A ships within 2 days [2].", claim(
            "Product A ships within 2 days.", SUPPORTED, ID[FAST], "Product A ships within 2 days"))
        self.assertEqual(judged.verdict, SUPPORTED)

    def test_additional_evidence_from_an_unavailable_chunk_is_not_used(self):
        text = "Product A costs 40 dollars and ships within 2 days."
        judged = self.judge(f"{text[:-1]} [1].", claim(
            text, SUPPORTED, ID[PRICE], "Product A costs 40 dollars",
            [evidence(ID[FAST], "Product A ships within 2 days")]), indexes=[PRICE])
        self.assertEqual((judged.verdict, judged.additional_evidence), (UNSUPPORTED, ()))
        self.assertIn("number(s) 2", judged.evidence_error)


class SupportingChunksTest(unittest.TestCase):
    def test_carries_main_additional_and_conflicting_evidence_once(self):
        chunks = retrieved([PRICE, FAST, SLOW, HOLIDAY])
        claims = [
            ClaimVerdict("a", SUPPORTED, ID[PRICE], "q", SUPPORTED, None, None,
                         ((ID[FAST], "q"),), ((ID[SLOW], "q"),)),
            ClaimVerdict("b", PARTIALLY_SUPPORTED, ID[FAST], "q", SUPPORTED, None, None,
                         ((ID[PRICE], "q"),)),
            ClaimVerdict("c", UNSUPPORTED, None, None, SUPPORTED, "x", CHECK_EVIDENCE),
            SimpleNamespace(claim_text="stored", verdict=SUPPORTED, evidence_chunk_id=ID[HOLIDAY]),
        ]
        self.assertEqual([c.chunk_id for c in supporting_chunks(chunks, claims)],
                         [ID[PRICE], ID[FAST], ID[SLOW], ID[HOLIDAY]])
        self.assertEqual(supporting_chunks(chunks, claims[2:3]), [])


ANSWER_1 = "Product A costs 40 dollars and ships within 2 days [1][2]."
REWRITTEN = "Product A price and shipping time"


class CorrectionEvidenceTest(Pinned):
    """POST /query in RELI mode: what evidence each attempt has, and what it is judged on."""

    def setUp(self):
        super().setUp()
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                               poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        self.Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with self.Session() as db:
            documents = {name: Document(filename=name, total_pages=6, total_chunks=2)
                         for name in ("catalog.pdf", "notice.pdf", "staff.pdf")}
            rows = [DocumentChunk(document=documents[name], page_number=page, chunk_index=i,
                                  content=text) for i, (name, page, text) in enumerate(CHUNKS)]
            db.add_all([*documents.values(), *rows])
            db.commit()
            self.ids = [row.id for row in rows]
            self.doc_ids = {name: document.id for name, document in documents.items()}

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def chunks(self, *indexes):
        return [RetrievedChunk(chunk_id=self.ids[i], document_id=self.doc_ids[CHUNKS[i][0]],
                               document=CHUNKS[i][0], page=CHUNKS[i][1], text=CHUNKS[i][2],
                               similarity=0.8 - 0.01 * rank)
                for rank, i in enumerate(indexes)]

    def first_evaluation(self, answer_relevance=0.5):
        """Attempt 1: the price and speed claim, backed by chunks PRICE and FAST together."""
        return reply([claim("Product A costs 40 dollars and ships within 2 days.", SUPPORTED,
                            self.ids[PRICE], "Product A costs 40 dollars",
                            [evidence(self.ids[FAST], "Product A ships within 2 days")])],
                     answer_relevance=answer_relevance)

    def post(self, *, retrievals, answers, evaluations, rewrites=(REWRITTEN,)):
        """`answers` are generator replies in order; `evaluations` maps answer text to reply."""
        prompts = []

        def evaluator(prompt, **_):
            prompts.append(prompt)
            answer = re.search(r"<answer>\n(.*?)\n</answer>", prompt, re.DOTALL).group(1)
            return llm_result(evaluations[answer])

        with patch("app.services.similarity_gate.retrieve", side_effect=list(retrievals)), \
             patch("app.services.generator.call_claude",
                   side_effect=[llm_result(a) for a in answers]), \
             patch("app.services.evaluator.call_claude", side_effect=evaluator), \
             patch("app.services.corrector.call_claude",
                   side_effect=[llm_result(r) for r in rewrites]):
            response = self.client.post("/query", json={"question": QUESTION, "mode": "reli"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(self.client.get(f"/query/{body['query_id']}").json(), body)
        return body, prompts

    @staticmethod
    def logged(attempt):
        return [(r["chunk_id"], r["filename"], r["page_number"]) for r in attempt["retrieval"]]

    def source(self, index):
        return (self.ids[index], CHUNKS[index][0], CHUNKS[index][1])

    def assert_consistent(self, attempt):
        """Stored claims, scores, and verdict equal the API's, and follow from each other."""
        evaluation = attempt["evaluation"]
        self.assertEqual(evaluation["faithfulness"],
                         compute_faithfulness([c["verdict"] for c in evaluation["claims"]]))
        self.assertEqual(evaluation["failure_type"], determine_failure_type(
            evaluation["faithfulness"], evaluation["answer_relevance"],
            evaluation["context_relevance"]))
        self.assertEqual(evaluation["passed"], evaluation["failure_type"] is None)
        available = {r["chunk_id"] for r in attempt["retrieval"]}
        for item in evaluation["claims"]:
            self.assertTrue(item["evidence_chunk_id"] is None
                            or item["evidence_chunk_id"] in available)
        with self.Session() as db:
            answer = db.scalars(select(Answer).where(
                Answer.attempt_number == attempt["attempt_number"]).order_by(Answer.id.desc())
            ).first()
            stored = db.scalars(select(Evaluation).where(Evaluation.answer_id == answer.id)).one()
            rows = db.scalars(select(Claim).where(Claim.evaluation_id == stored.id)
                              .order_by(Claim.id)).all()
        self.assertEqual((stored.faithfulness, stored.passed, stored.failure_type),
                         (evaluation["faithfulness"], evaluation["passed"],
                          evaluation["failure_type"]))
        self.assertEqual([(r.claim_text, r.verdict, r.evidence_chunk_id, r.evidence_quote,
                           r.evidence_error, r.check_name) for r in rows],
                         [(c["claim_text"], c["verdict"], c["evidence_chunk_id"],
                           c["evidence_quote"], c["evidence_error"], c["check_name"])
                          for c in evaluation["claims"]])

    def test_correction_keeps_original_evidence_once_with_its_sources(self):
        # The new retrieval repeats PRICE; FAST is only carried over from attempt 1.
        answer_2 = "Product A costs 40 dollars [1] and ships within 2 days [3]."
        body, prompts = self.post(
            retrievals=[self.chunks(PRICE, FAST), self.chunks(PRICE, SLOW)],
            answers=[ANSWER_1, answer_2],
            evaluations={ANSWER_1: self.first_evaluation(),
                         answer_2: reply([claim(
                             "Product A costs 40 dollars and ships within 2 days.", SUPPORTED,
                             self.ids[PRICE], "Product A costs 40 dollars",
                             [evidence(self.ids[FAST], "Product A ships within 2 days")])])})

        first, second = body["attempts"]
        self.assertEqual(self.logged(first), [self.source(PRICE), self.source(FAST)])
        self.assertEqual(self.logged(second),
                         [self.source(PRICE), self.source(SLOW), self.source(FAST)])
        self.assertEqual(second["strategy"], REWRITE)
        # Each attempt is evaluated with exactly its own logged passages.
        for prompt, attempt in zip(prompts, (first, second)):
            self.assertEqual([int(i) for i in re.findall(r"chunk_id=(\d+)", prompt)],
                             [r["chunk_id"] for r in attempt["retrieval"]])
        self.assertEqual((body["final_attempt_number"], body["final_answer"]), (2, answer_2))
        self.assertTrue(second["evaluation"]["passed"])
        self.assert_consistent(first)
        self.assert_consistent(second)

    def test_conflict_in_the_new_retrieval_is_recorded_and_attempt_1_is_kept(self):
        answer_2 = "Product A costs 40 dollars [1] and ships within 2 days [3]."
        body, _ = self.post(
            retrievals=[self.chunks(PRICE, FAST), self.chunks(PRICE, SLOW)],
            answers=[ANSWER_1, answer_2],
            evaluations={ANSWER_1: self.first_evaluation(),
                         answer_2: reply([claim(
                             "Product A costs 40 dollars and ships within 2 days.", SUPPORTED,
                             self.ids[PRICE], "Product A costs 40 dollars",
                             [evidence(self.ids[FAST], "Product A ships within 2 days")],
                             [evidence(self.ids[SLOW], "Product A ships within 5 days")])])})

        first, second = body["attempts"]
        conflicted = second["evaluation"]["claims"][0]
        self.assertEqual((conflicted["verdict"], conflicted["check_name"]),
                         (PARTIALLY_SUPPORTED, CHECK_SUPPORT))
        self.assertIn(f"chunk {self.ids[SLOW]} (notice.pdf, page 3)", conflicted["evidence_error"])
        # Attempt 1 has no conflicting passage, and its own verdict and scores are reported.
        self.assertEqual(body["final_attempt_number"], 1)
        self.assertEqual(body["final_answer"], ANSWER_1)
        self.assertEqual((first["evaluation"]["claims"][0]["verdict"],
                          first["evaluation"]["failure_type"]), (SUPPORTED, MISSING_INFO))
        self.assert_consistent(first)
        self.assert_consistent(second)

    def test_evidence_never_available_to_an_attempt_cannot_support_it(self):
        # Attempt 1 only uses PRICE and its passages were judged weak, so FAST is not carried
        # over and attempt 2 never has it.
        first_eval = reply([claim("Product A costs 40 dollars.", SUPPORTED, self.ids[PRICE],
                                  "Product A costs 40 dollars")], answer_relevance=0.5,
                           context_relevance=0.5)
        answer_1 = "Product A costs 40 dollars [1]."
        answer_2 = "Product A costs 40 dollars and ships within 2 days [1]."
        body, _ = self.post(
            retrievals=[self.chunks(PRICE, FAST), self.chunks(SLOW)],
            answers=[answer_1, answer_2],
            evaluations={answer_1: first_eval,
                         answer_2: reply([
                             claim("Product A costs 40 dollars and ships within 2 days.",
                                   SUPPORTED, self.ids[PRICE], "Product A costs 40 dollars",
                                   [evidence(self.ids[FAST], "Product A ships within 2 days")]),
                             claim("Product A ships within 2 days.", SUPPORTED, self.ids[FAST],
                                   "Product A ships within 2 days"),
                         ])})

        second = body["attempts"][1]
        self.assertEqual(self.logged(second), [self.source(SLOW), self.source(PRICE)])
        self.assertEqual([(c["verdict"], c["check_name"]) for c in second["evaluation"]["claims"]],
                         [(UNSUPPORTED, CHECK_SUPPORT), (UNSUPPORTED, CHECK_EVIDENCE)])
        self.assertIn("is not one of the retrieved chunks",
                      second["evaluation"]["claims"][1]["evidence_error"])
        self.assertEqual(body["final_attempt_number"], 1)
        self.assert_consistent(body["attempts"][0])
        self.assert_consistent(second)

    def test_failed_correction_retrieval_preserves_attempt_1(self):
        body, _ = self.post(
            retrievals=[self.chunks(PRICE, FAST), RuntimeError("vector store unavailable")],
            answers=[ANSWER_1], evaluations={ANSWER_1: self.first_evaluation()})

        self.assertEqual(len(body["attempts"]), 1)
        first = body["attempts"][0]
        self.assertEqual(self.logged(first), [self.source(PRICE), self.source(FAST)])
        self.assertEqual((body["final_attempt_number"], body["status"], body["final_answer"]),
                         (1, ANSWERED, ANSWER_1))
        self.assertEqual(first["evaluation"]["claims"][0]["verdict"], SUPPORTED)
        self.assert_consistent(first)

    def test_insufficient_evidence_and_evaluator_errors_are_unchanged(self):
        with patch("app.services.similarity_gate.retrieve",
                   return_value=self.chunks(PRICE)[:0]), \
             patch("app.services.generator.call_claude") as generator:
            gated = self.client.post("/query", json={"question": QUESTION, "mode": "reli"}).json()
        generator.assert_not_called()
        self.assertEqual((gated["status"], gated["attempts"][0]["evaluation"]),
                         (INSUFFICIENT_EVIDENCE, None))

        body, _ = self.post(retrievals=[self.chunks(PRICE, FAST)], answers=[ANSWER_1],
                            evaluations={ANSWER_1: "not json"}, rewrites=())
        evaluation = body["attempts"][0]["evaluation"]
        self.assertEqual((evaluation["passed"], evaluation["failure_type"],
                          evaluation["faithfulness"], evaluation["claims"]),
                         (False, EVALUATOR_ERROR, None, []))
        self.assertEqual(len(body["attempts"]), 1)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
