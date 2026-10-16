"""Cost benchmarks: local statistics, category inference and the optional BigQuery path."""

import unittest
import warnings
from unittest import mock

from omniclaim import benchmarks

warnings.filterwarnings("ignore", category=FutureWarning)  # google-api-core Python-version notice


class FakeJob:
    def __init__(self, row):
        self.row = row

    def result(self, timeout=None):
        return iter([self.row])


class FakeClient:
    """Stands in for bigquery.Client; records the SQL and the real QueryJobConfig."""

    last = None

    def __init__(self, project=None):
        self.project = project
        self.queries = []
        FakeClient.last = self

    def query(self, sql, job_config=None):
        self.queries.append((sql, job_config))
        return FakeJob({"n": 200, "q": [float(v) for v in range(0, 1010, 10)], "below": 150})


class LocalBenchmarkTest(unittest.TestCase):
    def test_local_statistics(self):
        stats = benchmarks.compute("auto_glass", 780.0)
        self.assertEqual(stats["source"], "local-dataset")
        self.assertEqual(stats["sampleSize"], 1600)
        self.assertLess(stats["median"], stats["p75"])
        self.assertLess(stats["p75"], stats["p95"])
        self.assertTrue(0 <= stats["claimPercentile"] <= 100)

    def test_category_inference(self):
        cases = [
            ("home", "Water damage: burst supply pipe", "home_water"),
            ("home", "Kitchen fire", "home_other"),
            ("auto", "Storm damage: windshield shattered by a falling branch", "auto_glass"),
            ("auto", "Hail damage: cracked windshield", "auto_glass"),
            ("auto", "Rollover on a rural road", "auto_major"),
            ("auto", "Collision: scrape against a parking garage pillar", "auto_collision"),
        ]
        for product, loss, expected in cases:
            self.assertEqual(benchmarks.infer_category(product, loss), expected, loss)


class BigQueryPathTest(unittest.TestCase):
    def tearDown(self):
        benchmarks._bq_status.update(state="not_configured", detail="", lastQueryMs=None)

    def test_query_parameters_and_parsing(self):
        with mock.patch.object(benchmarks, "BIGQUERY_BENCHMARK_TABLE", "demo-proj.claims.history"), \
                mock.patch("google.cloud.bigquery.Client", FakeClient):
            stats = benchmarks.compute("auto_glass", 780.0)
            state = benchmarks.status()["state"]
        self.assertEqual(stats["source"], "bigquery")
        self.assertEqual(stats["sampleSize"], 200)
        self.assertEqual((stats["median"], stats["p75"], stats["p95"]), (500.0, 750.0, 950.0))
        self.assertEqual(stats["claimPercentile"], 75.0)
        self.assertEqual(state, "active")
        sql, config = FakeClient.last.queries[-1]
        self.assertEqual(FakeClient.last.project, "demo-proj")
        self.assertIn("FROM `demo-proj.claims.history`", sql)
        self.assertIn("@category", sql)
        params = {p.name: p.value for p in config.query_parameters}
        self.assertEqual(params, {"category": "auto_glass", "amount": 780.0})

    def test_errors_fall_back_to_local_data(self):
        def failing_client(*args, **kwargs):
            raise RuntimeError("403 Access Denied")

        with mock.patch.object(benchmarks, "BIGQUERY_BENCHMARK_TABLE", "demo-proj.claims.history"), \
                mock.patch("google.cloud.bigquery.Client", failing_client):
            stats = benchmarks.compute("auto_glass", 780.0)
            status = benchmarks.status()
        self.assertEqual(stats["source"], "local-dataset")
        self.assertEqual(status["state"], "error")
        self.assertIn("Access Denied", status["detail"])

    def test_unsafe_table_name_is_refused(self):
        with mock.patch.object(benchmarks, "BIGQUERY_BENCHMARK_TABLE", "p.d.t` WHERE 1=1; --"), \
                mock.patch("google.cloud.bigquery.Client", FakeClient):
            stats = benchmarks.compute("auto_glass", 780.0)
        self.assertEqual(stats["source"], "local-dataset")


if __name__ == "__main__":
    unittest.main()
