"""Demo mode: what happens when Gemini is not configured.

* If the uploaded document and photo are one of the bundled sample pairs in
  samples/, a recorded assessment for that pair is replayed (clearly labeled
  "recorded demo result" in the UI).
* Anything else gets an honest "not analyzed" assessment and goes to an
  adjuster. Nothing is invented about files the system did not read.

All deterministic checks (reused photo, metadata, policy dates, benchmarks)
still run for real in demo mode.
"""

import hashlib
import json
from functools import lru_cache

from .config import BASE_DIR, DUPLICATE_PHOTO_MAX_DISTANCE, RECORDED_DEMO_FILE
from .imaging import dhash, hamming_distance, open_image
from .schemas import ClaimAssessment


@lru_cache(maxsize=1)
def _recorded() -> list[dict]:
    try:
        data = json.loads(RECORDED_DEMO_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = []
    for entry in data.get("analyses", []):
        doc_path = BASE_DIR / entry["document"]
        photo_path = BASE_DIR / entry["photo"] if entry.get("photo") else None
        try:
            doc_sha = hashlib.sha256(doc_path.read_bytes()).hexdigest()
            photo_hash = dhash(open_image(photo_path.read_bytes())) if photo_path else None
        except (OSError, ValueError):
            continue
        entries.append({"sha256": doc_sha, "dhash": photo_hash, "name": entry.get("name", ""),
                        "assessment": ClaimAssessment.model_validate(entry["assessment"])})
    return entries


def recorded_assessment(document_sha256: str | None, photo_dhash: str | None) -> tuple[ClaimAssessment, str] | None:
    if not document_sha256:
        return None
    for entry in _recorded():
        if entry["sha256"] != document_sha256:
            continue
        if entry["dhash"] and photo_dhash and hamming_distance(entry["dhash"], photo_dhash) <= DUPLICATE_PHOTO_MAX_DISTANCE:
            return entry["assessment"].model_copy(deep=True), entry["name"]
    return None


def generic_assessment(has_photo: bool, has_document: bool, docai: dict | None = None) -> ClaimAssessment:
    """Assessment for uploads that Gemini did not analyze.

    If Document AI read the bill, its line items are shown, held for the adjuster
    (they could not be compared with the photo).
    """
    read_by_docai = bool(docai and docai.get("lineItems"))
    unread = [name for name, present in (("photo", has_photo), ("document", has_document and not read_by_docai))
              if present]
    if unread:
        detail = ("Gemini is not configured on this server, so the uploaded " + " and ".join(unread) +
                  (" were" if len(unread) > 1 else " was") + " not analyzed. An adjuster must review it, or configure "
                  "Gemini (see the Settings dialog) to analyze uploads.")
    else:
        detail = "Gemini is not configured, so only the automated checks ran."
    findings = [{"title": "AI analysis not available", "severity": "MEDIUM", "detail": detail}]
    line_items = []
    if read_by_docai:
        skipped = 0
        for line in docai["lineItems"]:
            if line.get("amount") is None:
                skipped += 1
                continue
            line_items.append({
                "description": line["description"], "billed_amount": line["amount"], "photo_evidence": "NOT_CHECKED",
                "recommendation": "REVIEW", "allowed_amount": 0,
                "reason": "Read by Document AI. Not compared with the photo because Gemini is not configured."})
        findings.append({"title": "Bill read by Document AI only", "severity": "MEDIUM",
                         "detail": f"Document AI extracted {len(line_items)} billed line(s)"
                                   + (f" ({skipped} without an amount)" if skipped else "")
                                   + ". They are held for the adjuster because no AI compared them with the photo."})
    return ClaimAssessment(
        photo_description="Not analyzed: Gemini is not configured." if has_photo else "No photo provided.",
        damage_regions=[],
        document_type=("Invoice (read by Document AI)" if read_by_docai
                       else "Not analyzed" if has_document else "None provided"),
        vendor_name=(docai or {}).get("vendor") if read_by_docai else None,
        document_total=(docai or {}).get("total") if read_by_docai else None,
        line_items=line_items,
        clause_assessments=[],
        coverage_decision="NEEDS_REVIEW",
        findings=findings,
        risk_score=45,
        risk_rationale="Without an AI assessment the claim cannot be scored reliably, so it is routed to an adjuster "
                       "with a neutral score.",
        claimant_explanation="We have received your claim and the documents you sent. A claims adjuster will review "
                             "them and contact you if anything else is needed.",
    )


def demo_copilot_answer(claim: dict, question: str) -> str:
    """Template answers built from the real claim data (no AI involved)."""
    q = question.lower()
    s = claim["settlement"]
    if any(w in q for w in ("why", "flag", "risk", "fraud", "suspicious")):
        top = [f for f in claim["findings"] if f["severity"] != "INFO"][:4] or claim["findings"][:3]
        lines = [f"**{claim['id']}** has risk score **{claim['riskScore']}** ({claim['riskLevel'].lower()}).",
                 f"Routing: {claim['routingReason']}", "", "Main findings:"]
        lines += [f"- **{f['title']}**: {f['detail']}" for f in top]
        return "\n".join(lines)
    if any(w in q for w in ("policy", "clause", "cover", "exclusion", "deductible")):
        clauses = claim["coverage"]["clauses"]
        if not clauses:
            return "No policy clauses were assessed for this claim."
        lines = [f"Coverage decision: **{claim['coverage']['decision'].replace('_', ' ').lower()}**.", ""]
        lines += [f"- **{c['clauseId']} {c['title']}** ({c['verdict'].replace('_', ' ').lower()}): {c['explanation']}"
                  for c in clauses]
        return "\n".join(lines)
    if any(w in q for w in ("benchmark", "compare", "cost", "typical", "percentile")):
        b = claim["benchmark"]
        return (f"Compared with {b['sampleSize']:,} {b['categoryLabel'].lower()}, the claimed "
                f"${s['claimed']:,.2f} is at the **{b['claimPercentile']:.0f}th percentile** "
                f"(median ${b['median']:,.0f}, 95th percentile ${b['p95']:,.0f}). Source: {b['dataset']}.")
    if any(w in q for w in ("letter", "draft", "email", "write")):
        return "Here is the current letter draft:\n\n" + claim["letter"]
    if any(w in q for w in ("line", "item", "invoice", "bill", "estimate", "disallow")):
        items = claim["lineItems"]
        if not items:
            return "No line items were extracted for this claim."
        lines = [f"- {i['description']}: billed ${i['billedAmount']:,.2f}, "
                 f"{i['recommendation'].lower()} (${i['allowedAmount']:,.2f}). {i['reason']}" for i in items]
        return "\n".join(lines)
    return (f"**{claim['id']}** ({claim['claimantName']}): status {claim['status'].replace('_', ' ').lower()}, "
            f"risk {claim['riskScore']}. Claimed ${s['claimed']:,.2f}; recommended ${s['recommended']:,.2f}; "
            f"payment ${s['net']:,.2f}.\n\nAsk about the risk flags, policy clauses, line items, cost benchmark "
            "or the claimant letter. (Demo mode: answers are templates built from the claim data. Configure Gemini "
            "for free-form answers.)")
