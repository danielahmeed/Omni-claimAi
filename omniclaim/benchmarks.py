"""Cost benchmarks: how does this claim compare with similar past claims?

The benchmark runs against `data/benchmarks/historical_claims.csv`, a synthetic
dataset of 10,000 past claims (see tools/generate_benchmark_data.py). If
BIGQUERY_BENCHMARK_TABLE is set, the same statistics are computed by a
BigQuery query over that table instead; any BigQuery error falls back to the
local file and is reported on the status page.
"""

import bisect
import csv
import re
import threading
import time
from functools import lru_cache

from .config import BENCHMARK_CSV, BIGQUERY_BENCHMARK_TABLE

CATEGORY_LABELS = {
    "auto_glass": "Auto glass claims",
    "auto_collision": "Auto collision repairs",
    "auto_major": "Major auto losses (total loss, rollover, fire, theft)",
    "home_water": "Home water-damage claims",
    "home_other": "Other home claims",
}

_GLASS = re.compile(r"\b(glass|windshield|windscreen|window)\b", re.I)
_MAJOR = re.compile(r"\b(total loss|rollover|roll-over|fire|theft|stolen|flood(ed)?)\b", re.I)
_WATER = re.compile(r"\b(water|pipe|leak|burst|plumbing|flood)\b", re.I)
_TABLE = re.compile(r"^[A-Za-z0-9_\-]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$")

_status_lock = threading.Lock()
_bq_status = {"state": "not_configured" if not BIGQUERY_BENCHMARK_TABLE else "configured",
              "detail": "", "lastQueryMs": None}


def infer_category(product: str, loss_type: str, description: str = "") -> str:
    text = f"{loss_type} {description}"
    if product == "home":
        return "home_water" if _WATER.search(text) else "home_other"
    if _GLASS.search(loss_type) or (_GLASS.search(text) and not _MAJOR.search(text)):
        return "auto_glass"
    if _MAJOR.search(loss_type):
        return "auto_major"
    return "auto_collision"


@lru_cache(maxsize=1)
def _local_amounts() -> dict[str, list[float]]:
    amounts: dict[str, list[float]] = {}
    with BENCHMARK_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            amounts.setdefault(row["loss_category"], []).append(float(row["claim_amount"]))
    for values in amounts.values():
        values.sort()
    return amounts


def _quantile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolated quantile, q in [0, 1]."""
    if not sorted_values:
        return 0.0
    pos = (len(sorted_values) - 1) * q
    low = int(pos)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (pos - low)


def _local_stats(category: str, amount: float) -> dict:
    values = _local_amounts().get(category) or []
    n = len(values)
    below = bisect.bisect_right(values, amount)
    return {
        "sampleSize": n,
        "median": round(_quantile(values, 0.5), 2),
        "p75": round(_quantile(values, 0.75), 2),
        "p95": round(_quantile(values, 0.95), 2),
        "claimPercentile": round(100.0 * below / n, 1) if n else None,
        "source": "local-dataset",
        "dataset": f"Synthetic claims history ({sum(len(v) for v in _local_amounts().values()):,} rows, data/benchmarks/historical_claims.csv)",
    }


def _bigquery_stats(category: str, amount: float) -> dict:
    from google.cloud import bigquery  # Imported lazily: optional dependency.

    if not _TABLE.match(BIGQUERY_BENCHMARK_TABLE):
        raise ValueError("BIGQUERY_BENCHMARK_TABLE must look like project.dataset.table")
    client = bigquery.Client(project=BIGQUERY_BENCHMARK_TABLE.split(".")[0])
    sql = (
        "SELECT COUNT(*) AS n, APPROX_QUANTILES(claim_amount, 100) AS q, "
        "COUNTIF(claim_amount <= @amount) AS below "
        f"FROM `{BIGQUERY_BENCHMARK_TABLE}` WHERE loss_category = @category"
    )
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("category", "STRING", category),
        bigquery.ScalarQueryParameter("amount", "FLOAT64", float(amount)),
    ])
    row = next(iter(client.query(sql, job_config=job_config).result(timeout=30)))
    n = int(row["n"] or 0)
    q = list(row["q"] or [])
    if n == 0 or len(q) < 96:
        raise ValueError(f"No rows for category '{category}' in {BIGQUERY_BENCHMARK_TABLE}")
    return {
        "sampleSize": n,
        "median": round(float(q[50]), 2),
        "p75": round(float(q[75]), 2),
        "p95": round(float(q[95]), 2),
        "claimPercentile": round(100.0 * int(row["below"]) / n, 1),
        "source": "bigquery",
        "dataset": f"BigQuery table {BIGQUERY_BENCHMARK_TABLE}",
    }


def compute(category: str, amount: float) -> dict:
    stats = None
    if BIGQUERY_BENCHMARK_TABLE:
        started = time.perf_counter()
        try:
            stats = _bigquery_stats(category, amount)
            with _status_lock:
                _bq_status.update(state="active", detail="Last query succeeded",
                                  lastQueryMs=round((time.perf_counter() - started) * 1000))
        except Exception as exc:  # Fall back to the local copy of the data.
            with _status_lock:
                _bq_status.update(state="error", detail=f"{type(exc).__name__}: {exc}"[:300])
    if stats is None:
        stats = _local_stats(category, amount)
    stats["category"] = category
    stats["categoryLabel"] = CATEGORY_LABELS.get(category, category)
    return stats


def status() -> dict:
    with _status_lock:
        info = dict(_bq_status)
    if not BIGQUERY_BENCHMARK_TABLE:
        info["detail"] = "Using the local synthetic dataset. Set BIGQUERY_BENCHMARK_TABLE to query BigQuery."
    return info
