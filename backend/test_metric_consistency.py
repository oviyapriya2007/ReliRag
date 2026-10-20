"""Offline tests: analytics, the benchmark summary, and the evaluations CSV agree on latency,
pass rates, correction counts, and claim counts for the same stored records.

Usage (from the project root or backend/):
    python backend/test_metric_consistency.py

The records are synthetic rows written straight to an in-memory SQLite database; the benchmark
rows are built from the API's own /query responses for those records. No Claude call is made
and the real database is never touched. Exits with status 0 when all tests pass, 1 otherwise.
"""

import csv
import io
import os
import sys
import unittest
from pathlib import Path

# Must be set before `app` is imported so the app never connects to the real database.
os.environ["DATABASE_URL"] = "sqlite://"

BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND.parent / "scripts"))

import run_benchmark as rb  # noqa: E402
import test_analytics as fixtures  # noqa: E402
from app.services.corrector import REWRITE  # noqa: E402
from app.services.evaluator import (  # noqa: E402
    EVALUATOR_ERROR,
    MISSING_INFO,
    SUPPORTED,
    UNSUPPORTED,
    UNSUPPORTED_CLAIM,
)
from app.services.generator import ANSWERED  # noqa: E402
from app.services.similarity_gate import INSUFFICIENT_EVIDENCE  # noqa: E402

attempt, evaluation = fixtures.attempt, fixtures.evaluation


