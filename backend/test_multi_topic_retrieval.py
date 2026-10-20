"""RELI-RAG: offline tests for retrieving questions that list several requirements.

Usage (from the project root or backend/):
    python backend/test_multi_topic_retrieval.py

Offline: the embedding model and the vector search are replaced by a fake similarity table, so no
model, database, or Claude call is used. Exits with status 0 when all tests pass, 1 otherwise.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Must be set before `app` is imported so the app never connects to the real database.
os.environ["DATABASE_URL"] = "sqlite://"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import settings  # noqa: E402
from app.services import retrieval  # noqa: E402
from app.services.retrieval import (  # noqa: E402
    MAX_SUBQUERIES,
    RetrievedChunk,
    combine_requirement_results,
    retrieve,
    split_requirements,
)
from app.services.similarity_gate import passes_gate  # noqa: E402

MULTI = ("According to the report, explain solar panels, wind turbines, and hydroelectric dams. "
         "Describe one drawback of each.")
REQUIREMENTS = ["solar panels", "wind turbines", "hydroelectric dams"]


class SplitRequirementsTest(unittest.TestCase):
    def test_enumerations(self):
        cases = {
            MULTI: REQUIREMENTS,
            "Compare caching, replication and sharding.": ["caching", "replication", "sharding"],
            "Explain caching, replication, or sharding in the design.":
                ["caching", "replication", "sharding in the design"],
            "Describe the inputs, explain the outputs, and list the failure modes.":
                ["the inputs", "the outputs", "the failure modes"],
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(split_requirements(question), expected)

    def test_several_questions_and_lists(self):
        self.assertEqual(split_requirements("What is a lease? How long does a lease last?"),
                         ["a lease", "How long does a lease last"])
        self.assertEqual(split_requirements("Explain:\n- the intake process\n2) the review steps"),
                         ["the intake process", "the review steps"])

    def test_single_requirement_questions_are_not_split(self):
        for question in ("What is the main difference between TCP and UDP?",
                         "Explain caching and replication.",
                         "TCP, which is reliable, uses handshakes.",
                         "How many addresses are in a /27 subnet?",
                         "Summarize the document."):
            with self.subTest(question=question):
                self.assertEqual(split_requirements(question), [])

    def test_lead_ins_and_duplicates_are_dropped_and_count_is_capped(self):
        self.assertEqual(
            split_requirements("Based on the documents, explain alpha, Alpha, and beta."),
            ["alpha", "beta"])
        many = "Explain " + ", ".join(f"topic{i}" for i in range(10)) + ", and topic10."
        self.assertEqual(len(split_requirements(many)), MAX_SUBQUERIES)


def chunk(chunk_id: int, similarity: float, document_id: int = 1) -> RetrievedChunk:
    return RetrievedChunk(chunk_id=chunk_id, document_id=document_id, document="doc.pdf",
                          page=chunk_id, text=f"text {chunk_id}", similarity=similarity)


# Similarity of each chunk to the whole question ("whole") and to each requirement ("r0".."r2").
# Chunks 1-2 cover requirement 0, chunk 3 requirement 1, chunk 6 requirement 2; 4-5 are noise;
# chunk 7 is in another document.
SIMILARITIES = {
    "whole": {1: 0.70, 2: 0.66, 3: 0.55, 4: 0.50, 5: 0.48, 6: 0.40, 7: 0.65},
    "r0": {1: 0.80, 2: 0.78},
    "r1": {3: 0.75},
    "r2": {6: 0.72, 4: 0.20},
}
DOCUMENTS = {chunk_id: (2 if chunk_id == 7 else 1) for chunk_id in range(1, 8)}


class FakeSearch:
    """Stands in for the vector search: `_nearest` over SIMILARITIES; records every call."""

    def __init__(self, table=SIMILARITIES):
        self.table = table
        self.calls = []

    def __call__(self, db, query, k, document_ids, *, score_embedding=None):
        self.calls.append((query, k, document_ids, score_embedding))
        candidates = [cid for cid in DOCUMENTS
                      if document_ids is None or DOCUMENTS[cid] in document_ids]
        ranked = sorted(candidates, key=lambda cid: -self.table[query].get(cid, 0.1))[:k]
        scored = score_embedding or query
        return [(chunk(cid, self.table[scored].get(cid, 0.1), DOCUMENTS[cid]),
                 self.table[query].get(cid, 0.1)) for cid in ranked]


class RetrieveTest(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(settings, "similarity_gate", 0.30)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_retrieve(self, question, k=4, document_ids=(1,), table=SIMILARITIES):
        search = FakeSearch(table)
        with patch.object(retrieval, "_nearest", side_effect=search), \
             patch.object(retrieval, "embed_query", return_value="whole"), \
             patch.object(retrieval, "embed_texts",
                          side_effect=lambda texts: [f"r{i}" for i in range(len(texts))]):
            result = retrieve(None, question, k=k,
                              document_ids=None if document_ids is None else list(document_ids))
        return result, search

    def test_each_requirement_is_represented(self):
        result, search = self.run_retrieve(MULTI)

        self.assertEqual([c.chunk_id for c in result], [1, 2, 3, 6])
        # Without requirement searches the top 4 would be chunks 1-4: requirement 2 missing.
        self.assertEqual(len(search.calls), 1 + len(REQUIREMENTS))

    def test_single_topic_question_is_one_plain_search(self):
        result, search = self.run_retrieve("What is the main difference between TCP and UDP?")

        self.assertEqual([c.chunk_id for c in result], [1, 2, 3, 4])
        self.assertEqual(search.calls, [("whole", 4, [1], None)])

    def test_document_filter_applies_to_every_search(self):
        result, search = self.run_retrieve(MULTI, document_ids=(1,))
        self.assertNotIn(7, [c.chunk_id for c in result])
        self.assertTrue(all(call[2] == [1] for call in search.calls))

        _, unfiltered = self.run_retrieve(MULTI, document_ids=None)
        self.assertTrue(all(call[2] is None for call in unfiltered.calls))
        nothing, no_search = self.run_retrieve(MULTI, document_ids=())
        self.assertEqual((nothing, no_search.calls), ([], []))

    def test_similarities_are_against_the_whole_question(self):
        result, search = self.run_retrieve(MULTI)

        self.assertEqual([c.similarity for c in result], [0.70, 0.66, 0.55, 0.40])
        self.assertTrue(all(call[3] == "whole" for call in search.calls[1:]))

    def test_weak_requirement_matches_are_not_used(self):
        table = {**SIMILARITIES, "r2": {6: 0.25, 4: 0.20}}
        result, _ = self.run_retrieve(MULTI, table=table)
        self.assertNotIn(6, [c.chunk_id for c in result])

    def test_requirement_matches_cannot_open_the_gate(self):
        # Every chunk is weak for the whole question, but strong for one requirement.
        weak = {"whole": {cid: 0.25 - 0.01 * cid for cid in DOCUMENTS},
                "r0": {1: 0.95}, "r1": {3: 0.95}, "r2": {6: 0.95}}
        result, _ = self.run_retrieve(MULTI, table=weak)
        plain, _ = self.run_retrieve("A single topic question", table=weak)

        self.assertEqual(result[0].chunk_id, plain[0].chunk_id)
        self.assertEqual(passes_gate(result, 0.30), passes_gate(plain, 0.30))
        self.assertFalse(passes_gate(result, 0.30))


class CombineRequirementResultsTest(unittest.TestCase):
    def test_duplicates_are_removed(self):
        whole = [chunk(1, 0.7), chunk(2, 0.6)]
        per_requirement = [[(chunk(1, 0.7), 0.9), (chunk(3, 0.5), 0.8)],
                           [(chunk(3, 0.5), 0.9), (chunk(1, 0.7), 0.4)]]
        result = combine_requirement_results(whole, per_requirement, k=5, min_similarity=0.3)

        self.assertEqual([c.chunk_id for c in result], [1, 2, 3])

    def test_best_whole_question_chunk_is_always_first_and_kept(self):
        whole = [chunk(1, 0.6), chunk(2, 0.5)]
        # Chunk 3 tops two requirements, so it outranks chunk 1 in the fusion.
        per_requirement = [[(chunk(3, 0.4), 0.9)], [(chunk(3, 0.4), 0.9)]]
        for k in (1, 2, 3):
            with self.subTest(k=k):
                result = combine_requirement_results(whole, per_requirement, k=k,
                                                     min_similarity=0.3)
                self.assertEqual(result[0].chunk_id, 1)
                self.assertEqual(len(result), k)
        self.assertEqual(combine_requirement_results([], per_requirement, 3, 0.3), [])


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
