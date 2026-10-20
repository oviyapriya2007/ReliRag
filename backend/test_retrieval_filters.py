"""Offline tests for retrieval ranking, document filtering, duplicate passages, and the evidence
each attempt of Basic and RELI (Attest) mode receives.

Usage (from the project root or backend/):
    python backend/test_retrieval_filters.py

The vector search (`_nearest`) runs SQL that only PostgreSQL with pgvector can execute. These
tests check that SQL's filters and ordering directly, and otherwise replace `_nearest` with a
search over an in-memory SQLite database that applies the same rules: only chunks of selected,
non-deleted documents, ordered by similarity then chunk ID, at most `k`. Documents, questions,
and similarities are synthetic.

Offline: embeddings and every Claude caller are mocked, so no API calls are made and the real
database is never touched. Exits with status 0 when all tests pass, 1 otherwise.
"""

import json
import os
import re
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

# Must be set before `app` is imported so the app never connects to the real database.
os.environ["DATABASE_URL"] = "sqlite://"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Document, DocumentChunk, Query  # noqa: E402
from app.routers.query import GATE_FAILED_MESSAGE, NO_PASSAGES_MESSAGE  # noqa: E402
from app.services import retrieval  # noqa: E402
from app.services.corrector import RETRY_TOP_K, REWRITE  # noqa: E402
from app.services.evaluator import SUPPORTED  # noqa: E402
from app.services.generator import ANSWERED  # noqa: E402
from app.services.llm import LLMResult  # noqa: E402
from app.services.retrieval import MAX_TOP_K, RetrievedChunk, retrieve  # noqa: E402
from app.services.similarity_gate import INSUFFICIENT_EVIDENCE  # noqa: E402

MODEL = "claude-test-model"
QUESTION = "What are the opening hours and the parking rules?"
REWRITTEN = "parking rules for visitors"
# (document key, text). "copy" repeats two chunks of "guide" word for word, as when the same
# file is uploaded twice; "archived" is soft-deleted; "overlap" shares most text with guide-1.
DOCUMENTS = ("guide", "rules", "archived", "copy")
CHUNKS = [
    ("guide", "The centre opens at 9 am on weekdays."),
    ("guide", "Visitors may park in the north lot."),
    ("guide", "Guided tours start every hour."),
    ("rules", "Parking in the north lot is limited to 2 hours."),
    ("rules", "Bicycles must use the east rack."),
    ("archived", "The centre opens at 7 am on weekdays."),
    ("copy", "The centre opens at 9 am on weekdays."),
    ("copy", "Visitors may park in the north lot."),
    ("guide", "The centre opens at 9 am on weekdays and closes at 6 pm."),
]
GUIDE_OPEN, GUIDE_PARK, GUIDE_TOURS, RULES_PARK, RULES_BIKES, ARCHIVED, COPY_OPEN, COPY_PARK, \
    GUIDE_OPEN_LONG = range(len(CHUNKS))
# Similarity of each chunk to each query; identical text has identical similarity.
SIMILARITY = {
    QUESTION: {GUIDE_OPEN: 0.82, COPY_OPEN: 0.82, ARCHIVED: 0.90, GUIDE_PARK: 0.74,
               COPY_PARK: 0.74, RULES_PARK: 0.70, GUIDE_OPEN_LONG: 0.66, GUIDE_TOURS: 0.40,
               RULES_BIKES: 0.35},
    REWRITTEN: {RULES_PARK: 0.88, GUIDE_PARK: 0.80, COPY_PARK: 0.80, RULES_BIKES: 0.45},
    "Unrelated question": {index: 0.10 for index in range(len(CHUNKS))},
}


def llm_result(text: str) -> LLMResult:
    return LLMResult(text=text, model=MODEL, input_tokens=10, output_tokens=10, latency_ms=1,
                     stop_reason="end_turn", attempts=1)


