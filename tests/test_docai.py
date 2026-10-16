"""Document AI Invoice Parser: parsing, the real REST client against a fake endpoint, and the pipeline."""

import base64
import json
import threading
import unittest
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from google.auth.credentials import AnonymousCredentials
from google.cloud import documentai
from google.cloud.documentai_v1.services.document_processor_service.transports import (
    DocumentProcessorServiceRestTransport,
)

from omniclaim.docai import DocumentAIError, DocumentAIService, parse_amount, parse_document
from tests.helpers import FakeGemini, TempService, file_upload, preset_payload, recorded_assessment
from tests.test_gemini_integration import api_key_client
from tools.create_document_ai_processor import ensure_processor

warnings.filterwarnings("ignore", category=FutureWarning)

PROCESSOR = "projects/demo-project/locations/us/processors/abc123"
COLLISION_LINES = [
    ("Left rear wheel arch: repair and refinish (body labor 3.0 h)", "650"),
    ("Paint and materials (basecoat / clearcoat)", "350"),
    ("Clips, mouldings and hardware", "250"),
    ("Rear suspension assembly: replace (parts + 9.5 h labor)", "3800"),
    ("Exhaust system and heat shield: re-align, replace hangers", "1150"),
    ("Frame machine set-up and structural pull (rear)", "2250"),
]


def collision_document() -> dict:
    entities = [
        {"type": "supplier_name", "mentionText": "Apex Prestige Collision & Frame"},
        {"type": "invoice_id", "mentionText": "APC-26-1014-07"},
        {"type": "invoice_date", "mentionText": "2026-10-15",
         "normalizedValue": {"dateValue": {"year": 2026, "month": 10, "day": 15}}},
        {"type": "total_amount", "mentionText": "$8,450.00",
         "normalizedValue": {"moneyValue": {"currencyCode": "USD", "units": "8450"}}},
    ]
    for description, amount in COLLISION_LINES:
        entities.append({"type": "line_item", "mentionText": description, "properties": [
            {"type": "line_item/description", "mentionText": description},
            {"type": "line_item/amount", "mentionText": f"{float(amount):,.2f}",
             "normalizedValue": {"moneyValue": {"units": amount}}}]})
    return {"pages": [{}], "entities": entities}


