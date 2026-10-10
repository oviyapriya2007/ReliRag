"""RELI-RAG A6: question-file loading for calibrate_gate.py.

Usage (from the project root or backend/):
    python backend/test_calibrate_gate.py

Offline: retrieval and the database session are mocked, so no embedding model, database,
or Claude call is used. data/benchmark.json is only read.
Exits with status 0 when all tests pass, 1 otherwise.
"""

import argparse
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

# Must be set before `app` is imported so nothing can connect to the real database.
os.environ["DATABASE_URL"] = "sqlite://"

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

import calibrate_gate  # noqa: E402
from calibrate_gate import COVERED, OUT_OF_SCOPE, load_questions  # noqa: E402
from app.services.retrieval import RetrievedChunk  # noqa: E402

BENCHMARK_PATH = BACKEND_DIR.parent / "data" / "benchmark.json"


def benchmark_entry(category, question="What is TCP?", id_="Q01"):
    return {"id": id_, "category": category, "question": question}


class LoadQuestionsTest(unittest.TestCase):
    def load(self, data, *, bom=False):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "questions.json"
            path.write_text(json.dumps(data), encoding="utf-8-sig" if bom else "utf-8")
            args = argparse.Namespace(questions=str(path), covered=None, out_of_scope=None)
            return load_questions(args)

    def test_simple_format(self):
        questions = self.load({COVERED: ["What is TCP?"], OUT_OF_SCOPE: ["Who won?"]})
        self.assertEqual(questions, {COVERED: ["What is TCP?"], OUT_OF_SCOPE: ["Who won?"]})

    def test_benchmark_format_maps_categories(self):
        data = {"dataset_name": "x", "questions": [
            benchmark_entry("clearly_covered", "covered 1", "Q01"),
            benchmark_entry("multipart_comparison", "covered 2", "Q02"),
            benchmark_entry("ambiguous_tricky", "out 1", "Q03"),
            benchmark_entry("out_of_scope", "out 2", "Q04"),
        ]}
        questions = self.load(data)
        self.assertEqual(questions, {
            COVERED: ["covered 1", "covered 2"],
            OUT_OF_SCOPE: ["out 1", "out 2"],
        })

    def test_utf8_bom_is_accepted_for_both_formats(self):
        simple = self.load({COVERED: ["a"], OUT_OF_SCOPE: ["b"]}, bom=True)
        benchmark = self.load({"questions": [
            benchmark_entry("clearly_covered", "a"), benchmark_entry("out_of_scope", "b"),
        ]}, bom=True)
        self.assertEqual(simple, benchmark)

    def test_real_benchmark_file(self):
        questions = self.load(json.loads(BENCHMARK_PATH.read_text(encoding="utf-8-sig")))
        self.assertEqual(len(questions[COVERED]), 13)
        self.assertEqual(len(questions[OUT_OF_SCOPE]), 7)
        self.assertIn("Is the network secure?", questions[OUT_OF_SCOPE])
        self.assertIn("What do RPO and RTO describe?", questions[COVERED])

    def test_invalid_or_missing_category_is_rejected(self):
        cases = {
            "unknown": benchmark_entry("partially_covered", id_="Q99"),
            "missing": {"id": "Q99", "question": "What is TCP?"},
            "null": benchmark_entry(None, id_="Q99"),
        }
        for name, entry in cases.items():
            with self.subTest(name):
                with self.assertRaisesRegex(ValueError, r"Q99 has invalid or missing category"):
                    self.load({"questions": [benchmark_entry("clearly_covered"), entry]})

    def test_malformed_benchmark_entries_are_rejected(self):
        cases = {
            "missing question": ({"questions": [{"id": "Q05", "category": "out_of_scope"}]},
                                 r"Q05 has a missing or empty 'question'"),
            "blank question": ({"questions": [benchmark_entry("out_of_scope", "  ", "Q05")]},
                               r"Q05 has a missing or empty 'question'"),
            "entry not an object": ({"questions": ["What is TCP?"]}, r"#0 must be an object"),
            "questions not a list": ({"questions": {"Q01": "x"}}, r"'questions' must be a list"),
            "simple not a list": ({COVERED: "What is TCP?", OUT_OF_SCOPE: ["b"]},
                                  r"'covered' must be a list"),
            "top level not an object": ([], r"must contain a JSON object"),
        }
        for name, (data, message) in cases.items():
            with self.subTest(name):
                with self.assertRaisesRegex(ValueError, message):
                    self.load(data)

    def test_one_group_empty_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least one covered and one out-of-scope"):
            self.load({"questions": [benchmark_entry("clearly_covered")]})


class MainTest(unittest.TestCase):
    def test_benchmark_run_is_retrieval_only_and_passes_doc_ids(self):
        def fake_retrieve(_db, question, *, k, document_ids):
            return [RetrievedChunk(1, 8, "benchmark.pdf", 1, "text", 0.5 + len(question) / 1000)]

        session = MagicMock()
        argv = ["calibrate_gate.py", "--questions", str(BENCHMARK_PATH), "--doc-ids", "8"]
        with patch.object(sys, "argv", argv), \
             patch("calibrate_gate.SessionLocal", return_value=session), \
             patch("calibrate_gate.retrieve", side_effect=fake_retrieve) as retrieve, \
             patch("app.services.llm.call_claude") as claude, \
             redirect_stdout(io.StringIO()) as output:
            exit_code = calibrate_gate.main()

        self.assertEqual(exit_code, 0, output.getvalue())
        self.assertEqual(retrieve.call_count, 20)
        for call in retrieve.call_args_list:
            self.assertEqual(call.kwargs, {"k": 1, "document_ids": [8]})
        claude.assert_not_called()
        session.add.assert_not_called()
        session.commit.assert_not_called()
        session.close.assert_called_once()
        self.assertIn("Lowest covered score", output.getvalue())


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
