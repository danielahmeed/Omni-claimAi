"""Turn an assessment into a decision: line items, routing, settlement, letter.

Everything with money or routing is computed here in plain code, never by the
model, so the numbers on screen always add up and the rules can be audited:

* risk 0-19 + covered + every line supported + no review findings -> auto-approve
* risk 80-100, or a photo/document reused from another claim       -> SIU referral
* everything else                                                  -> adjuster review
* payment = approved amount - deductible (never negative); nothing is paid
  while a claim is with SIU or denied.
"""

from datetime import datetime, timezone

from .config import AUTO_APPROVE_MAX_RISK, SIU_MIN_RISK
from .schemas import ClaimAssessment

DECISIONS = {
    "APPROVE_RECOMMENDED": "Approved the recommended amount",
    "APPROVE_FULL": "Approved the full claimed amount",
    "REFER_SIU": "Referred to the Special Investigations Unit",
    "DENY": "Denied the claim",
}
STATUS_LABELS = {
    "AUTO_APPROVED": "Auto-approved",
    "ADJUSTER_REVIEW": "Adjuster review",
    "SIU_ESCALATED": "SIU referral",
    "APPROVED": "Approved",
    "DENIED": "Denied",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def risk_level(score: int) -> str:
    if score < 20:
        return "LOW"
    if score < 50:
        return "MODERATE"
    if score < 80:
        return "HIGH"
    return "CRITICAL"


def _money(value) -> float:
    try:
        return round(max(0.0, float(value)), 2)
    except (TypeError, ValueError):
        return 0.0


def normalize_line_items(assessment: ClaimAssessment) -> list[dict]:
    items = []
    for item in assessment.line_items:
        billed = _money(item.billed_amount)
        if item.recommendation == "ALLOW":
            allowed = billed
        elif item.recommendation == "REDUCE":
            allowed = min(_money(item.allowed_amount), billed)
        else:  # DISALLOW, or REVIEW (held for the adjuster)
            allowed = 0.0
        items.append({
            "description": item.description.strip()[:300],
            "billedAmount": billed,
            "photoEvidence": item.photo_evidence,
            "recommendation": item.recommendation,
            "allowedAmount": allowed,
            "reason": item.reason.strip()[:500],
        })
    return items


def _clean_box(box: list[int]) -> list[int] | None:
    if len(box) != 4:
        return None
    ymin, xmin, ymax, xmax = (max(0, min(1000, int(v))) for v in box)
    if ymax - ymin < 5 or xmax - xmin < 5:
        return None
    return [ymin, xmin, ymax, xmax]


def damage_regions(assessment: ClaimAssessment) -> list[dict]:
    regions = []
    for region in assessment.damage_regions[:12]:
        box = _clean_box(region.box_2d)
        if box:
            regions.append({"label": region.label.strip()[:80], "severity": region.severity, "box": box})
    return regions


def compute_settlement(claim: dict) -> dict:
    claimed = _money(claim["claimedAmount"])
    deductible = _money(claim["deductible"])
    items = claim.get("lineItems") or []
    coverage = claim["coverage"]["decision"]
    if items:
        recommended = sum(i["allowedAmount"] for i in items if i["recommendation"] in ("ALLOW", "REDUCE"))
        held = sum(i["billedAmount"] for i in items if i["recommendation"] == "REVIEW")
    else:
        recommended, held = claimed, 0.0
    if coverage == "NOT_COVERED":
        recommended, held = 0.0, 0.0
    recommended = round(min(recommended, claimed), 2)
    held = round(min(held, max(0.0, claimed - recommended)), 2)
    disallowed = round(max(0.0, claimed - recommended - held), 2)

    decision = claim.get("decision") or {}
    status = claim["status"]
    approved = decision.get("approvedAmount")
    if approved is None and status == "AUTO_APPROVED":
        approved = recommended
    if status in ("SIU_ESCALATED", "DENIED"):
        net, basis = 0.0, ("on-hold" if status == "SIU_ESCALATED" else "denied")
    elif approved is not None:
        net, basis = round(max(0.0, approved - deductible), 2), "approved"
    else:
        net, basis = round(max(0.0, recommended - deductible), 2), "recommended"
    return {"claimed": claimed, "recommended": recommended, "held": held, "disallowed": disallowed,
            "deductible": deductible, "approved": approved, "net": net, "basis": basis}


def route(claim: dict) -> tuple[str, str, str]:
    """Return (status, recommendedAction, reason) for an undecided claim."""
    risk = claim["riskScore"]
    findings = claim.get("findings") or []
    items = claim.get("lineItems") or []
    coverage = claim["coverage"]["decision"]
    reused = bool((claim.get("photo") or {}).get("matches")) or bool((claim.get("document") or {}).get("matches"))
    if reused:
        return "SIU_ESCALATED", "SIU_REFERRAL", "The photo or document was already used in another claim."
    if risk >= SIU_MIN_RISK:
        return "SIU_ESCALATED", "SIU_REFERRAL", f"Risk score {risk} is {SIU_MIN_RISK} or higher."
    if coverage == "NOT_COVERED":
        return "ADJUSTER_REVIEW", "DENY", "A policy exclusion applies, so an adjuster must confirm the denial."

    blockers = []
    if risk > AUTO_APPROVE_MAX_RISK:
        blockers.append(f"the risk score ({risk}) is above {AUTO_APPROVE_MAX_RISK}")
    if coverage != "COVERED":
        blockers.append("coverage needs confirmation")
    if any(f["severity"] in ("CRITICAL", "MEDIUM") for f in findings):
        blockers.append("some findings need review")
    if not claim.get("photo") and not claim.get("illustration"):
        blockers.append("there is no damage photo")
    if not items:
        blockers.append("there is no itemized bill")
    elif any(i["recommendation"] != "ALLOW" for i in items):
        blockers.append("some billed lines were reduced, disallowed or held")
    if claim["analysis"]["engine"] == "demo-generic":
        blockers.append("the photo and document were not analyzed because Gemini is not configured")
    if claim["analysis"].get("notice"):
        blockers.append("the Gemini assessment failed, so a live AI result is missing")
    if not blockers:
        return "AUTO_APPROVED", "AUTO_APPROVE", "Low risk, coverage confirmed and every billed line is supported by the evidence."

    settlement = compute_settlement({**claim, "status": "ADJUSTER_REVIEW"})
    action = "APPROVE_ADJUSTED" if items and settlement["recommended"] < settlement["claimed"] else "REVIEW"
    return "ADJUSTER_REVIEW", action, "Sent to an adjuster because " + "; ".join(blockers) + "."


def _fmt(value: float) -> str:
    return f"${value:,.2f}"


def build_letter(claim: dict) -> str:
    s = claim["settlement"]
    status = claim["status"]
    explanation = (claim.get("explanation") or "").strip()
    first_line = f"Dear {claim['claimantName']},\n\nRe: claim {claim['id']} ({claim['lossType']})\n\n"
    closing = "\n\nSincerely,\nClaims Team, Apex Mutual Insurance"

    if status in ("AUTO_APPROVED", "APPROVED"):
        body = (f"{explanation}\n\nSettlement summary\n"
                f"- Amount claimed: {_fmt(s['claimed'])}\n"
                f"- Amount approved: {_fmt(s['approved'] or 0)}\n"
                f"- Deductible: {_fmt(s['deductible'])}\n"
                f"- Payment: {_fmt(s['net'])}\n\n"
                "Payment will be sent to the account on file. If you have questions, reply to this message and a "
                "claims specialist will help.")
    elif status == "SIU_ESCALATED":
        body = ("Your claim needs additional review before we can make a decision. A claims specialist may contact you "
                "to request more information or to inspect the vehicle or property. This does not mean a decision has "
                "been made, and we will keep you updated.")
    elif status == "DENIED":
        exclusion = next((c for c in claim["coverage"]["clauses"] if c["verdict"] == "EXCLUSION_TRIGGERED"), None)
        reason = f" because {exclusion['title'].lower()} ({exclusion['clauseId']}) applies" if exclusion else ""
        body = (f"{explanation}\n\nAfter review we are unable to pay this claim{reason}. If you disagree, reply to this "
                "message with any additional information and we will reconsider.")
    elif claim.get("recommendedAction") == "DENY":
        body = (f"{explanation}\n\nBased on the information received, this loss does not appear to be covered by your "
                "policy. A claims adjuster will confirm the decision and contact you. If any information is incorrect, "
                "please let us know.")
    else:
        body = (f"{explanation}\n\nYour claim is with a claims adjuster for a final decision. Based on the documents "
                "received so far:\n"
                f"- Amount claimed: {_fmt(s['claimed'])}\n"
                f"- Amount we expect to approve: {_fmt(s['recommended'])}\n"
                f"- Deductible: {_fmt(s['deductible'])}\n"
                f"- Expected payment: {_fmt(s['net'])}\n\n"
                "We will contact you if we need anything else.")
    return first_line + body.strip() + closing


def finalize(claim: dict) -> dict:
    """Recompute routing (for undecided claims), settlement and the letter."""
    if not claim.get("decision"):
        status, action, reason = route(claim)
        claim["status"], claim["recommendedAction"], claim["routingReason"] = status, action, reason
    claim["riskLevel"] = risk_level(claim["riskScore"])
    claim["settlement"] = compute_settlement(claim)
    claim["letter"] = build_letter(claim)
    return claim


def apply_decision(claim: dict, action: str, notes: str = "", at: str | None = None, by: str = "Adjuster") -> dict:
    if action not in DECISIONS:
        raise ValueError("Unknown decision. Use one of: " + ", ".join(DECISIONS))
    before = compute_settlement(claim)
    approved = None
    if action == "APPROVE_RECOMMENDED":
        status, approved = "APPROVED", before["recommended"]
    elif action == "APPROVE_FULL":
        status, approved = "APPROVED", before["claimed"]
    elif action == "REFER_SIU":
        status = "SIU_ESCALATED"
    else:
        status, approved = "DENIED", 0.0
    at = at or now_iso()
    claim["status"] = status
    claim["decision"] = {"action": action, "label": DECISIONS[action], "approvedAmount": approved,
                         "notes": (notes or "").strip()[:500], "by": by, "at": at}
    claim.setdefault("history", []).append({"at": at, "event": DECISIONS[action], "by": by})
    claim["settlement"] = compute_settlement(claim)
    claim["letter"] = build_letter(claim)
    return claim