class FakeDocumentAI:
    """Answers like the Document AI REST API: process, list processors, create processor."""

    def __init__(self):
        self.requests = []
        self.process_responses = []
        self.processors = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self, status, payload):
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                fake.requests.append({"method": "GET", "path": self.path})
                self._reply(200, {"processors": fake.processors})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                fake.requests.append({"method": "POST", "path": self.path, "body": body})
                if ":process" in self.path:
                    status, payload = (fake.process_responses.pop(0) if fake.process_responses
                                       else (200, {"document": collision_document()}))
                    self._reply(status, payload)
                else:
                    created = {"name": self.path.split("?")[0][len("/v1/"):] + "/new987",
                               "type": body.get("type"), "displayName": body.get("displayName")}
                    fake.processors.append(created)
                    self._reply(200, created)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.host = f"127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def client_factory(self, location=None):
        return documentai.DocumentProcessorServiceClient(transport=DocumentProcessorServiceRestTransport(
            host=self.host, credentials=AnonymousCredentials(), url_scheme="http"))

    def service(self) -> DocumentAIService:
        return DocumentAIService(PROCESSOR, client_factory=self.client_factory)

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class ParsingTest(unittest.TestCase):
    def test_parses_invoice_entities(self):
        result = parse_document(documentai.Document.from_json(json.dumps(collision_document())))
        self.assertEqual(result["vendor"], "Apex Prestige Collision & Frame")
        self.assertEqual((result["invoiceId"], result["invoiceDate"]), ("APC-26-1014-07", "2026-10-15"))
        self.assertEqual((result["total"], result["currency"]), (8450.0, "USD"))
        self.assertEqual([round(li["amount"]) for li in result["lineItems"]], [650, 350, 250, 3800, 1150, 2250])

    def test_fallbacks(self):
        doc = documentai.Document.from_json(json.dumps({"entities": [
            {"type": "line_item", "mentionText": "Clips\nx 5", "properties": [
                {"type": "line_item/quantity", "mentionText": "5"},
                {"type": "line_item/unit_price", "mentionText": "$50.00"}]},
            {"type": "line_item", "mentionText": "Labor", "properties": [
                {"type": "line_item/description", "mentionText": "Labor"},
                {"type": "line_item/amount", "mentionText": "USD 1,234.50"}]},
            {"type": "line_item", "mentionText": "Note without amount"},
        ]}))
        lines = parse_document(doc)["lineItems"]
        self.assertEqual([(li["description"], li["amount"]) for li in lines],
                         [("Clips x 5", 250.0), ("Labor", 1234.5), ("Note without amount", None)])

    def test_parse_amount(self):
        self.assertEqual(parse_amount("$8,450.00"), 8450.0)
        self.assertEqual(parse_amount("EUR 12"), 12.0)
        self.assertIsNone(parse_amount("n/a"))


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDocumentAI()

    def tearDown(self):
        self.fake.close()

    def test_request_and_status(self):
        service = self.fake.service()
        self.assertEqual(service.status()["state"], "configured")
        result = service.extract(b"\x89PNG fake", "image/png")
        request = self.fake.requests[-1]
        self.assertTrue(request["path"].startswith(f"/v1/{PROCESSOR}:process"))
        self.assertEqual(request["body"]["rawDocument"]["mimeType"], "image/png")
        self.assertEqual(base64.b64decode(request["body"]["rawDocument"]["content"]), b"\x89PNG fake")
        self.assertEqual(len(result["lineItems"]), 6)
        self.assertEqual(result["processor"], "abc123")
        self.assertEqual(service.status()["state"], "active")

    def test_permission_error(self):
        self.fake.process_responses.append((403, {"error": {"code": 403, "message": "Permission denied",
                                                            "status": "PERMISSION_DENIED"}}))
        service = self.fake.service()
        with self.assertRaises(DocumentAIError) as ctx:
            service.extract(b"%PDF-1.4", "application/pdf")
        self.assertIn("roles/documentai.apiUser", str(ctx.exception))
        self.assertEqual(service.status()["state"], "error")

    def test_configuration_errors(self):
        self.assertFalse(DocumentAIService("").configured())
        bad = DocumentAIService("my-processor-id")
        self.assertFalse(bad.configured())
        self.assertEqual(bad.status()["state"], "error")
        with self.assertRaises(DocumentAIError):
            self.fake.service().extract(b"data", "text/plain")

    def test_processor_tool_creates_once(self):
        client = self.fake.client_factory()
        name, created = ensure_processor(client, "demo-project", "us", "omniclaim-invoice-parser")
        self.assertTrue(created)
        self.assertEqual(name, "projects/demo-project/locations/us/processors/new987")
        create_request = next(r for r in self.fake.requests if r["method"] == "POST")
        self.assertEqual(create_request["body"]["type"], "INVOICE_PROCESSOR")
        name_again, created_again = ensure_processor(client, "demo-project", "us", "omniclaim-invoice-parser")
        self.assertEqual((name_again, created_again), (name, False))


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.fake_docai = FakeDocumentAI()

    def tearDown(self):
        self.fake_docai.close()

    def test_document_ai_reading_is_passed_to_gemini(self):
        gemini = FakeGemini()
        env = TempService(backend="api-key", api_key="k", client_factory=api_key_client(gemini),
                          docai=self.fake_docai.service())
        try:
            gemini.reply_json(recorded_assessment("Inflated repair bill"))
            claim = env.service.analyze(preset_payload("inflated-bill"))
            sent = self.fake_docai.requests[-1]["body"]["rawDocument"]
            self.assertEqual(sent["mimeType"], "image/png", "Document AI must receive the original file")
            step = next(s for s in claim["analysis"]["steps"] if s["name"] == "Document AI extraction")
            self.assertEqual((step["status"], step["detail"]), ("done", "Invoice Parser read 6 line item(s), total $8,450.00"))
            self.assertEqual(claim["document"]["extractedBy"], "Document AI Invoice Parser + Gemini")
            self.assertEqual(claim["document"]["documentAi"]["invoiceId"], "APC-26-1014-07")
            prompt = gemini.requests[-1]["body"]["contents"][0]["parts"][0]["text"]
            self.assertIn("document_ai_extraction", prompt)
            self.assertIn("Rear suspension assembly: replace", prompt)
            self.assertEqual(claim["settlement"]["net"], 750.0)
        finally:
            gemini.close()
            env.close()

    def test_document_ai_failure_does_not_stop_gemini(self):
        gemini = FakeGemini()
        self.fake_docai.process_responses.append((500, {"error": {"code": 500, "message": "boom", "status": "INTERNAL"}}))
        env = TempService(backend="api-key", api_key="k", client_factory=api_key_client(gemini),
                          docai=self.fake_docai.service())
        try:
            gemini.reply_json(recorded_assessment("Inflated repair bill"))
            claim = env.service.analyze(preset_payload("inflated-bill"))
            step = next(s for s in claim["analysis"]["steps"] if s["name"] == "Document AI extraction")
            self.assertEqual(step["status"], "failed")
            self.assertEqual(claim["analysis"]["engine"], "gemini")
            self.assertEqual(claim["document"]["extractedBy"], "Gemini")
            self.assertNotIn("document_ai_extraction", gemini.requests[-1]["body"]["contents"][0]["parts"][0]["text"])
        finally:
            gemini.close()
            env.close()

    def test_document_ai_without_gemini_holds_lines_for_review(self):
        env = TempService(docai=self.fake_docai.service())
        try:
            payload = preset_payload("inflated-bill", with_files=False)
            payload["photo"] = file_upload("samples/photos/shattered-windshield.jpg")  # not the recorded pair
            payload["document"] = file_upload("samples/documents/collision-invoice.png", "image/png")
            claim = env.service.analyze(payload)
            self.assertEqual(claim["analysis"]["engine"], "demo-generic")
            self.assertEqual(claim["document"]["extractedBy"], "Document AI Invoice Parser")
            self.assertEqual(len(claim["lineItems"]), 6)
            self.assertTrue(all(i["recommendation"] == "REVIEW" and i["photoEvidence"] == "NOT_CHECKED"
                                for i in claim["lineItems"]))
            self.assertEqual(claim["settlement"]["held"], 8450.0)
            self.assertEqual(claim["status"], "ADJUSTER_REVIEW")
        finally:
            env.close()


if __name__ == "__main__":
    unittest.main()
