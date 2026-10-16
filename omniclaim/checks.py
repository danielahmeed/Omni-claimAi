"""Deterministic checks that run on every claim, with or without Gemini.

The results are shown to the adjuster as findings and are also passed to
Gemini as context, so the model weighs them in its assessment.
"""

import re
from datetime import date

from . import policies
from .config import DUPLICATE_PHOTO_MAX_DISTANCE, NEW_POLICY_ALERT_DAYS
from .imaging import hamming_distance


def finding(title: str, severity: str, detail: str, source: str) -> dict:
    return {"title": title, "severity": severity, "detail": detail, "source": source}


def _name_tokens(name: str) -> set[str]:
    name = re.sub(r"['\"‘’“”].*?['\"‘’“”]", " ", name or "")  # drop quoted nicknames
    return {t for t in re.findall(r"[a-z]+", name.lower()) if len(t) > 1}


def find_photo_matches(dhash: str, index: list[dict], exclude_id: str | None = None) -> list[dict]:
    """index: [{claimId, claimantName, createdAt, dhash}] for claims that have photos."""
    matches = []
    for entry in index:
        if entry["claimId"] == exclude_id or not entry.get("dhash"):
            continue
        distance = hamming_distance(dhash, entry["dhash"])
        if distance <= DUPLICATE_PHOTO_MAX_DISTANCE:
            matches.append({"claimId": entry["claimId"], "claimantName": entry.get("claimantName"),
                            "createdAt": entry.get("createdAt"), "distance": distance})
    return sorted(matches, key=lambda m: (m["distance"], m["createdAt"] or ""))


def find_document_matches(sha256: str, index: list[dict], exclude_id: str | None = None) -> list[dict]:
    return [{"claimId": e["claimId"], "claimantName": e.get("claimantName"), "createdAt": e.get("createdAt")}
            for e in index if e["claimId"] != exclude_id and e.get("sha256") == sha256]


def photo_findings(metadata: dict | None, matches: list[dict], incident: date | None) -> list[dict]:
    out = []
    if matches:
        listed = ", ".join(f"{m['claimId']} ({m['claimantName']})" for m in matches[:3])
        closest = matches[0]["distance"]
        out.append(finding(
            "Photo already used in another claim", "CRITICAL",
            f"This photo matches the photo submitted with {listed}. {closest} of 64 perceptual-hash bits differ "
            f"(0 means identical).", "photo-check"))
    if metadata is None:
        return out
    if metadata.get("editedWith"):
        out.append(finding("Photo was edited", "MEDIUM",
                           f"The photo's metadata shows it was saved by editing software ({metadata['editedWith']}).",
                           "photo-check"))
    captured = policies.parse_date(metadata.get("capturedAt"))
    if captured and incident:
        gap = (incident - captured).days
        if gap > 2:
            out.append(finding("Photo taken before the incident", "MEDIUM",
                               f"Camera metadata says the photo was taken on {captured.isoformat()}, "
                               f"{gap} days before the reported incident date.", "photo-check"))
        else:
            device = " ".join(filter(None, [metadata.get("cameraMake"), metadata.get("cameraModel")])) or "an unknown camera"
            out.append(finding("Photo date matches the incident", "INFO",
                               f"Taken on {captured.isoformat()} with {device}.", "photo-check"))
    elif not metadata.get("hasExif") or not captured:
        out.append(finding("No camera date in photo", "INFO",
                           "The photo has no capture date in its metadata (common for screenshots and photos sent "
                           "through messaging apps), so the date could not be checked.", "photo-check"))
    return out


def document_findings(matches: list[dict]) -> list[dict]:
    if not matches:
        return []
    listed = ", ".join(f"{m['claimId']} ({m['claimantName']})" for m in matches[:3])
    return [finding("Same document already submitted", "CRITICAL",
                    f"This exact file was already submitted with {listed}.", "document-check")]


