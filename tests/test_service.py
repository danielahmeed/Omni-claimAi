import base64
import threading
import unittest
from unittest import mock

from omniclaim import service as service_module
from omniclaim.service import SubmissionError
from tests.helpers import TempService, file_upload, preset_payload


class SeedDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = TempService()
        cls.claims = {c["id"]: c for c in cls.env.service.list_claims()}

    @classmethod
    def tearDownClass(cls):
        cls.env.close()

    def test_sample_statuses(self):
        expected = {"CLM-8977": "APPROVED", "CLM-8819": "AUTO_APPROVED", "CLM-8750": "AUTO_APPROVED",
                    "CLM-9231": "ADJUSTER_REVIEW", "CLM-9042": "ADJUSTER_REVIEW", "CLM-9104": "SIU_ESCALATED"}
        self.assertEqual({k: v["status"] for k, v in self.claims.items()}, expected)

    def test_every_claim_adds_up(self):
        for claim in self.claims.values():
            s = claim["settlement"]
            self.assertAlmostEqual(s["recommended"] + s["held"] + s["disallowed"], s["claimed"], places=2, msg=claim["id"])
            self.assertGreaterEqual(s["net"], 0)
            if claim["lineItems"] and claim["coverage"]["decision"] != "NOT_COVERED":
                allowed = sum(i["allowedAmount"] for i in claim["lineItems"])
                self.assertAlmostEqual(allowed, s["recommended"], places=2, msg=claim["id"])

    def test_known_sample_numbers(self):
        self.assertEqual(self.claims["CLM-9042"]["settlement"]["net"], 750.0)
        self.assertEqual(self.claims["CLM-9042"]["settlement"]["disallowed"], 7200.0)
        self.assertEqual(self.claims["CLM-8819"]["settlement"]["net"], 2950.0)
        self.assertEqual(self.claims["CLM-8750"]["settlement"]["net"], 680.0)
        self.assertEqual(self.claims["CLM-8977"]["settlement"]["net"], 3400.0)
        self.assertEqual(self.claims["CLM-9231"]["settlement"]["net"], 0.0)

    def test_reused_photo_is_detected_by_the_real_check(self):
        matches = self.claims["CLM-9104"]["photo"]["matches"]
        self.assertEqual([m["claimId"] for m in matches], ["CLM-8977"])
        titles = [f["title"] for f in self.claims["CLM-9104"]["findings"] if f["source"] == "photo-check"]
        self.assertIn("Photo already used in another claim", titles)

    def test_samples_are_labeled(self):
        for claim in self.claims.values():
            self.assertTrue(claim["isSample"])
            self.assertEqual(claim["analysis"]["engine"], "sample")


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.env = TempService()
        self.service = self.env.service

    def tearDown(self):
        self.env.close()

    def test_presets_in_demo_mode(self):
        outcomes = {}
        for preset in ("inflated-bill", "storm-windshield", "burst-pipe", "reused-photo"):
            claim = self.service.analyze(preset_payload(preset))
            outcomes[preset] = (claim["status"], claim["analysis"]["engine"])
            self.assertEqual(claim["analysis"]["label"], "Recorded demo result (Gemini not configured)")
        self.assertEqual(outcomes, {
            "inflated-bill": ("ADJUSTER_REVIEW", "recorded-demo"),
            "storm-windshield": ("AUTO_APPROVED", "recorded-demo"),
            "burst-pipe": ("AUTO_APPROVED", "recorded-demo"),
            "reused-photo": ("SIU_ESCALATED", "recorded-demo"),
        })

    def test_glass_claim_uses_glass_deductible(self):
        claim = self.service.analyze(preset_payload("storm-windshield"))
        self.assertEqual(claim["deductible"], 100.0)
        self.assertEqual(claim["lossCategory"], "auto_glass")

    def test_resubmitting_the_same_files_is_flagged(self):
        first = self.service.analyze(preset_payload("burst-pipe"))
        second = self.service.analyze(preset_payload("burst-pipe"))
        self.assertEqual(first["status"], "AUTO_APPROVED")
        self.assertEqual(second["status"], "SIU_ESCALATED")
        self.assertEqual(second["photo"]["matches"][0]["claimId"], first["id"])
        self.assertEqual(second["document"]["matches"][0]["claimId"], first["id"])

    def test_unknown_upload_is_not_invented(self):
        payload = preset_payload("inflated-bill", with_files=False)
        payload["claimantName"] = "New Person"
        payload["policyNumber"] = "POL-AUTO-00001"
        payload["photo"] = file_upload("samples/documents/windshield-invoice.png", "image/png")
        claim = self.service.analyze(payload)
        self.assertEqual(claim["analysis"]["engine"], "demo-generic")
        self.assertEqual(claim["lineItems"], [])
        self.assertEqual(claim["status"], "ADJUSTER_REVIEW")
        titles = [f["title"] for f in claim["findings"]]
        self.assertIn("Policy not in the policy register", titles)
        self.assertIn("AI analysis not available", titles)

    def test_pdf_document_is_accepted_and_stored(self):
        pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
        payload = preset_payload("inflated-bill", with_files=False)
        payload["document"] = {"name": "estimate.pdf", "type": "application/pdf", "data": base64.b64encode(pdf).decode()}
        claim = self.service.analyze(payload)
        self.assertEqual(claim["document"]["mimeType"], "application/pdf")
        data, mime, name = self.service.claim_file(claim["id"], "document")
        self.assertEqual((data, mime, name), (pdf, "application/pdf", "estimate.pdf"))

    def test_photo_file_is_served_back(self):
        claim = self.service.analyze(preset_payload("storm-windshield"))
        data, mime, _ = self.service.claim_file(claim["id"], "photo")
        self.assertEqual(mime, "image/jpeg")
        self.assertTrue(data.startswith(b"\xff\xd8"))

    def test_decisions_and_legacy_action_names(self):
        claim = self.service.decide("CLM-9042", {"action": "APPROVE"})  # legacy name for APPROVE_FULL
        self.assertEqual((claim["status"], claim["settlement"]["net"]), ("APPROVED", 7950.0))
        claim = self.service.decide("CLM-9042", {"action": "APPROVE_ADJUSTED"})
        self.assertEqual(claim["settlement"]["net"], 750.0)
        with self.assertRaises(SubmissionError):
            self.service.decide("CLM-9042", {"action": "NOPE"})

    def test_demo_copilot_uses_claim_data(self):
        answer = self.service.copilot("CLM-9042", {"question": "Why was this flagged?"})
        self.assertEqual(answer["engine"], "demo")
        self.assertIn("74", answer["answer"])
        answer = self.service.copilot("CLM-9231", {"question": "Which policy clauses apply?"})
        self.assertIn("EXCL-4.B", answer["answer"])

    def test_reset_restores_samples(self):
        self.service.analyze(preset_payload("burst-pipe"))
        self.assertEqual(len(self.service.list_claims()), 7)
        with mock.patch.object(service_module, "ALLOW_DATA_RESET", True):
            self.service.reset()
        self.assertEqual(len(self.service.list_claims()), 6)

    def test_reset_can_be_disabled(self):
        with mock.patch.object(service_module, "ALLOW_DATA_RESET", False):
            with self.assertRaises(PermissionError):
                self.service.reset()