class RetrievalFixture(unittest.TestCase):
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
            documents = {key: Document(filename=f"{key}.pdf", total_pages=9, total_chunks=1)
                         for key in DOCUMENTS}
            documents["archived"].deleted_at = datetime.now(UTC)
            rows = [DocumentChunk(document=documents[key], page_number=i + 1, chunk_index=i,
                                  content=text) for i, (key, text) in enumerate(CHUNKS)]
            db.add_all([*documents.values(), *rows])
            db.commit()
            self.doc = {key: document.id for key, document in documents.items()}
            self.ids = [row.id for row in rows]
        self.index_of = {chunk_id: index for index, chunk_id in enumerate(self.ids)}
        self.searches = []

    def nearest(self, db, query, k, document_ids, *, score_embedding=None):
        """`_nearest` over SQLite with the production filters and ordering."""
        self.searches.append((query, k, None if document_ids is None else list(document_ids)))
        with self.Session() as session:
            stmt = (select(DocumentChunk, Document)
                    .join(Document, Document.id == DocumentChunk.document_id)
                    .where(Document.deleted_at.is_(None)))
            if document_ids is not None:
                stmt = stmt.where(DocumentChunk.document_id.in_(list(document_ids)))
            rows = session.execute(stmt).all()
        table = SIMILARITY[query]
        scored = SIMILARITY[score_embedding or query]
        rows.sort(key=lambda row: (-table.get(self.index_of[row[0].id], 0.0), row[0].id))
        return [(RetrievedChunk(chunk_id=c.id, document_id=d.id, document=d.filename,
                                page=c.page_number, text=c.content,
                                similarity=scored.get(self.index_of[c.id], 0.0)),
                 table.get(self.index_of[c.id], 0.0))
                for c, d in rows[:k]]

    def patched_search(self):
        return (patch.object(retrieval, "_nearest", side_effect=self.nearest),
                patch.object(retrieval, "embed_query", side_effect=lambda text: text),
                patch.object(retrieval, "embed_texts", side_effect=lambda texts: list(texts)))

    def retrieve(self, question=QUESTION, k=4, document_ids=None):
        nearest, embed_query, embed_texts = self.patched_search()
        with nearest, embed_query, embed_texts:
            return retrieve(None, question, k=k, document_ids=document_ids)

    def indexes(self, chunks):
        return [self.index_of[chunk.chunk_id] for chunk in chunks]


class RetrieveTest(RetrievalFixture):
    def test_evidence_from_several_documents_keeps_its_source(self):
        result = self.retrieve(k=4)
        self.assertEqual(self.indexes(result), [GUIDE_OPEN, GUIDE_PARK, RULES_PARK,
                                                GUIDE_OPEN_LONG])
        self.assertEqual({(c.document_id, c.document) for c in result},
                         {(self.doc["guide"], "guide.pdf"), (self.doc["rules"], "rules.pdf")})
        self.assertEqual([c.page for c in result],
                         [GUIDE_OPEN + 1, GUIDE_PARK + 1, RULES_PARK + 1, GUIDE_OPEN_LONG + 1])

    def test_top_k_is_a_prefix_of_one_ranking(self):
        full = self.indexes(self.retrieve(k=6))
        for k in range(1, 7):
            with self.subTest(k=k):
                result = self.retrieve(k=k)
                self.assertEqual(self.indexes(result), full[:k])
                self.assertEqual([c.similarity for c in result],
                                 sorted((c.similarity for c in result), reverse=True))
        for k in (0, MAX_TOP_K + 1):
            with self.subTest(k=k), self.assertRaises(ValueError):
                self.retrieve(k=k)

    def test_document_filter_excludes_other_documents(self):
        result = self.retrieve(k=4, document_ids=[self.doc["rules"]])
        self.assertEqual(self.indexes(result), [RULES_PARK, RULES_BIKES])
        self.assertTrue(all(ids == [self.doc["rules"]] for _, _, ids in self.searches))

    def test_empty_filter_searches_nothing_and_none_searches_everything(self):
        self.assertEqual(self.retrieve(document_ids=[]), [])
        self.assertEqual(self.searches, [])
        everything = self.retrieve(k=MAX_TOP_K, document_ids=None)
        self.assertEqual(len(everything), len(CHUNKS) - 1 - 2)  # no archived, no repeats

    def test_unknown_document_ids_match_nothing_and_are_ignored_beside_valid_ones(self):
        self.assertEqual(self.retrieve(document_ids=[999, -1]), [])
        mixed = self.retrieve(document_ids=[self.doc["rules"], 999])
        self.assertEqual(self.indexes(mixed), [RULES_PARK, RULES_BIKES])

    def test_deleted_documents_are_never_retrieved(self):
        for document_ids in (None, [self.doc["archived"]],
                             [self.doc["archived"], self.doc["guide"]]):
            with self.subTest(document_ids=document_ids):
                result = self.retrieve(k=MAX_TOP_K, document_ids=document_ids)
                self.assertNotIn(ARCHIVED, self.indexes(result))
        self.assertEqual(self.retrieve(document_ids=[self.doc["archived"]]), [])

    def test_repeated_passages_take_one_place_and_the_search_goes_deeper(self):
        # The copy's chunks tie with the originals; the lower chunk ID (the original) is kept.
        result = self.retrieve(k=4, document_ids=[self.doc["guide"], self.doc["copy"]])
        self.assertEqual(self.indexes(result), [GUIDE_OPEN, GUIDE_PARK, GUIDE_OPEN_LONG,
                                                GUIDE_TOURS])
        self.assertEqual(len({c.text for c in result}), 4)
        self.assertEqual([k for _, k, _ in self.searches], [4, 8])
        # Overlapping but different text is kept.
        self.assertIn(GUIDE_OPEN_LONG, self.indexes(result))

    def test_without_repeats_one_search_of_k_is_made(self):
        self.retrieve(k=3, document_ids=[self.doc["guide"], self.doc["rules"]])
        self.assertEqual([k for _, k, _ in self.searches], [3])

    def test_deeper_search_is_bounded(self):
        copies = [RetrievedChunk(chunk_id=i, document_id=1, document="d.pdf", page=1,
                                 text="Same text.", similarity=0.9) for i in range(100)]
        calls = []

        def nearest(db, query, k, document_ids, *, score_embedding=None):
            calls.append(k)
            return [(chunk, 0.9) for chunk in copies[:k]]

        with patch.object(retrieval, "_nearest", side_effect=nearest), \
             patch.object(retrieval, "embed_query", return_value="q"):
            result = retrieve(None, "Single topic", k=5)
        self.assertEqual(([c.chunk_id for c in result], calls),
                         ([0], [5, 10, 20]))
        self.assertEqual(retrieval.DUPLICATE_SEARCH_FACTOR, 4)


