import unittest
from datetime import date

from omniclaim import adjudication, checks
from omniclaim.schemas import ClaimAssessment


def make_claim(**overrides) -> dict:
    claim = {
        "id": "CLM-9999", "claimantName": "Test Person", "lossType": "Collision", "claimedAmount": 1000.0,
        "deductible": 100.0, "riskScore": 10, "status": None, "decision": None, "findings": [],
        "lineItems": [
            {"description": "Bumper", "billedAmount": 600.0, "photoEvidence": "SUPPORTED", "recommendation": "ALLOW",
             "allowedAmount": 600.0, "reason": ""},
            {"description": "Paint", "billedAmount": 400.0, "photoEvidence": "NOT_APPLICABLE", "recommendation": "ALLOW",
             "allowedAmount": 400.0, "reason": ""},
        ],
        "coverage": {"decision": "COVERED", "clauses": []},
        "photo": {"matches": [], "dhash": "0" * 16}, "document": None, "explanation": "We reviewed your claim.",
        "analysis": {"engine": "gemini"},
    }
    claim.update(overrides)
    return claim


class RoutingTest(unittest.TestCase):
    def test_clean_low_risk_claim_is_auto_approved(self):
        claim = adjudication.finalize(make_claim())
        self.assertEqual(claim["status"], "AUTO_APPROVED")
        self.assertEqual(claim["settlement"]["approved"], 1000.0)
        self.assertEqual(claim["settlement"]["net"], 900.0)

    def test_high_risk_goes_to_siu(self):
        claim = adjudication.finalize(make_claim(riskScore=85))
        self.assertEqual(claim["status"], "SIU_ESCALATED")
        self.assertEqual(claim["settlement"]["net"], 0.0)

    def test_reused_photo_always_goes_to_siu(self):
        claim = adjudication.finalize(make_claim(photo={"matches": [{"claimId": "CLM-1"}]}))
        self.assertEqual(claim["status"], "SIU_ESCALATED")

    def test_medium_finding_blocks_auto_approval(self):
        claim = adjudication.finalize(make_claim(findings=[{"title": "x", "severity": "MEDIUM", "detail": "", "source": "x"}]))
        self.assertEqual(claim["status"], "ADJUSTER_REVIEW")

    def test_missing_bill_blocks_auto_approval(self):
        claim = adjudication.finalize(make_claim(lineItems=[]))
        self.assertEqual(claim["status"], "ADJUSTER_REVIEW")
        self.assertIn("no itemized bill", claim["routingReason"])

    def test_missing_photo_blocks_auto_approval(self):
        claim = adjudication.finalize(make_claim(photo=None))
        self.assertEqual(claim["status"], "ADJUSTER_REVIEW")
        self.assertIn("no damage photo", claim["routingReason"])

    def test_demo_generic_never_auto_approves(self):
        claim = adjudication.finalize(make_claim(analysis={"engine": "demo-generic"}))
        self.assertEqual(claim["status"], "ADJUSTER_REVIEW")

    def test_exclusion_recommends_denial_with_zero_payment(self):
        claim = adjudication.finalize(make_claim(riskScore=40, coverage={"decision": "NOT_COVERED", "clauses": []}))
        self.assertEqual(claim["status"], "ADJUSTER_REVIEW")
        self.assertEqual(claim["recommendedAction"], "DENY")
        self.assertEqual(claim["settlement"]["recommended"], 0.0)
        self.assertEqual(claim["settlement"]["net"], 0.0)


class SettlementTest(unittest.TestCase):
    def test_disallowed_and_held_lines(self):
        items = [
            {"description": "a", "billedAmount": 500.0, "recommendation": "ALLOW", "allowedAmount": 500.0},
            {"description": "b", "billedAmount": 300.0, "recommendation": "REDUCE", "allowedAmount": 200.0},
            {"description": "c", "billedAmount": 150.0, "recommendation": "REVIEW", "allowedAmount": 0.0},
            {"description": "d", "billedAmount": 50.0, "recommendation": "DISALLOW", "allowedAmount": 0.0},
        ]
        claim = adjudication.finalize(make_claim(riskScore=40, lineItems=items))
        s = claim["settlement"]
        self.assertEqual((s["recommended"], s["held"], s["disallowed"]), (700.0, 150.0, 150.0))
        self.assertEqual(s["net"], 600.0)
        self.assertEqual(s["recommended"] + s["held"] + s["disallowed"], s["claimed"])

    def test_deductible_larger_than_amount_never_negative(self):
        claim = adjudication.finalize(make_claim(deductible=5000.0))
        self.assertEqual(claim["settlement"]["net"], 0.0)

    def test_recommended_never_exceeds_claimed(self):
        items = [{"description": "a", "billedAmount": 2000.0, "recommendation": "ALLOW", "allowedAmount": 2000.0}]
        claim = adjudication.finalize(make_claim(riskScore=40, lineItems=items))
        self.assertEqual(claim["settlement"]["recommended"], 1000.0)


