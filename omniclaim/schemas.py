"""Structured output that Gemini must return for a claim assessment.

The Pydantic model is passed to Gemini as `response_schema`, so the model can
only answer with JSON in exactly this shape. Field descriptions are part of
the instructions the model sees. The field order also matters: Gemini fills
the evidence fields (photo, document, line items) before it scores risk.

Recorded demo analyses and the sample claims use the same shape, so every
claim in the app goes through the same downstream code.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

Severity = Literal["INFO", "MEDIUM", "CRITICAL"]


class DamageRegion(BaseModel):
    label: str = Field(description="Short name of the damaged area, for example 'Paint scrape on rear wheel arch'.")
    severity: Literal["MINOR", "MODERATE", "SEVERE"]
    box_2d: list[int] = Field(
        description="Bounding box of the damaged area on the photo as [ymin, xmin, ymax, xmax], integers scaled 0-1000.")


class LineItemAssessment(BaseModel):
    description: str = Field(description="The line item text exactly as written on the document.")
    billed_amount: float = Field(description="Amount billed for this line, as a plain number.")
    photo_evidence: Literal["SUPPORTED", "NOT_SUPPORTED", "NOT_VISIBLE", "NOT_APPLICABLE", "NOT_CHECKED"] = Field(
        description="SUPPORTED: damage clearly visible. NOT_SUPPORTED: the area is visible but undamaged or far less damaged. "
                    "NOT_VISIBLE: the area cannot be seen in the photo. NOT_APPLICABLE: fees, materials, diagnostics. "
                    "NOT_CHECKED: there is no photo to compare with.")
    recommendation: Literal["ALLOW", "REDUCE", "DISALLOW", "REVIEW"] = Field(
        description="ALLOW: reasonable and supported. REDUCE: supported but overpriced. DISALLOW: not supported or not covered. "
                    "REVIEW: a human should decide (for example possible hidden damage).")
    allowed_amount: float = Field(description="Amount recommended for this line. 0 when DISALLOW; the full billed amount when ALLOW.")
    reason: str = Field(description="One sentence explaining the decision with reference to the photo, document or policy.")


class Finding(BaseModel):
    title: str = Field(description="Short headline, for example 'Billed suspension work not visible in photo'.")
    severity: Severity = Field(description="CRITICAL: likely fraud or an exclusion. MEDIUM: discrepancy needing review. INFO: neutral or reassuring fact.")
    detail: str = Field(description="One or two sentences with the specific evidence.")


class ClauseAssessment(BaseModel):
    clause_id: str = Field(description="Clause ID exactly as given in the policy wording, for example 'SEC-4.A'.")
    verdict: Literal["APPLIES", "SATISFIED", "NOT_MET", "EXCLUSION_TRIGGERED"] = Field(
        description="APPLIES: relevant term (for example a deductible). SATISFIED: the claim meets the clause. "
                    "NOT_MET: the claim does not meet it. EXCLUSION_TRIGGERED: an exclusion removes coverage.")
    explanation: str = Field(description="One sentence explaining how the clause applies to this claim.")


class ClaimAssessment(BaseModel):
    photo_description: str = Field(
        description="What the photo actually shows: the vehicle or property, which areas are damaged and how badly, and anything "
                    "unusual (old or weathered damage, a different vehicle than claimed, a photo of a screen). "
                    "Say 'No photo provided' when there is none.")
    damage_regions: list[DamageRegion] = Field(description="One entry per visibly damaged area. Empty if there is no photo.")
    document_type: str = Field(description="What the supporting document is, for example 'Repair invoice' or 'Police report'. "
                                           "'None provided' when there is no document.")
    vendor_name: Optional[str] = Field(default=None, description="Business that issued the document, if any.")
    document_total: Optional[float] = Field(default=None, description="Total amount shown on the document, if any.")
    line_items: list[LineItemAssessment] = Field(description="Every billed line on the document, in order. Empty if there is no document.")
    clause_assessments: list[ClauseAssessment] = Field(description="Only the policy clauses that are relevant to this claim.")
    coverage_decision: Literal["COVERED", "PARTIALLY_COVERED", "NOT_COVERED", "NEEDS_REVIEW"]
    findings: list[Finding] = Field(description="Evidence-based observations an adjuster should know, most important first.")
    risk_score: int = Field(description="0-19 consistent and safe to pay automatically; 20-79 needs a human adjuster; "
                                        "80-100 strong indicators of fraud.")
    risk_rationale: str = Field(description="Two or three sentences explaining the risk score.")
    claimant_explanation: str = Field(
        description="Two to four plain-language sentences to the claimant explaining the outcome of the review. "
                    "No dollar amounts, no mention of fraud or risk scores, no promise of payment.")
