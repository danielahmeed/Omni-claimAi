"""End-to-end tests of the Gemini path through the real google-genai SDK.

The SDK is pointed at a local fake endpoint, so these tests check the exact
HTTP request the app sends (model, photo and document parts, JSON schema,
thinking level) and how it handles real-shaped answers and errors, without
needing credentials or network access.
"""

import json
import unittest

from google import genai
from google.genai import types
from google.oauth2.credentials import Credentials

from tests.helpers import FakeGemini, TempService, preset_payload, recorded_assessment


def api_key_client(fake):
    return lambda s: genai.Client(api_key=s.api_key, http_options=types.HttpOptions(base_url=fake.url, timeout=20_000))


def vertex_client(fake):
    # A static access token stands in for the Cloud Run service account.
    return lambda s: genai.Client(enterprise=True, project=s.project, location=s.location,
                                  credentials=Credentials(token="test-access-token"),
                                  http_options=types.HttpOptions(base_url=fake.url, timeout=20_000))


class ApiKeyModeTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeGemini()
        self.env = TempService(backend="api-key", api_key="test-key-0000-1234", client_factory=api_key_client(self.fake))
        self.service = self.env.service

    def tearDown(self):
        self.fake.close()
        self.env.close()

    def test_assessment_request_contains_photo_document_and_schema(self):
        self.fake.reply_json(recorded_assessment("Inflated repair bill"))
        claim = self.service.analyze(preset_payload("inflated-bill"))

        request = self.fake.requests[-1]
        self.assertIn("models/gemini-3.8-flash:generateContent", request["path"])
        headers = {k.lower(): v for k, v in request["headers"].items()}
        self.assertEqual(headers.get("x-goog-api-key"), "test-key-0000-1234")

        body = request["body"]
        parts = body["contents"][0]["parts"]
        inline = [p["inlineData"].get("mimeType") or p["inlineData"].get("mime_type") for p in parts if "inlineData" in p]
        self.assertEqual(inline, ["image/jpeg", "image/jpeg"], "photo and document must both be sent")
        texts = " ".join(p.get("text", "") for p in parts)
        self.assertIn("CLAIM FILE (JSON)", texts)
        self.assertIn("SEC-4.A", texts, "policy wording must be included")
        self.assertIn("automated_checks", texts)

        config = body["generationConfig"]
        self.assertEqual(config["responseMimeType"], "application/json")
        schema = config.get("responseSchema") or config.get("responseJsonSchema")
        self.assertIsNotNone(schema, "a response schema must be sent")
        self.assertIn("line_items", json.dumps(schema))
        thinking = config["thinkingConfig"]
        self.assertEqual(thinking.get("thinkingLevel") or thinking.get("thinking_level"), "LOW")
        for unsupported in ("temperature", "topK", "topP", "candidateCount", "presencePenalty", "frequencyPenalty"):
            self.assertNotIn(unsupported, config)
        self.assertIn("systemInstruction", body)

        self.assertEqual(claim["analysis"]["engine"], "gemini")
        self.assertEqual(claim["analysis"]["model"], "gemini-3.8-flash")
        self.assertEqual(claim["status"], "ADJUSTER_REVIEW")
        self.assertEqual(claim["settlement"]["recommended"], 1250.0)
        self.assertEqual(claim["settlement"]["net"], 750.0)
        self.assertEqual(len(claim["damageRegions"]), 1)
        self.assertEqual(self.service.gemini.status()["state"], "live")

    def test_leaked_key_error_is_reported_and_falls_back(self):
        self.fake.reply_error(403, "Your API key was reported as leaked. Please use another API key.", "PERMISSION_DENIED")
        claim = self.service.analyze(preset_payload("inflated-bill"))
        self.assertEqual(claim["analysis"]["engine"], "recorded-demo")
        self.assertEqual(claim["analysis"]["label"], "Recorded demo result (Gemini call failed)")
        self.assertIn("API key was rejected", claim["analysis"]["notice"])
        gemini_step = next(s for s in claim["analysis"]["steps"] if s["name"] == "Gemini assessment")
        self.assertEqual(gemini_step["status"], "failed")
        status = self.service.gemini.status()
        self.assertEqual(status["state"], "error")
        self.assertIn("leaked", status["lastError"])

    def test_failed_gemini_call_never_auto_approves(self):
        self.fake.reply_error(500, "internal error", "INTERNAL")
        claim = self.service.analyze(preset_payload("storm-windshield"))  # auto-approved when Gemini works
        self.assertEqual(claim["status"], "ADJUSTER_REVIEW")
        self.assertIn("Gemini assessment failed", claim["routingReason"])

    def test_unknown_model_message(self):
        self.fake.reply_error(404, "models/gemini-x is not found", "NOT_FOUND")
        result = self.service.gemini.test_connection()
        self.assertFalse(result["ok"])
        self.assertIn("was not found", result["message"])

    def test_malformed_model_answer_falls_back(self):
        self.fake.reply_text("this is not json")
        claim = self.service.analyze(preset_payload("burst-pipe"))
        self.assertEqual(claim["analysis"]["engine"], "recorded-demo")
        self.assertIn("unexpected format", claim["analysis"]["notice"])

    def test_connection_test_success(self):
        self.fake.reply_text("OK")
        result = self.service.gemini.test_connection()
        self.assertTrue(result["ok"])
        self.assertEqual(result["message"], "OK")
        self.assertIn("latencyMs", result)

    def test_copilot_answer_comes_from_gemini(self):
        self.fake.reply_text("- The bill includes suspension work the photo does not support.")
        answer = self.service.copilot("CLM-9042", {"question": "Why was this flagged?",
                                                   "history": [{"role": "user", "text": "hi"}]})
        self.assertEqual(answer["engine"], "gemini")
        self.assertIn("suspension", answer["answer"])
        prompt = self.fake.requests[-1]["body"]["contents"][0]["parts"][0]["text"]
        self.assertIn("ADJUSTER QUESTION: Why was this flagged?", prompt)
        self.assertIn("CLM-9042", prompt)
        self.assertNotIn("data:image", prompt)


class VertexModeTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeGemini()
        self.env = TempService(backend="vertex", project="demo-project", location="global",
                               client_factory=vertex_client(self.fake))

    def tearDown(self):
        self.fake.close()
        self.env.close()

    def test_vertex_request_path_and_parsing(self):
        self.fake.reply_json(recorded_assessment("Storm-damaged windshield"))
        claim = self.env.service.analyze(preset_payload("storm-windshield"))
        request = self.fake.requests[-1]
        self.assertIn("projects/demo-project/locations/global/publishers/google/models/gemini-3.8-flash:generateContent",
                      request["path"])
        headers = {k.lower(): v for k, v in request["headers"].items()}
        self.assertEqual(headers.get("authorization"), "Bearer test-access-token")
        self.assertNotIn("x-goog-api-key", headers, "Vertex mode must not send an API key")
        self.assertEqual(claim["analysis"]["backend"], "vertex")
        self.assertEqual(claim["status"], "AUTO_APPROVED")
        self.assertEqual(claim["settlement"]["net"], 680.0)


if __name__ == "__main__":
    unittest.main()