class LocalStoreTest(unittest.TestCase):
    def setUp(self):
        self.env = TempService()

    def tearDown(self):
        self.env.close()

    def test_claim_numbers_are_unique_under_concurrency(self):
        ids, lock = [], threading.Lock()

        def take():
            for _ in range(25):
                claim_id = self.env.service.store.next_id()
                with lock:
                    ids.append(claim_id)

        threads = [threading.Thread(target=take) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(set(ids)), 100)

    def test_rejected_uploads_do_not_use_up_numbers(self):
        payload = preset_payload("burst-pipe", with_files=False)
        with self.assertRaises(SubmissionError):
            self.env.service.analyze({**payload, "photo": {"data": base64.b64encode(b"not an image").decode()}})
        self.assertEqual(self.env.service.analyze(payload)["id"], "CLM-9232")


class ValidationTest(unittest.TestCase):
    def setUp(self):
        self.env = TempService()

    def tearDown(self):
        self.env.close()

    def assert_rejected(self, payload, field):
        with self.assertRaises(SubmissionError) as ctx:
            self.env.service.analyze(payload)
        self.assertEqual(ctx.exception.field, field)

    def test_field_validation(self):
        base = preset_payload("burst-pipe", with_files=False)
        self.assert_rejected({**base, "claimantName": ""}, "claimantName")
        self.assert_rejected({**base, "policyNumber": "BAD NUMBER!"}, "policyNumber")
        self.assert_rejected({**base, "incidentDate": "2999-01-01"}, "incidentDate")
        self.assert_rejected({**base, "incidentDate": "yesterday"}, "incidentDate")
        self.assert_rejected({**base, "claimedAmount": -5}, "claimedAmount")
        self.assert_rejected({**base, "claimedAmount": "abc"}, "claimedAmount")
        self.assert_rejected({**base, "product": "boat"}, "product")
        self.assert_rejected({**base, "description": "short"}, "description")

    def test_upload_validation(self):
        base = preset_payload("burst-pipe", with_files=False)
        self.assert_rejected({**base, "photo": {"data": "@@not-base64@@"}}, "photo")
        self.assert_rejected({**base, "photo": {"data": base64.b64encode(b"hello").decode()}}, "photo")
        self.assert_rejected({**base, "photo": "just-a-string"}, "photo")
        with mock.patch.object(service_module, "MAX_UPLOAD_MB", 0.01):
            self.assert_rejected({**base, "document": file_upload("samples/documents/collision-invoice.png")}, "document")


if __name__ == "__main__":
    unittest.main()
