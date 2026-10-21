"""Regression tests for the known evaluation-pipeline defects, with negative controls.

Usage (from the project root or backend/):
    python backend/test_evaluation_regressions.py

Test names say what each test is:
- `test_defect<N>_...` states the intended behavior for known defect N. These are expected to
  FAIL on the current code and to pass once the staged fix for that defect lands.
- `test_control<N>_...` is a control for defect N: most are negative controls (a genuinely
  unsupported claim must stay unsupported), some check behavior that is already correct. They
  must pass both before and after the fixes, so a fix cannot weaken detection.
- `test_observed_...` covers a related false positive found while writing these tests; it is
  not one of the eight known defects.

Defect 6 tests use `claude_evidence_chunk_id` and `claude_evidence_quote` on the scored claim,
the stored claim, and the API claim: the evidence exactly as Claude gave it, kept when a check
rejects it, and never counted as support.

Defect 8 (frontend display) has no tests here: the display logic lives inside JSX components,
which the frontend's `node --test` runner cannot import without moving that logic into plain
modules first.

Documents are synthetic and deliberately unrelated to each other (network hardware, recipes,
history, bicycles, power plants, spacecraft, medication leaflets, software, business, contracts,
device maintenance, clinics) and use different layouts: prose, "Label: value" records,
numbered sections, bullet lists, and text split by the production chunker.

Offline: every Claude caller and retrieval are mocked, and the app runs against an in-memory
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
from sqlalchemy import create_engine, event, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Claim, Document, DocumentChunk  # noqa: E402
from app.services import answer_checks  # noqa: E402
from app.services.attempt_selection import (  # noqa: E402
    AttemptEvaluation,
    AttemptSummary,
    compare_attempts,
)
from app.services.corrector import supporting_chunks  # noqa: E402
from app.services.evaluator import (  # noqa: E402
    CHECK_EVIDENCE,
    CHECK_LIMITATION,
    CHECK_SUPPORT,
    CHECK_UNCITED,
    PARTIALLY_SUPPORTED,
    SUPPORTED,
    UNSUPPORTED,
    compute_faithfulness,
    evaluate_answer,
)
from app.services.generator import ANSWERED  # noqa: E402
from app.services.ingestion import split_text  # noqa: E402
from app.services.llm import LLMResult  # noqa: E402
from app.services.retrieval import RetrievedChunk  # noqa: E402

MODEL = "claude-test-model"
PINNED = {
    "claude_model": MODEL,
    "claude_max_tokens": 1024,
    "similarity_gate": 0.30,
    "evaluator_model": None,
    "evaluator_max_tokens": 2048,
    "evaluator_pass_threshold": 0.70,
    "evaluator_max_parse_attempts": 2,
}


def llm_result(text: str) -> LLMResult:
    return LLMResult(text=text, model=MODEL, input_tokens=10, output_tokens=10, latency_ms=1,
                     stop_reason="end_turn", attempts=1)


def chunk(chunk_id, text, document_id=1, document="doc.pdf", page=1):
    return RetrievedChunk(chunk_id=chunk_id, document_id=document_id, document=document,
                          page=page, text=text, similarity=0.8)


def claim(text, verdict=SUPPORTED, chunk_id=None, quote=None):
    return {"claim_text": text, "verdict": verdict, "evidence_chunk_id": chunk_id,
            "evidence_quote": quote}


def evaluator_reply(claims, limitations=None, answer_relevance=1.0, context_relevance=1.0,
                    feedback="Checked."):
    body = {"claims": claims, "answer_relevance": answer_relevance,
            "context_relevance": context_relevance, "feedback": feedback}
    if limitations is not None:
        body["limitations"] = limitations
    return json.dumps(body)


class Pinned(unittest.TestCase):
    def setUp(self):
        for name, value in PINNED.items():
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def evaluate(self, question, answer, retrieved, claims, limitations=None, **scores):
        with patch("app.services.evaluator.call_claude",
                   return_value=llm_result(evaluator_reply(claims, limitations, **scores))):
            result = evaluate_answer(question, answer, retrieved)
        self.assertEqual(result.faithfulness,
                         compute_faithfulness([c.verdict for c in result.claims]))
        return result

    def judge(self, question, answer, retrieved, judged_claim):
        """The scored version of `judged_claim` (matched by its text)."""
        result = self.evaluate(question, answer, retrieved, [judged_claim])
        matches = [c for c in result.claims if c.claim_text == judged_claim["claim_text"]]
        self.assertEqual(len(matches), 1, [c.claim_text for c in result.claims])
        return matches[0]

    def assert_verdict(self, judged, verdict):
        self.assertEqual(judged.verdict, verdict,
                         f"check={judged.check!r} reason={judged.evidence_error!r}")

    def assert_not_supported(self, judged):
        self.assertNotEqual(judged.verdict, SUPPORTED,
                            "a claim the evidence does not state was accepted as supported")


# --- Defect 1: quantities from the question and number words --------------------------------

ROUTER = chunk(101, "The X200 router is a home networking device. Notable features of the X200 "
                    "include mesh networking, guest isolation, and parental controls.",
               document="router-guide.pdf")
ROUTER_QUOTE = ("Notable features of the X200 include mesh networking, guest isolation, and "
                "parental controls")
RECIPE = chunk(102, "Shortbread. Ingredients: \u25cf\u200b flour \u25cf\u200b sugar \u25cf\u200b "
                    "butter \u25cf\u200b eggs Bake for 20 minutes.", document="recipes.pdf")
TREATIES = chunk(103, "The war ended in 1648 with the Treaty of Arden and the Treaty of Vell.",
                 document="history.pdf")
BICYCLES = chunk(104, "The Atlas and the Zephyr share the same aluminium frame.",
                 document="bikes.pdf")
WARRANTY = chunk(105, "The warranty lasts 2 years from the date of purchase.",
                 document="warranty.pdf")
PLANS = chunk(106, "The Basic plan costs 25 dollars per month.", document="pricing.pdf")
REACTORS = chunk(107, "Three reactors at the plant were shut down in 2011.",
                 document="plant-report.pdf")


class QuestionQuantityTest(Pinned):
    def test_defect1_count_from_the_question_with_every_listed_item_in_the_evidence(self):
        cases = {
            "prose list": (
                "What are three notable features of the X200 router?",
                "Three notable features of the X200 router are mesh networking, guest "
                "isolation, and parental controls.", ROUTER, ROUTER_QUOTE),
            "bullet list": (
                "What are four ingredients in the shortbread?",
                "Four ingredients in the shortbread are flour, sugar, butter, and eggs.",
                RECIPE, "Ingredients: \u25cf flour \u25cf sugar \u25cf butter \u25cf eggs"),
            "named items": (
                "Which two treaties ended the war?",
                "The two treaties that ended the war were the Treaty of Arden and the Treaty "
                "of Vell.", TREATIES,
                "The war ended in 1648 with the Treaty of Arden and the Treaty of Vell"),
        }
        for name, (question, text, evidence, quote) in cases.items():
            with self.subTest(name):
                judged = self.judge(question, f"{text[:-1]} [1].", [evidence],
                                    claim(text, SUPPORTED, evidence.chunk_id, quote))
                self.assert_verdict(judged, SUPPORTED)

    def test_defect1_number_word_referring_to_entities_the_question_names(self):
        text = "The two bicycles share the same aluminium frame."
        judged = self.judge("How do the Atlas and Zephyr bicycles compare?", f"{text[:-1]} [1].",
                            [BICYCLES], claim(text, SUPPORTED, BICYCLES.chunk_id,
                                              "The Atlas and the Zephyr share the same "
                                              "aluminium frame"))
        self.assert_verdict(judged, SUPPORTED)

    def test_control1_question_number_restated_as_a_fact_the_evidence_contradicts(self):
        cases = {
            "duration": ("Does the warranty last 3 years?", "The warranty lasts 3 years.",
                         WARRANTY, "The warranty lasts 2 years"),
            "price": ("Which plan costs 20 dollars per month?",
                      "The Basic plan costs 20 dollars per month.", PLANS,
                      "The Basic plan costs 25 dollars per month"),
        }
        for name, (question, text, evidence, quote) in cases.items():
            with self.subTest(name):
                judged = self.judge(question, f"{text[:-1]} [1].", [evidence],
                                    claim(text, SUPPORTED, evidence.chunk_id, quote))
                self.assert_verdict(judged, UNSUPPORTED)

    def test_control1_count_with_an_item_missing_from_the_evidence_is_not_supported(self):
        text = ("Three notable features of the X200 router are mesh networking, guest "
                "isolation, and a VPN server.")
        judged = self.judge("What are three notable features of the X200 router?",
                            f"{text[:-1]} [1].", [ROUTER],
                            claim(text, SUPPORTED, ROUTER.chunk_id, ROUTER_QUOTE))
        self.assert_not_supported(judged)

    def test_control1_count_that_does_not_match_the_listed_items_is_not_supported(self):
        text = ("Three notable features of the X200 router are mesh networking and guest "
                "isolation.")
        judged = self.judge("What are three notable features of the X200 router?",
                            f"{text[:-1]} [1].", [ROUTER],
                            claim(text, SUPPORTED, ROUTER.chunk_id, ROUTER_QUOTE))
        self.assert_not_supported(judged)

    def test_control1_number_word_contradicted_by_the_evidence_count(self):
        text = "The two reactors at the plant were shut down in 2011."
        judged = self.judge("What happened to the reactors at the plant in 2011?",
                            f"{text[:-1]} [1].", [REACTORS],
                            claim(text, SUPPORTED, REACTORS.chunk_id,
                                  "reactors at the plant were shut down in 2011"))
        self.assert_verdict(judged, UNSUPPORTED)


# --- Defect 2: field labels and sentence-initial entities -----------------------------------

SPEC_SHEET = chunk(201, "Model X200 Release date: March 3, 2021\u200b Weight: 1.2 kg\u200b "
                        "Manufacturer: Acme Corp Model X300 Release date: May 9, 2022\u200b "
                        "Weight: 1.5 kg\u200b Manufacturer: Acme Corp",
                   document="spec-sheet.pdf")
SATELLITES = chunk(202, "3. Kestrel Original launch date: June 2, 2019\u200b Orbit: polar "
                        "4. Falcon Original launch date: May 1, 2020\u200b Orbit: equatorial",
                   document="satellites.pdf")
LEAFLET = chunk(203, "Amoxicillin 500 mg capsules Dosage: one capsule three times daily\u200b "
                     "Storage: below 25 \u00b0C Ibuprofen 200 mg tablets Dosage: one tablet "
                     "every six hours\u200b Storage: below 30 \u00b0C", document="leaflet.pdf")
LANGUAGES = chunk(204, "While Python introduced the feature, Rust extended that approach with "
                       "stricter checks.", document="languages.pdf")
VENDORS = chunk(205, "While Acme introduced the subscription model, Globex extended it to "
                     "enterprise customers.", document="market-report.pdf")
SATELLITE_QUESTION = "When were the Kestrel and Falcon satellites launched?"
LEAFLET_QUESTION = "How should Amoxicillin and Ibuprofen be taken?"
VENDOR_QUESTION = "Did Initech or Globex extend the subscription model that Acme introduced?"


class SubjectMatchingTest(Pinned):
    def test_defect2_value_under_a_field_label_supports_its_records_claim(self):
        cases = {
            "single-word records": (
                "When were the X200 and X300 released?", "The X200 was released on March 3, 2021.",
                SPEC_SHEET, "Release date: March 3, 2021"),
            "numbered sections, multi-word label": (
                SATELLITE_QUESTION, "Kestrel was originally launched on June 2, 2019.",
                SATELLITES, "Original launch date: June 2, 2019"),
        }
        for name, (question, text, evidence, quote) in cases.items():
            with self.subTest(name):
                judged = self.judge(question, f"{text[:-1]} [1].", [evidence],
                                    claim(text, SUPPORTED, evidence.chunk_id, quote))
                self.assert_verdict(judged, SUPPORTED)

    def test_defect2_entity_at_the_start_of_the_claim_is_its_subject(self):
        cases = {
            "software": ("How did Rust build on Python's feature?",
                         "Rust extended Python's approach with stricter checks.", LANGUAGES,
                         "Rust extended that approach with stricter checks"),
            "business": (VENDOR_QUESTION,
                         "Globex extended Acme's subscription model to enterprise customers.",
                         VENDORS, "Globex extended it to enterprise customers"),
        }
        for name, (question, text, evidence, quote) in cases.items():
            with self.subTest(name):
                judged = self.judge(question, f"{text[:-1]} [1].", [evidence],
                                    claim(text, SUPPORTED, evidence.chunk_id, quote))
                self.assert_verdict(judged, SUPPORTED)

    def test_defect2_record_of_another_entity_does_not_support_a_sentence_initial_subject(self):
        text = "Ibuprofen is taken as one capsule three times daily."
        judged = self.judge(LEAFLET_QUESTION, f"{text[:-1]} [1].", [LEAFLET],
                            claim(text, SUPPORTED, LEAFLET.chunk_id,
                                  "Dosage: one capsule three times daily"))
        self.assert_not_supported(judged)

    def test_control2_record_value_does_not_support_another_records_claim(self):
        cases = {
            "single-word records": (
                "When were the X200 and X300 released?", "The X300 was released on March 3, 2021.",
                SPEC_SHEET, "Release date: March 3, 2021"),
            "numbered sections": (
                SATELLITE_QUESTION, "Falcon was originally launched on June 2, 2019.",
                SATELLITES, "Original launch date: June 2, 2019"),
        }
        for name, (question, text, evidence, quote) in cases.items():
            with self.subTest(name):
                judged = self.judge(question, f"{text[:-1]} [1].", [evidence],
                                    claim(text, SUPPORTED, evidence.chunk_id, quote))
                self.assert_not_supported(judged)

    def test_control2_record_value_supports_its_own_sentence_initial_subject(self):
        text = "Amoxicillin is taken as one capsule three times daily."
        judged = self.judge(LEAFLET_QUESTION, f"{text[:-1]} [1].", [LEAFLET],
                            claim(text, SUPPORTED, LEAFLET.chunk_id,
                                  "Dosage: one capsule three times daily"))
        self.assert_verdict(judged, SUPPORTED)

    def test_control2_wrong_sentence_initial_subject_is_not_supported(self):
        text = "Initech extended Acme's subscription model to enterprise customers."
        judged = self.judge(VENDOR_QUESTION, f"{text[:-1]} [1].", [VENDORS],
                            claim(text, SUPPORTED, VENDORS.chunk_id,
                                  "Globex extended it to enterprise customers"))
        self.assert_not_supported(judged)

    def test_defect2_swapped_subjects_with_a_sentence_initial_entity_are_not_supported(self):
        text = "Python extended Rust's approach with stricter checks."
        judged = self.judge("How did Rust build on Python's feature?", f"{text[:-1]} [1].",
                            [LANGUAGES], claim(text, SUPPORTED, LANGUAGES.chunk_id,
                                               "Rust extended that approach with stricter "
                                               "checks"))
        self.assert_not_supported(judged)


# --- Defect 3: hedge detection scope ---------------------------------------------------------

CLINIC_SERVICES = chunk(301, "The clinic offers vaccinations, blood tests, and physiotherapy "
                             "sessions that are usually booked a week ahead.",
                        document="clinic.pdf")
EXPORTER = chunk(302, "The tool exports CSV files, JSON files, and reports that may include "
                      "charts.", document="tool-manual.pdf")
SIDE_EFFECTS = chunk(303, "Patients may experience mild headaches after the dose.",
                     document="trial-summary.pdf")


class HedgeScopeTest(Pinned):
    def test_defect3_hedge_in_another_clause_does_not_qualify_the_claim(self):
        cases = {
            "clinic": ("What does the clinic offer?", "The clinic offers vaccinations and blood tests.",
                       CLINIC_SERVICES, "The clinic offers vaccinations, blood tests"),
            "software": ("Which formats does the tool export?",
                         "The tool exports CSV files and JSON files.", EXPORTER,
                         "The tool exports CSV files, JSON files"),
        }
        for name, (question, text, evidence, quote) in cases.items():
            with self.subTest(name):
                judged = self.judge(question, f"{text[:-1]} [1].", [evidence],
                                    claim(text, SUPPORTED, evidence.chunk_id, quote))
                self.assert_verdict(judged, SUPPORTED)

    def test_control3_hedge_that_qualifies_the_quoted_clause_is_kept(self):
        text = "Patients experience mild headaches after the dose."
        for quote in ("experience mild headaches after the dose",
                      "Patients may experience mild headaches after the dose"):
            with self.subTest(quote=quote):
                judged = self.judge("What side effects were reported?", f"{text[:-1]} [1].",
                                    [SIDE_EFFECTS], claim(text, SUPPORTED, SIDE_EFFECTS.chunk_id,
                                                          quote))
                self.assert_verdict(judged, PARTIALLY_SUPPORTED)


# --- Defect 4: quotes across contiguous chunks -----------------------------------------------

CONTRACT_TEXT = ("Clause 7. The supplier shall replace defective parts within thirty days of written "
                 "notice from the buyer. Clause 8. The buyer shall pay each invoice within "
                 "forty-five days of receipt. Clause 9. Either party may end this agreement with "
                 "ninety days of written notice.")
CONTRACT = split_text(CONTRACT_TEXT, size=100, overlap=25)
STEPS_TEXT = ("Step 1: Remove the battery cover and disconnect the sensor cable from the main "
              "board. Step 2: Clean the sensor lens with a dry cloth. Step 3: Reconnect the cable "
              "and close the cover.")
STEPS = split_text(STEPS_TEXT, size=90, overlap=30)
CLAUSE_7 = ("The supplier shall replace defective parts within thirty days of written notice "
            "from the buyer")
STEP_2 = "Step 2: Clean the sensor lens with a dry cloth"


def contract_chunk(index, document_id=1):
    return chunk(400 + index, CONTRACT[index], document_id=document_id,
                 document="supply-contract.pdf" if document_id == 1 else "other-contract.pdf")


def steps_chunk(index):
    return chunk(410 + index, STEPS[index], document_id=3, document="maintenance.pdf")


class ContiguousChunkTest(Pinned):
    QUESTION = "How quickly must the supplier replace defective parts?"
    CLAIM = "The supplier shall replace defective parts within thirty days of written notice from the buyer."

    def test_fixtures_come_from_the_production_chunker(self):
        self.assertGreaterEqual(len(CONTRACT), 3)
        self.assertFalse(answer_checks.quote_occurs(CLAUSE_7, CONTRACT[0]))
        self.assertFalse(answer_checks.quote_occurs(CLAUSE_7, CONTRACT[1]))
        self.assertTrue(answer_checks.quote_occurs(CLAUSE_7, CONTRACT_TEXT))
        self.assertFalse(answer_checks.quote_occurs(STEP_2, STEPS[0]))
        self.assertTrue(answer_checks.quote_occurs(STEP_2, STEPS[1]))
        self.assertTrue(STEPS[0].endswith("Step"))

    def test_defect4_quote_across_a_chunk_boundary_is_verified(self):
        judged = self.judge(self.QUESTION, f"{self.CLAIM[:-1]} [1][2].",
                            [contract_chunk(0), contract_chunk(1)],
                            claim(self.CLAIM, SUPPORTED, contract_chunk(0).chunk_id, CLAUSE_7))
        self.assert_verdict(judged, SUPPORTED)

    def test_defect4_quote_cut_off_in_the_cited_chunk_and_complete_in_the_next(self):
        text = "Step 2 is to clean the sensor lens with a dry cloth."
        judged = self.judge("How is the sensor lens cleaned?", f"{text[:-1]} [2].",
                            [steps_chunk(0), steps_chunk(1)],
                            claim(text, SUPPORTED, steps_chunk(0).chunk_id, STEP_2))
        self.assert_verdict(judged, SUPPORTED)

    def test_control4_continuation_not_retrieved_or_not_adjacent(self):
        for name, retrieved in {"only the cited chunk": [contract_chunk(0)],
                                "a later, non-adjacent chunk": [contract_chunk(0),
                                                                contract_chunk(2)]}.items():
            with self.subTest(name):
                judged = self.judge(self.QUESTION, f"{self.CLAIM[:-1]} [1].", retrieved,
                                    claim(self.CLAIM, SUPPORTED, contract_chunk(0).chunk_id,
                                          CLAUSE_7))
                self.assertEqual((judged.verdict, judged.check), (UNSUPPORTED, CHECK_EVIDENCE))

    def test_control4_identical_text_in_another_document_is_not_a_continuation(self):
        judged = self.judge(self.QUESTION, f"{self.CLAIM[:-1]} [1][2].",
                            [contract_chunk(0), contract_chunk(1, document_id=2)],
                            claim(self.CLAIM, SUPPORTED, contract_chunk(0).chunk_id, CLAUSE_7))
        self.assertEqual((judged.verdict, judged.check), (UNSUPPORTED, CHECK_EVIDENCE))

    def test_control4_altered_quote_across_the_boundary_is_unsupported(self):
        text = "The supplier shall replace defective parts within sixty days of written notice from the buyer."
        judged = self.judge(self.QUESTION, f"{text[:-1]} [1][2].",
                            [contract_chunk(0), contract_chunk(1)],
                            claim(text, SUPPORTED, contract_chunk(0).chunk_id,
                                  CLAUSE_7.replace("thirty", "sixty")))
        self.assertEqual((judged.verdict, judged.check), (UNSUPPORTED, CHECK_EVIDENCE))


# --- Defect 5: limitation statements ---------------------------------------------------------

CLINIC_HOURS = chunk(501, "Opening hours. The clinic opens at 8 am on weekdays.",
                     document="clinic-hours.pdf")
RELEASE_NOTES = chunk(502, "Release notes. Version 4.2 removed the legacy API and added streaming "
                           "exports.", document="release-notes.pdf")
OPENS = claim("The clinic opens at 8 am.", SUPPORTED, CLINIC_HOURS.chunk_id,
              "The clinic opens at 8 am")
REMOVED = claim("Version 4.2 removed the legacy API.", SUPPORTED, RELEASE_NOTES.chunk_id,
                "Version 4.2 removed the legacy API")


class LimitationTest(Pinned):
    def limited(self, question, fact, evidence, limitation):
        answer = f"{fact['claim_text'][:-1]} [1]. {limitation}"
        return self.evaluate(question, answer, [evidence], [fact], [limitation])

    def test_defect5_leading_however_does_not_turn_a_limitation_into_a_claim(self):
        limitation = "However, the passages do not state when the clinic closes."
        self.assertTrue(answer_checks.is_pure_limitation(limitation))
        result = self.limited("When is the clinic open?", OPENS, CLINIC_HOURS, limitation)
        self.assertEqual([c.claim_text for c in result.claims], [OPENS["claim_text"]])
        self.assertEqual(result.faithfulness, 1.0)

    def test_defect5_limitation_contradicting_the_answers_own_claim_is_scored(self):
        cases = {
            "clinic": ("When does the clinic open?", OPENS, CLINIC_HOURS,
                       "The passages do not state when the clinic opens."),
            "software": ("What changed in version 4.2?", REMOVED, RELEASE_NOTES,
                         "The passages do not mention the legacy API."),
        }
        for name, (question, fact, evidence, limitation) in cases.items():
            with self.subTest(name):
                result = self.limited(question, fact, evidence, limitation)
                scored = {c.claim_text: c.verdict for c in result.claims}
                self.assertEqual(scored.get(limitation), UNSUPPORTED, scored)
                self.assertLess(result.faithfulness, 1.0)

    def test_control5_limitation_about_something_else_is_not_scored(self):
        cases = {
            "clinic": ("When is the clinic open?", OPENS, CLINIC_HOURS,
                       "The passages do not state when the clinic closes."),
            "software": ("What changed in version 4.2?", REMOVED, RELEASE_NOTES,
                         "The passages do not mention a replacement for the legacy API."),
        }
        for name, (question, fact, evidence, limitation) in cases.items():
            with self.subTest(name):
                result = self.limited(question, fact, evidence, limitation)
                self.assertEqual([c.claim_text for c in result.claims], [fact["claim_text"]])
                self.assertEqual(result.faithfulness, 1.0)

    def test_defect5_leading_discourse_markers_before_genuine_limitations(self):
        for limitation in ("However, the passages do not state when the clinic closes.",
                           "However the passages do not state when the clinic closes.",
                           "But the passages do not state when the clinic closes.",
                           "Yet the context does not specify the closing time.",
                           "- However, the documents do not mention the closing time.",
                           "However, the passages do not state when, or whether, the clinic "
                           "closes."):
            with self.subTest(limitation=limitation):
                self.assertTrue(answer_checks.is_pure_limitation(limitation))
                result = self.limited("When is the clinic open?", OPENS, CLINIC_HOURS, limitation)
                self.assertEqual([c.claim_text for c in result.claims], [OPENS["claim_text"]])
                self.assertEqual(result.faithfulness, 1.0)
                self.assertIn("1 limitation statement(s) were not scored", result.feedback)

    def test_control5_leading_marker_does_not_hide_a_factual_statement(self):
        for statement in (
                "However, the clinic closes at 6 pm.",
                "However, the clinic closes at 6 pm and the passages do not state the opening "
                "days.",
                "However, the passages do not state the closing time, but the clinic closes at "
                "6 pm.",
                "But the passages do not state the closing time, although the clinic closes "
                "at 6 pm.",
                "Although the passages give the opening time, they do not state the closing "
                "time."):
            with self.subTest(statement=statement):
                self.assertFalse(answer_checks.is_pure_limitation(statement))
                result = self.limited("When is the clinic open?", OPENS, CLINIC_HOURS, statement)
                scored = {c.claim_text: (c.verdict, c.check) for c in result.claims}
                self.assertEqual(scored.get(statement), (UNSUPPORTED, CHECK_LIMITATION), scored)
                self.assertEqual(result.faithfulness, 0.5)

    def test_control5_factual_sentence_starting_with_however_is_judged_as_a_claim(self):
        hours = chunk(503, "Opening hours. The clinic opens at 8 am on weekdays. The clinic "
                           "closes at 6 pm.", document="clinic-hours.pdf")
        closes = "However, the clinic closes at 6 pm."
        supported = self.evaluate(
            "When is the clinic open?", f"{OPENS['claim_text'][:-1]} [1]. {closes[:-1]} [1].",
            [hours], [dict(OPENS, evidence_chunk_id=503),
                      claim(closes, SUPPORTED, 503, "The clinic closes at 6 pm")])
        self.assertEqual([(c.verdict, c.check) for c in supported.claims],
                         [(SUPPORTED, None), (SUPPORTED, None)])
        uncited = self.evaluate("When is the clinic open?",
                                f"{OPENS['claim_text'][:-1]} [1]. {closes}", [hours],
                                [dict(OPENS, evidence_chunk_id=503)])
        self.assertEqual([(c.claim_text, c.verdict, c.check) for c in uncited.claims],
                         [(OPENS["claim_text"], SUPPORTED, None),
                          (closes, UNSUPPORTED, CHECK_UNCITED)])

    def test_control5_limitation_that_also_asserts_a_fact_is_scored(self):
        mixed = "The passages do not state the closing time; however, the clinic closes at 6 pm."
        self.assertFalse(answer_checks.is_pure_limitation(mixed))
        result = self.limited("When is the clinic open?", OPENS, CLINIC_HOURS, mixed)
        scored = {c.claim_text: c.verdict for c in result.claims}
        self.assertEqual(scored.get(mixed), UNSUPPORTED, scored)


# --- Defect 6: evidence and explanations of downgraded claims --------------------------------

NUMBER_MISMATCH = claim("The warranty lasts 3 years.", SUPPORTED, WARRANTY.chunk_id,
                        "The warranty lasts 2 years")
MISQUOTED = claim("The warranty lasts 2 years.", SUPPORTED, WARRANTY.chunk_id,
                  "The warranty is valid for 2 years")


class DowngradedEvidenceTest(Pinned):
    QUESTION = "How long does the warranty last?"

    def downgraded(self, judged_claim):
        judged = self.judge(self.QUESTION, f"{judged_claim['claim_text'][:-1]} [1].", [WARRANTY],
                            judged_claim)
        self.assertEqual(judged.verdict, UNSUPPORTED)
        return judged

    def test_defect6_downgraded_claim_keeps_the_evidence_claude_gave(self):
        for name, (judged_claim, check) in {"failed support check": (NUMBER_MISMATCH, CHECK_SUPPORT),
                                            "quote not found": (MISQUOTED, CHECK_EVIDENCE)}.items():
            with self.subTest(name):
                judged = self.downgraded(judged_claim)
                self.assertEqual(judged.check, check)
                self.assertEqual(
                    (getattr(judged, "claude_evidence_chunk_id", "<missing>"),
                     getattr(judged, "claude_evidence_quote", "<missing>")),
                    (judged_claim["evidence_chunk_id"], judged_claim["evidence_quote"]))

    def test_control6_rejected_evidence_never_counts_as_support(self):
        judged = self.downgraded(NUMBER_MISMATCH)
        self.assertEqual((judged.evidence_chunk_id, judged.evidence_quote), (None, None))
        self.assertEqual(judged.evidence, [])
        self.assertEqual(supporting_chunks([WARRANTY], [judged]), [])
        self.assertIn("number(s) 3", judged.evidence_error)

    def original(self, judged):
        return (getattr(judged, "claude_evidence_chunk_id", "<missing>"),
                getattr(judged, "claude_evidence_quote", "<missing>"))

    def test_defect6_supported_claim_records_the_same_original_and_verified_evidence(self):
        quote = "The warranty lasts 2 years"
        judged = self.judge(self.QUESTION, "The warranty lasts 2 years [1].", [WARRANTY],
                            claim("The warranty lasts 2 years.", SUPPORTED, WARRANTY.chunk_id,
                                  quote))
        self.assertEqual((judged.verdict, judged.claude_verdict, judged.check),
                         (SUPPORTED, SUPPORTED, None))
        self.assertEqual((judged.evidence_chunk_id, judged.evidence_quote),
                         (WARRANTY.chunk_id, quote))
        self.assertEqual(self.original(judged), (WARRANTY.chunk_id, quote))

    def test_defect6_partial_downgrade_keeps_verified_and_original_evidence(self):
        quote = "experience mild headaches after the dose"
        judged = self.judge("What side effects were reported?",
                            "Patients experience mild headaches after the dose [1].",
                            [SIDE_EFFECTS], claim("Patients experience mild headaches after "
                                                  "the dose.", SUPPORTED, SIDE_EFFECTS.chunk_id,
                                                  quote))
        self.assertEqual((judged.verdict, judged.claude_verdict, judged.check),
                         (PARTIALLY_SUPPORTED, SUPPORTED, CHECK_SUPPORT))
        self.assertEqual((judged.evidence_chunk_id, judged.evidence_quote),
                         (SIDE_EFFECTS.chunk_id, quote))
        self.assertEqual(self.original(judged), (SIDE_EFFECTS.chunk_id, quote))

    def test_defect6_claim_claude_judged_unsupported_or_a_check_added_has_no_original_evidence(self):
        answer = ("The warranty covers accidental damage [1]. The warranty is transferable to new "
                  "owners. The passages do not state who issues the warranty.")
        result = self.evaluate(
            self.QUESTION, answer, [WARRANTY],
            [claim("The warranty covers accidental damage.", UNSUPPORTED)],
            ["The passages do not state who issues the warranty.",
             "The warranty is extended for registered products."])
        self.assertEqual(
            [(c.claim_text, c.verdict, c.claude_verdict, c.check, c.evidence_chunk_id)
             + self.original(c) for c in result.claims],
            [("The warranty covers accidental damage.", UNSUPPORTED, UNSUPPORTED, None, None,
              None, None),
             ("The warranty is extended for registered products.", UNSUPPORTED, None,
              CHECK_LIMITATION, None, None, None),
             ("The warranty is transferable to new owners.", UNSUPPORTED, None, CHECK_UNCITED,
              None, None, None)])


class DowngradedEvidenceApiTest(unittest.TestCase):
    QUESTION = "How long does the warranty last?"

    def setUp(self):
        for name, value in PINNED.items():
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                               poolclass=StaticPool)

        # Enforce foreign keys as PostgreSQL does, so storing a rejected chunk ID is checked.
        @event.listens_for(engine, "connect")
        def _enforce_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        self.Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with self.Session() as db:
            document = Document(filename="warranty.pdf", total_pages=1, total_chunks=1)
            row = DocumentChunk(document=document, page_number=1, chunk_index=0,
                                content=WARRANTY.text)
            db.add_all([document, row])
            db.commit()
            self.retrieved = [RetrievedChunk(chunk_id=row.id, document_id=document.id,
                                             document="warranty.pdf", page=1, text=row.content,
                                             similarity=0.8)]

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def query(self, text="The warranty lasts 3 years.", chunk_id=None,
              quote="The warranty lasts 2 years"):
        chunk_id = self.retrieved[0].chunk_id if chunk_id is None else chunk_id
        judged = claim(text, SUPPORTED, chunk_id, quote)
        with patch("app.services.similarity_gate.retrieve", return_value=self.retrieved), \
             patch("app.services.generator.call_claude",
                   return_value=llm_result(f"{text[:-1]} [1].")), \
             patch("app.services.evaluator.call_claude",
                   return_value=llm_result(evaluator_reply([judged]))):
            response = self.client.post("/query", json={"question": self.QUESTION,
                                                        "mode": "basic"})
        self.assertEqual(response.status_code, 200, response.text)
        evaluation = response.json()["attempts"][0]["evaluation"]
        self.assertIsNotNone(evaluation, "the evaluation was not saved")
        [api_claim] = evaluation["claims"]
        with self.Session() as db:
            stored = db.scalars(select(Claim)).one()
        listed = self.client.get("/evaluations").json()["items"][0]["claims"]
        self.assertEqual(listed, [api_claim])
        return chunk_id, api_claim, stored

    def test_defect6_invented_chunk_id_is_kept_and_stored(self):
        _, api_claim, stored = self.query(text="The warranty lasts 2 years.", chunk_id=999999)
        self.assertEqual((api_claim["verdict"], api_claim["check_name"],
                          api_claim["evidence_chunk_id"], api_claim["evidence_quote"]),
                         (UNSUPPORTED, CHECK_EVIDENCE, None, None))
        self.assertEqual((api_claim.get("claude_evidence_chunk_id"),
                          api_claim.get("claude_evidence_quote")),
                         (999999, "The warranty lasts 2 years"))
        self.assertEqual((getattr(stored, "claude_evidence_chunk_id", None),
                          stored.evidence_chunk_id), (999999, None))

    def test_control6_supported_claim_api_fields_are_unchanged(self):
        chunk_id, api_claim, stored = self.query(text="The warranty lasts 2 years.")
        self.assertEqual(
            {key: api_claim[key] for key in ("claim_text", "verdict", "evidence_chunk_id",
                                             "evidence_quote", "claude_verdict",
                                             "evidence_error", "check_name")},
            {"claim_text": "The warranty lasts 2 years.", "verdict": SUPPORTED,
             "evidence_chunk_id": chunk_id, "evidence_quote": "The warranty lasts 2 years",
             "claude_verdict": SUPPORTED, "evidence_error": None, "check_name": None})
        self.assertEqual((stored.evidence_chunk_id, stored.verdict), (chunk_id, SUPPORTED))

    def test_defect6_rejected_evidence_is_stored_and_returned(self):
        chunk_id, api_claim, stored = self.query()
        expected = (chunk_id, "The warranty lasts 2 years")
        self.assertEqual((api_claim.get("claude_evidence_chunk_id"),
                          api_claim.get("claude_evidence_quote")), expected)
        self.assertEqual((getattr(stored, "claude_evidence_chunk_id", None),
                          getattr(stored, "claude_evidence_quote", None)), expected)

    def test_control6_downgrade_reason_is_stored_and_returned(self):
        _, api_claim, stored = self.query()
        self.assertEqual((api_claim["verdict"], api_claim["check_name"]),
                         (UNSUPPORTED, CHECK_SUPPORT))
        self.assertIn("number(s) 3", api_claim["evidence_error"])
        self.assertEqual(stored.evidence_error, api_claim["evidence_error"])
        self.assertIsNone(api_claim["evidence_chunk_id"])


# --- Defect 7: a correct, complete retry must not lose to an incomplete first attempt --------

PROBE_QUESTION = "Which team built the Orion probe, and what are three instruments it carries?"
PROBE_TEXTS = [
    "Mission overview. The Orion probe was built by the Kestrel team. The probe carries several "
    "scientific instruments.",
    "Orion payload. Its instruments include a magnetometer, a dust counter, and a radio receiver.",
]
BUILT = "The Orion probe was built by the Kestrel team."
INSTRUMENTS_QUOTE = "Its instruments include a magnetometer, a dust counter, and a radio receiver"
LIMITATION = "The passages do not list the instruments the Orion probe carries."


class CompleteRetrySelectionTest(unittest.TestCase):
    def setUp(self):
        for name, value in PINNED.items():
            patcher = patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                               poolclass=StaticPool)
        Base.metadata.create_all(engine)
        self.addCleanup(engine.dispose)
        self.Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with self.Session() as db:
            document = Document(filename="mission.pdf", total_pages=2, total_chunks=2)
            rows = [DocumentChunk(document=document, page_number=i + 1, chunk_index=i,
                                  content=text) for i, text in enumerate(PROBE_TEXTS)]
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

    def retrieved(self, indexes):
        return [RetrievedChunk(chunk_id=self.ids[i], document_id=self.document_id,
                               document="mission.pdf", page=i + 1, text=PROBE_TEXTS[i],
                               similarity=0.8 - 0.01 * rank)
                for rank, i in enumerate(indexes)]

    def run_query(self, instruments):
        built = claim(BUILT, SUPPORTED, self.ids[0], BUILT[:-1])
        listed = (f"Three instruments the Orion probe carries are {instruments}.")
        first_answer = f"{BUILT[:-1]} [1]. {LIMITATION}"
        second_answer = f"{BUILT[:-1]} [1]. {listed[:-1]} [2]."
        evaluations = [
            evaluator_reply([built], [LIMITATION], answer_relevance=0.5, context_relevance=0.5,
                            feedback="The instruments are not listed in the passages."),
            evaluator_reply([built, claim(listed, SUPPORTED, self.ids[1], INSTRUMENTS_QUOTE)]),
        ]
        with patch("app.services.similarity_gate.retrieve",
                   side_effect=[self.retrieved([0]), self.retrieved([0, 1])]), \
             patch("app.services.generator.call_claude",
                   side_effect=[llm_result(first_answer), llm_result(second_answer)]), \
             patch("app.services.evaluator.call_claude",
                   side_effect=[llm_result(text) for text in evaluations]), \
             patch("app.services.corrector.call_claude",
                   return_value=llm_result("Orion probe instrument list")):
            response = self.client.post("/query", json={"question": PROBE_QUESTION,
                                                        "mode": "reli"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(len(body["attempts"]), 2)
        self.assertEqual(body["attempts"][1]["answer"], second_answer)
        return body, listed

    def test_defect7_complete_and_correct_retry_is_reported(self):
        body, _ = self.run_query("a magnetometer, a dust counter, and a radio receiver")
        retry = body["attempts"][1]["evaluation"]
        self.assertTrue(retry["passed"], retry)
        self.assertEqual((body["status"], body["final_attempt_number"]), (ANSWERED, 2),
                         body["selection_reason"])

    def test_control7_retry_with_an_invented_list_item_does_not_replace_the_first(self):
        body, listed = self.run_query("a magnetometer, a dust counter, and a plasma camera")
        verdicts = {c["claim_text"]: c["verdict"] for c in body["attempts"][1]["evaluation"]["claims"]}
        self.assertEqual(verdicts[listed], UNSUPPORTED)
        self.assertEqual(body["final_attempt_number"], 1, body["selection_reason"])

    def test_control7_selection_policy_still_rejects_a_large_faithfulness_loss(self):
        def attempt(number, faithfulness, completeness, passed):
            return AttemptSummary(number, ANSWERED, AttemptEvaluation(
                passed, None if passed else "unsupported_claim", faithfulness, completeness, 1.0))
        better, _ = compare_attempts(attempt(2, 0.5, 1.0, False), attempt(1, 1.0, 0.5, False))
        self.assertFalse(better)


# --- Observed while writing these tests (not one of the eight known defects) -----------------

class ObservedTest(Pinned):
    def test_observed_passive_voice_paraphrase_is_not_a_reversed_relationship(self):
        probe = chunk(901, PROBE_TEXTS[0], document="mission.pdf")
        text = "The Kestrel team built the Orion probe."
        judged = self.judge("Who built the Orion probe?", f"{text[:-1]} [1].", [probe],
                            claim(text, SUPPORTED, probe.chunk_id, BUILT[:-1]))
        self.assert_verdict(judged, SUPPORTED)

    def test_control_observed_genuinely_reversed_relationship_stays_partial(self):
        staff = chunk(902, "Bob reports to Alice.", document="org-chart.pdf")
        judged = self.judge("Who reports to whom?", "Alice reports to Bob [1].", [staff],
                            claim("Alice reports to Bob.", SUPPORTED, staff.chunk_id,
                                  "Bob reports to Alice"))
        self.assert_verdict(judged, PARTIALLY_SUPPORTED)


def _summary(result: unittest.TestResult) -> None:
    """Pass/fail per test, grouped by kind, with the first line of each failure."""
    def name(test):
        # Subtests report as "test_x (Class.test_x) [label]"; group them under their test.
        return test.id().split(" ", 1)[0].rsplit(".", 1)[-1]

    reasons: dict[str, list[str]] = {}
    for test, trace in result.failures + result.errors:
        lines = [line for line in trace.splitlines() if line.strip()]
        reason = next((line.strip() for line in lines if line.startswith(("AssertionError",
                                                                          "AttributeError"))),
                      lines[-1].strip())
        detail = next((line.strip() for line in lines if line.startswith(" : ")), "")
        reason = f"{reason} {detail}".strip()
        label = getattr(test, "_subDescription", lambda: "")()
        reasons.setdefault(name(test), []).append(f"{label} {reason}".strip())

    loaded = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    groups: dict[str, list[str]] = {"defect": [], "control": [], "observed": [], "other": []}

    def walk(suite):
        for item in suite:
            if isinstance(item, unittest.TestSuite):
                walk(item)
            else:
                test = name(item)
                kind = next((k for k in ("defect", "control", "observed")
                             if test.startswith(f"test_{k}")), "other")
                groups[kind].append(test)

    walk(loaded)
    print("\nSummary (defect tests are expected to fail until their fix lands):")
    for kind, tests in groups.items():
        if tests:
            passing = sum(test not in reasons for test in tests)
            print(f"  {kind}: {passing}/{len(tests)} passing")
            for test in tests:
                print(f"    {'FAIL' if test in reasons else 'PASS'}  {test}")
                for reason in reasons.get(test, []):
                    print(f"          {reason[:160]}")


if __name__ == "__main__":
    program = unittest.main(exit=False, verbosity=1)
    _summary(program.result)
    sys.exit(0 if program.result.wasSuccessful() else 1)