class DecisionTest(unittest.TestCase):
    """Regression tests for the old bug where switching decisions left a stale payout."""

    def setUp(self):
        items = [
            {"description": "ok", "billedAmount": 400.0, "recommendation": "ALLOW", "allowedAmount": 400.0},
            {"description": "no", "billedAmount": 600.0, "recommendation": "DISALLOW", "allowedAmount": 0.0},
        ]
        self.claim = adjudication.finalize(make_claim(riskScore=50, lineItems=items))

    def test_full_then_recommended_recomputes_payment(self):
        adjudication.apply_decision(self.claim, "APPROVE_FULL")
        self.assertEqual(self.claim["settlement"]["net"], 900.0)
        adjudication.apply_decision(self.claim, "APPROVE_RECOMMENDED")
        self.assertEqual(self.claim["settlement"]["approved"], 400.0)
        self.assertEqual(self.claim["settlement"]["net"], 300.0)
        self.assertIn("$300.00", self.claim["letter"])
        self.assertNotIn("$900.00", self.claim["letter"])

    def test_siu_and_deny_pay_nothing(self):
        adjudication.apply_decision(self.claim, "REFER_SIU")
        self.assertEqual((self.claim["status"], self.claim["settlement"]["net"]), ("SIU_ESCALATED", 0.0))
        self.assertNotIn("fraud", self.claim["letter"].lower(), "letters must not tip off the claimant")
        adjudication.apply_decision(self.claim, "DENY")
        self.assertEqual((self.claim["status"], self.claim["settlement"]["net"]), ("DENIED", 0.0))

    def test_unknown_decision_rejected(self):
        with self.assertRaises(ValueError):
            adjudication.apply_decision(self.claim, "PAY_DOUBLE")

    def test_history_records_decisions(self):
        adjudication.apply_decision(self.claim, "APPROVE_FULL", notes="ok")
        self.assertEqual(self.claim["history"][-1]["event"], "Approved the full claimed amount")


class NormalizationTest(unittest.TestCase):
    def test_model_amounts_are_sanitized(self):
        assessment = ClaimAssessment.model_validate({
            "photo_description": "x", "damage_regions": [{"label": "a", "severity": "MINOR", "box_2d": [10, 20, 900, 1500]},
                                                         {"label": "tiny", "severity": "MINOR", "box_2d": [1, 1, 2, 2]}],
            "document_type": "Invoice", "line_items": [
                {"description": "a", "billed_amount": -5, "photo_evidence": "SUPPORTED", "recommendation": "ALLOW",
                 "allowed_amount": 999, "reason": "r"},
                {"description": "b", "billed_amount": 100, "photo_evidence": "SUPPORTED", "recommendation": "REDUCE",
                 "allowed_amount": 250, "reason": "r"},
                {"description": "c", "billed_amount": 100, "photo_evidence": "NOT_SUPPORTED", "recommendation": "DISALLOW",
                 "allowed_amount": 100, "reason": "r"}],
            "clause_assessments": [], "coverage_decision": "COVERED", "findings": [], "risk_score": 5,
            "risk_rationale": "r", "claimant_explanation": "e"})
        items = adjudication.normalize_line_items(assessment)
        self.assertEqual([i["allowedAmount"] for i in items], [0.0, 100.0, 0.0])
        regions = adjudication.damage_regions(assessment)
        self.assertEqual(regions, [{"label": "a", "severity": "MINOR", "box": [10, 20, 900, 1000]}])


class ChecksTest(unittest.TestCase):
    def test_policy_period_and_new_policy(self):
        policy = {"policyNumber": "P-1", "holder": "Ann Lee", "product": "auto",
                  "effectiveDate": "2026-10-01", "expirationDate": "2027-10-01"}
        info, found = checks.policy_check(policy, "auto", "Ann Lee", date(2026, 10, 5))
        self.assertEqual(info["daysSincePolicyStart"], 4)
        self.assertEqual([f["title"] for f in found], ["Loss soon after the policy started"])
        _, found = checks.policy_check(policy, "auto", "Ann Lee", date(2026, 9, 1))
        self.assertEqual(found[0]["severity"], "CRITICAL")

    def test_nicknames_do_not_break_name_match(self):
        policy = {"policyNumber": "P-1", "holder": "Devon Vance", "product": "auto",
                  "effectiveDate": "2020-01-01", "expirationDate": "2030-01-01"}
        _, found = checks.policy_check(policy, "auto", "Devon 'Ace' Vance", date(2026, 1, 1))
        self.assertEqual(found, [])
        _, found = checks.policy_check(policy, "auto", "Someone Else", date(2026, 1, 1))
        self.assertEqual(found[0]["title"], "Claimant is not the named policyholder")

    def test_photo_taken_before_incident(self):
        meta = {"hasExif": True, "capturedAt": "2026-01-01T10:00:00", "cameraMake": "X", "cameraModel": "Y",
                "editedWith": None}
        found = checks.photo_findings(meta, [], date(2026, 10, 1))
        self.assertEqual(found[0]["title"], "Photo taken before the incident")

    def test_amount_mismatch(self):
        found = checks.amount_findings(1000.0, 1500.0, 1500.0)
        self.assertEqual([f["title"] for f in found], ["Claimed amount differs from the document"])


if __name__ == "__main__":
    unittest.main()