class VectorSearchSqlTest(unittest.TestCase):
    def test_sql_filters_and_orders_deterministically(self):
        captured = []

        class FakeSession:
            def execute(self, stmt):
                captured.append(stmt)
                return []

        retrieval._nearest(FakeSession(), [0.0] * 384, 5, [1, 2])
        sql = " ".join(str(captured[0].compile(dialect=postgresql.dialect())).split())
        self.assertIn("document_chunks.embedding IS NOT NULL", sql)
        self.assertIn("documents.deleted_at IS NULL", sql)
        self.assertIn("document_chunks.document_id IN", sql)
        self.assertRegex(sql, r"ORDER BY distance, document_chunks\.id LIMIT")


class PipelineEvidenceTest(RetrievalFixture):
    def setUp(self):
        super().setUp()

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def claim(self, index, text):
        return {"claim_text": f"{text}.", "verdict": SUPPORTED,
                "evidence_chunk_id": self.ids[index], "evidence_quote": text}

    def post(self, *, mode, question=QUESTION, document_ids=None, answers=(), evaluations=None,
             rewrites=()):
        evaluations = evaluations or {}

        def evaluate(prompt, **_):
            answer = re.search(r"<answer>\n(.*?)\n</answer>", prompt, re.DOTALL).group(1)
            return llm_result(evaluations[answer])

        nearest, embed_query, embed_texts = self.patched_search()
        with nearest, embed_query, embed_texts, \
             patch("app.services.generator.call_claude",
                   side_effect=[llm_result(a) for a in answers]) as generator, \
             patch("app.services.evaluator.call_claude", side_effect=evaluate), \
             patch("app.services.corrector.call_claude",
                   side_effect=[llm_result(r) for r in rewrites]):
            response = self.client.post("/query", json={
                "question": question, "mode": mode, "k": 3, "document_ids": document_ids})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(self.client.get(f"/query/{body['query_id']}").json(), body)
        return body, generator

    def logged(self, attempt):
        return [(self.index_of[r["chunk_id"]], r["document_id"], r["filename"])
                for r in attempt["retrieval"]]

    def source(self, index):
        key = CHUNKS[index][0]
        return (index, self.doc[key], f"{key}.pdf")

    def test_basic_and_attest_receive_the_same_filtered_first_attempt_evidence(self):
        answer = "The centre opens at 9 am on weekdays [1]. Visitors may park in the north lot [2]."
        evaluation = json.dumps({
            "claims": [self.claim(GUIDE_OPEN, "The centre opens at 9 am on weekdays"),
                       self.claim(GUIDE_PARK, "Visitors may park in the north lot")],
            "answer_relevance": 1.0, "context_relevance": 1.0, "feedback": "Complete."})
        selected = [self.doc["guide"], self.doc["copy"]]
        bodies = {}
        for mode in ("basic", "reli"):
            body, generator = self.post(mode=mode, document_ids=selected, answers=[answer],
                                        evaluations={answer: evaluation})
            bodies[mode] = body
            prompt = generator.call_args.args[0]
            self.assertIn("(source: guide.pdf, page 1)", prompt)
            self.assertNotIn("copy.pdf", prompt)
            with self.Session() as db:
                self.assertEqual(db.get(Query, body["query_id"]).options["document_ids"], selected)
        self.assertEqual(bodies["basic"]["attempts"][0]["retrieval"],
                         bodies["reli"]["attempts"][0]["retrieval"])
        self.assertEqual(self.logged(bodies["reli"]["attempts"][0]),
                         [self.source(GUIDE_OPEN), self.source(GUIDE_PARK),
                          self.source(GUIDE_OPEN_LONG)])

    def test_correction_retrieval_keeps_the_filter_and_earlier_evidence(self):
        selected = [self.doc["guide"], self.doc["rules"]]
        first = "The centre opens at 9 am on weekdays [1]."
        second = ("The centre opens at 9 am on weekdays [1]. Parking in the north lot is limited "
                  "to 2 hours [2].")
        body, _ = self.post(
            mode="reli", document_ids=selected, answers=[first, second], rewrites=[REWRITTEN],
            evaluations={
                first: json.dumps({
                    "claims": [self.claim(GUIDE_OPEN, "The centre opens at 9 am on weekdays")],
                    "answer_relevance": 0.5, "context_relevance": 0.5,
                    "feedback": "The parking rules are missing."}),
                second: json.dumps({
                    "claims": [self.claim(GUIDE_OPEN, "The centre opens at 9 am on weekdays"),
                               self.claim(RULES_PARK,
                                          "Parking in the north lot is limited to 2 hours")],
                    "answer_relevance": 1.0, "context_relevance": 0.9, "feedback": "Complete."}),
            })

        first_attempt, second_attempt = body["attempts"]
        self.assertEqual(second_attempt["strategy"], REWRITE)
        self.assertEqual(second_attempt["retrieval_query"], REWRITTEN)
        # Every search, including the retry's, is limited to the selected documents.
        self.assertTrue(all(ids == selected for _, _, ids in self.searches))
        self.assertEqual([(query, k) for query, k, _ in self.searches],
                         [(QUESTION, 3), (REWRITTEN, RETRY_TOP_K)])
        # Attempt 1's cited passage is kept, each chunk once; being in both rankings, it is fused
        # to the top. Attempt 1's other passages were judged weak and are not carried over.
        self.assertEqual(self.logged(second_attempt),
                         [self.source(GUIDE_OPEN), self.source(RULES_PARK),
                          self.source(GUIDE_PARK), self.source(RULES_BIKES),
                          self.source(GUIDE_TOURS), self.source(GUIDE_OPEN_LONG)])
        self.assertEqual((body["final_attempt_number"], body["final_answer"]), (2, second))
        self.assertTrue(second_attempt["evaluation"]["passed"])
        self.assertEqual(self.logged(first_attempt)[0], self.source(GUIDE_OPEN))

    def test_no_retrievable_passages_is_reported_as_such(self):
        for document_ids in ([], [999], [self.doc["archived"]]):
            for mode in ("basic", "reli"):
                with self.subTest(document_ids=document_ids, mode=mode):
                    body, generator = self.post(mode=mode, document_ids=document_ids)
                    generator.assert_not_called()
                    self.assertEqual((body["status"], body["final_answer"],
                                      body["attempts"][0]["retrieval"]),
                                     (INSUFFICIENT_EVIDENCE, NO_PASSAGES_MESSAGE, []))

    def test_weak_passages_still_fail_the_similarity_gate(self):
        body, generator = self.post(mode="basic", question="Unrelated question")
        generator.assert_not_called()
        self.assertEqual((body["status"], body["final_answer"]),
                         (INSUFFICIENT_EVIDENCE, GATE_FAILED_MESSAGE))
        self.assertEqual(len(body["attempts"][0]["retrieval"]), 3)
        self.assertNotEqual(body["status"], ANSWERED)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
