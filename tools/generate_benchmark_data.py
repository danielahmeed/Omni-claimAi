#!/usr/bin/env python3
"""Generate the synthetic historical-claims dataset used for cost benchmarks.

The dataset is synthetic: amounts are drawn from log-normal distributions per
loss category with a fixed random seed, so every run produces the same file.
It stands in for an insurer's real claims history. The same CSV can be loaded
into BigQuery (see docs/DEPLOYMENT.md) so the benchmark query runs there.

Usage:
    python tools/generate_benchmark_data.py
"""

import csv
import math
import random
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent.parent / "data" / "benchmarks" / "historical_claims.csv"
SEED = 20260916

# Per-category shape of the claim-amount distribution (log-normal).
CATEGORIES = {
    "auto_glass": {"n": 1600, "median": 640.0, "sigma": 0.38},
    "auto_collision": {"n": 4400, "median": 2850.0, "sigma": 0.72},
    "auto_major": {"n": 700, "median": 14500.0, "sigma": 0.55},
    "home_water": {"n": 2500, "median": 4300.0, "sigma": 0.78},
    "home_other": {"n": 800, "median": 3600.0, "sigma": 0.95},
}
STATES = ["CA", "WA", "TX", "FL", "CO", "NY", "IL", "GA"]
FRAUD_RATE = 0.025


def generate(rng: random.Random):
    rows = []
    serial = 100000
    for category, shape in CATEGORIES.items():
        for _ in range(shape["n"]):
            serial += 1
            amount = shape["median"] * math.exp(shape["sigma"] * rng.gauss(0.0, 1.0))
            amount = round(max(50.0, amount), 2)
            fraud = rng.random() < FRAUD_RATE
            approved = 0.0 if fraud else round(amount * rng.uniform(0.72, 1.0), 2)
            rows.append({
                "claim_id": f"HIST-{serial}",
                "loss_category": category,
                "state": rng.choice(STATES),
                "claim_year": rng.choice([2022, 2023, 2024, 2025]),
                "claim_amount": f"{amount:.2f}",
                "approved_amount": f"{approved:.2f}",
                "days_to_settle": max(1, int(rng.gammavariate(2.0, 5.5))),
                "confirmed_fraud": "true" if fraud else "false",
            })
    rng.shuffle(rows)
    return rows


def main():
    rows = generate(random.Random(SEED))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} synthetic claims to {OUTPUT}")


if __name__ == "__main__":
    main()
