"""Sample policy wording and policy register (data/policies.json)."""

import json
from datetime import date
from functools import lru_cache

from .config import POLICIES_FILE

PRODUCTS = ("auto", "home")
DEFAULT_DEDUCTIBLE = 500.0


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(POLICIES_FILE.read_text(encoding="utf-8"))


def form_for(product: str) -> dict:
    forms = _data()["forms"]
    return forms.get(product) or forms["auto"]


def clause(product: str, clause_id: str) -> dict | None:
    return next((c for c in form_for(product)["clauses"] if c["id"] == clause_id), None)


def lookup(policy_number: str) -> dict | None:
    number = (policy_number or "").strip().upper()
    return next((p for p in _data()["policies"] if p["policyNumber"] == number), None)


def default_deductible(policy: dict | None, category: str) -> float:
    """Pick the deductible from the register for the coverage that applies."""
    if not policy:
        return DEFAULT_DEDUCTIBLE
    deductibles = policy.get("deductibles", {})
    if category == "auto_glass":
        key = "glass"
    elif category.startswith("home"):
        key = "allPerils"
    else:
        key = "collision"
    value = deductibles.get(key) or deductibles.get("collision") or deductibles.get("allPerils")
    return float(value) if value is not None else DEFAULT_DEDUCTIBLE


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