def policy_check(policy: dict | None, product: str, claimant: str, incident: date | None) -> tuple[dict, list[dict]]:
    if not policy:
        return ({"found": False}, [finding(
            "Policy not in the policy register", "MEDIUM",
            "The policy number was not found in the sample policy register, so the policy period, product and "
            "policyholder could not be verified.", "policy-check")])
    effective = policies.parse_date(policy.get("effectiveDate"))
    expiration = policies.parse_date(policy.get("expirationDate"))
    info = {"found": True, "holder": policy.get("holder"), "product": policy.get("product"),
            "effectiveDate": policy.get("effectiveDate"), "expirationDate": policy.get("expirationDate"),
            "endorsements": policy.get("endorsements", []), "daysSincePolicyStart": None, "inPolicyPeriod": None}
    out = []
    if policy.get("product") != product:
        out.append(finding("Claim type does not match the policy", "MEDIUM",
                           f"Policy {policy['policyNumber']} is a {policy.get('product')} policy but the claim was filed as {product}.",
                           "policy-check"))
    holder = _name_tokens(policy.get("holder", ""))
    if holder and not holder.issubset(_name_tokens(claimant)):
        out.append(finding("Claimant is not the named policyholder", "MEDIUM",
                           f"The policy is held by {policy.get('holder')}.", "policy-check"))
    if incident and effective and expiration:
        in_period = effective <= incident <= expiration
        info["inPolicyPeriod"] = in_period
        info["daysSincePolicyStart"] = (incident - effective).days
        if not in_period:
            out.append(finding("Loss outside the policy period", "CRITICAL",
                               f"The incident date {incident.isoformat()} is outside the policy period "
                               f"{effective.isoformat()} to {expiration.isoformat()}.", "policy-check"))
        elif info["daysSincePolicyStart"] < NEW_POLICY_ALERT_DAYS:
            out.append(finding("Loss soon after the policy started", "MEDIUM",
                               f"The loss happened {info['daysSincePolicyStart']} days after the policy started on "
                               f"{effective.isoformat()}.", "policy-check"))
    return info, out


def benchmark_findings(bench: dict, amount: float) -> list[dict]:
    pct = bench.get("claimPercentile")
    if pct is None or not bench.get("sampleSize"):
        return []
    label = bench["categoryLabel"].lower()
    if pct >= 95:
        share = (f"higher than all {bench['sampleSize']:,}" if pct >= 99.95
                 else f"higher than {pct:.1f}% of {bench['sampleSize']:,}")
        return [finding("Amount far above similar claims", "MEDIUM",
                        f"${amount:,.2f} is {share} {label} "
                        f"(95th percentile ${bench['p95']:,.0f}, median ${bench['median']:,.0f}).", "benchmark")]
    if pct >= 75:
        return [finding("Amount above most similar claims", "INFO",
                        f"${amount:,.2f} is at the {pct:.0f}th percentile of {bench['sampleSize']:,} {label} "
                        f"(median ${bench['median']:,.0f}).", "benchmark")]
    return [finding("Amount typical for similar claims", "INFO",
                    f"${amount:,.2f} is at the {pct:.0f}th percentile of {bench['sampleSize']:,} {label} "
                    f"(median ${bench['median']:,.0f}).", "benchmark")]


def amount_findings(claimed: float, document_total: float | None, items_total: float | None) -> list[dict]:
    out = []
    if document_total and abs(document_total - claimed) > max(50.0, 0.02 * claimed):
        out.append(finding("Claimed amount differs from the document", "MEDIUM",
                           f"The claim form says ${claimed:,.2f} but the document total is ${document_total:,.2f}.",
                           "amount-check"))
    if document_total and items_total and abs(document_total - items_total) > max(1.0, 0.01 * document_total):
        out.append(finding("Line items do not add up to the total", "INFO",
                           f"The extracted line items add up to ${items_total:,.2f} but the document total is "
                           f"${document_total:,.2f}. Some lines may not have been read.", "amount-check"))
    return out