class MetricConsistencyTest(unittest.TestCase):
    setUp = fixtures.AnalyticsTest.setUp
    add_query = fixtures.AnalyticsTest.add_query
    summary = fixtures.AnalyticsTest.summary

    def seed(self):
        """Stored outcomes; returns the query IDs in insertion order."""
        # B1. Basic, passed; an older, superseded evaluation must be ignored. Several logged
        # chunks must not multiply its claim count.
        self.add_query("basic", ANSWERED, [attempt(latency=100, chunks=[0, 1, 2], evaluations=[
            evaluation((0.2, 0.2, 0.2), passed=False, failure_type=UNSUPPORTED_CLAIM,
                       latency=999, claims=[UNSUPPORTED, UNSUPPORTED, UNSUPPORTED]),
            evaluation((0.9, 0.9, 0.9), latency=40, claims=[SUPPORTED, UNSUPPORTED]),
        ])])
        # B2. Basic, evaluator_error: time was spent, but there are no scores.
        self.add_query("basic", ANSWERED, [attempt(latency=80, evaluations=[
            evaluation(passed=False, failure_type=EVALUATOR_ERROR, latency=30)])])
        # B3. Basic, rejected by the similarity gate: no Claude call, no timing.
        self.add_query("basic", INSUFFICIENT_EVIDENCE,
                       [attempt(INSUFFICIENT_EVIDENCE, chunks=[0])])
        # R1. RELI, attempt 1 passes.
        self.add_query("reli", ANSWERED, [attempt(latency=120, chunks=[0], evaluations=[
            evaluation((1.0, 0.9, 0.9), latency=50, claims=[SUPPORTED])])], final_attempt=1)
        # R2. RELI, correction selected and passing; one claim has no verdict.
        self.add_query("reli", ANSWERED, [
            attempt(latency=100, chunks=[0], evaluations=[evaluation(
                (1.0, 0.5, 0.9), passed=False, failure_type=MISSING_INFO, latency=40,
                claims=[UNSUPPORTED])]),
            attempt(latency=110, strategy=REWRITE, chunks=[0, 1], evaluations=[
                evaluation((1.0, 0.95, 0.9), latency=45, claims=[SUPPORTED, None])]),
        ], final_attempt=2)
        # R3. RELI, attempt 2 passes but is not selected (much less faithful): attempt 1 kept.
        self.add_query("reli", ANSWERED, [
            attempt(latency=90, chunks=[1], evaluations=[evaluation(
                (1.0, 0.6, 0.9), passed=False, failure_type=MISSING_INFO, latency=30)]),
            attempt(latency=95, strategy=REWRITE, chunks=[1], evaluations=[
                evaluation((0.8, 0.9, 0.9), latency=35)]),
        ], final_attempt=1)
        # R4. RELI, Claude refused: generation time, no evaluation.
        self.add_query("reli", INSUFFICIENT_EVIDENCE,
                       [attempt(INSUFFICIENT_EVIDENCE, latency=60, chunks=[2])], final_attempt=1)
        return list(range(1, 8))

    def benchmark_rows(self, ids):
        """Benchmark rows built from the API's /query responses, Basic and RELI paired."""
        def body(query_id):
            response = self.client.get(f"/query/{query_id}")
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        basic, reli = [body(i) for i in ids[:3]], [body(i) for i in ids[3:]]
        pairs = [(basic[i] if i < len(basic) else None, reli[i]) for i in range(len(reli))]
        return [rb.build_row(rb.BenchmarkQuestion(id=f"S{n}", question="synthetic"), "run",
                             http_status=200, body={"compare_id": "c", "basic": b, "reli": r},
                             error=None, elapsed_ms=1)
                for n, (b, r) in enumerate(pairs, start=1)]

    def test_latency_parts_add_up_and_match_the_benchmark(self):
        ids = self.seed()
        by_mode = self.summary()["by_mode"]

        # Basic: B1 100 + 40, B2 80 + 30; B3 made no Claude call and is not counted.
        self.assertEqual(by_mode["basic"]["latency"], {
            "queries": 2, "avg_generation_ms": 90.0, "avg_evaluation_ms": 35.0,
            "avg_total_ms": 125.0})
        # RELI generation 120, 210, 185, 60; evaluation 50, 85, 65, and 0 for the refusal.
        self.assertEqual(by_mode["reli"]["latency"], {
            "queries": 4, "avg_generation_ms": 143.75, "avg_evaluation_ms": 50.0,
            "avg_total_ms": 193.75})
        for mode in ("basic", "reli"):
            latency = by_mode[mode]["latency"]
            self.assertAlmostEqual(latency["avg_generation_ms"] + latency["avg_evaluation_ms"],
                                   latency["avg_total_ms"])

        summary = rb.summarize(self.benchmark_rows(ids))
        self.assertEqual((summary["basic_avg_latency_ms"], summary["reli_avg_latency_ms"]),
                         (125.0, 193.75))

    def test_pass_rates_and_corrections_agree_with_the_benchmark(self):
        ids = self.seed()
        body = self.summary()
        basic, reli = body["by_mode"]["basic"], body["by_mode"]["reli"]

        # evaluator_error (B2) and unevaluated queries (B3, R4) are outside every denominator.
        self.assertEqual(basic["first_pass"], {"count": 1, "total": 1, "rate": 1.0})
        self.assertEqual(basic["final_pass"], {"count": 1, "total": 1, "rate": 1.0})
        self.assertEqual(reli["first_pass"], {"count": 1, "total": 3, "rate": 1 / 3})
        # R3's passing attempt 2 was not selected, so only R1 and R2's final answers pass.
        self.assertEqual(reli["final_pass"], {"count": 2, "total": 3, "rate": 2 / 3})
        self.assertEqual(body["corrections"], {
            "eligible": 2, "triggered": 2, "successful": 1, "failed_after_correction": 1,
            "trigger_rate": 1.0, "success_rate": 0.5})
        self.assertEqual((body["insufficient_evidence"], basic["insufficient_evidence"],
                          reli["insufficient_evidence"]), (2, 1, 1))

        summary = rb.summarize(self.benchmark_rows(ids))
        for mode, metric in (("basic", basic), ("reli", reli)):
            self.assertEqual((summary[f"{mode}_passed"], summary[f"{mode}_evaluated"]),
                             (metric["final_pass"]["count"], metric["final_pass"]["total"]))
        self.assertEqual((summary["basic_evaluator_errors"], summary["reli_evaluator_errors"]),
                         (1, 0))
        self.assertEqual((summary["corrections_triggered"], summary["corrections_successful"]),
                         (body["corrections"]["triggered"], body["corrections"]["successful"]))
        self.assertIn("1 evaluator error(s) not counted", rb.format_summary(summary, "run"))

    def test_claims_are_counted_once_per_latest_evaluation(self):
        self.seed()
        body = self.summary()

        # B1's latest evaluation has 1 unsupported claim (the superseded one's 3 are ignored);
        # R2's attempt 1 has 1. A claim without a verdict is neither supported nor unsupported.
        self.assertEqual((body["unsupported_claims"], body["by_mode"]["basic"]["unsupported_claims"],
                          body["by_mode"]["reli"]["unsupported_claims"]), (2, 1, 1))
        self.assertEqual(body["by_mode"]["reli"]["partially_supported_claims"], 0)

        response = self.client.get("/evaluations/export.csv")
        self.assertEqual(response.status_code, 200, response.text)
        rows = list(csv.DictReader(io.StringIO(response.text)))
        self.assertEqual(sum(int(row["unsupported_claims"]) for row in rows),
                         body["unsupported_claims"])
        self.assertTrue(all(row["is_latest"] == "true" for row in rows))
        self.assertEqual([row["status"] for row in rows].count("evaluator_error"), 1)

    def test_stored_verdicts_are_not_rescored(self):
        # Verdicts recorded under an earlier threshold keep their stored result.
        self.add_query("basic", ANSWERED, [attempt(latency=10, evaluations=[
            evaluation((0.75, 0.75, 0.75), passed=False, failure_type=UNSUPPORTED_CLAIM,
                       latency=5)])])
        self.add_query("basic", ANSWERED, [attempt(latency=10, evaluations=[
            evaluation((0.65, 0.9, 0.9), latency=5)])])
        basic = self.summary()["by_mode"]["basic"]
        self.assertEqual(basic["first_pass"], {"count": 1, "total": 2, "rate": 0.5})
        self.assertEqual(basic["final_pass"], basic["first_pass"])


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2).result
    sys.exit(0 if result.wasSuccessful() else 1)
