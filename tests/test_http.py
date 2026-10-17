"""HTTP-level tests: routing, static allowlist, security headers and limits."""

import http.client
import json
import threading
import unittest
from unittest import mock

from omniclaim import web
from omniclaim.app import create_server
from tests.helpers import TempService, preset_payload


class HttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = TempService(writable=False)
        cls.server = create_server(cls.env.service, "127.0.0.1", 0)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.env.close()

    def request(self, method, path, body=None, content_type="application/json", headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        data = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
        all_headers = dict(headers or {})
        if data is not None:
            all_headers.setdefault("Content-Type", content_type)
        conn.request(method, path, body=data, headers=all_headers)
        response = conn.getresponse()
        payload = response.read()
        conn.close()
        return response, payload

    def json(self, method, path, body=None):
        response, payload = self.request(method, path, body)
        return response.status, json.loads(payload)

    # -- static files ------------------------------------------------------------

    def test_app_files_are_served_with_security_headers(self):
        response, body = self.request("GET", "/")
        self.assertEqual(response.status, 200)
        self.assertIn(b"<title>", body)
        self.assertIn("script-src 'self'", response.getheader("Content-Security-Policy"))
        self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")
        for path in ("/app.js", "/styles.css", "/samples/presets.json", "/samples/photos/front-end-damage.jpg"):
            self.assertEqual(self.request("GET", path)[0].status, 200, path)

    def test_private_files_are_never_served(self):
        for path in ("/server.py", "/omniclaim/config.py", "/data/policies.json", "/data/runtime/claims.json",
                     "/data/runtime/settings.json", "/.env", "/.git/config", "/samples/../server.py",
                     "/samples/%2e%2e/server.py", "/samples/", "/requirements.txt", "/Dockerfile"):
            response, _ = self.request("GET", path)
            self.assertEqual(response.status, 404, path)

    # -- API -----------------------------------------------------------------------

    def test_claims_endpoints(self):
        status, claims = self.json("GET", "/api/claims")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(claims), 6)
        status, claim = self.json("GET", "/api/claims/clm-9042")
        self.assertEqual((status, claim["id"]), (200, "CLM-9042"))
        self.assertIn("related", claim)
        status, error = self.json("GET", "/api/claims/CLM-0001")
        self.assertEqual(status, 404)
        self.assertIn("error", error)

    def test_create_claim_and_decide(self):
        status, claim = self.json("POST", "/api/claims", preset_payload("storm-windshield"))
        self.assertEqual(status, 201)
        self.assertEqual(claim["status"], "AUTO_APPROVED")
        response, body = self.request("GET", f"/api/claims/{claim['id']}/photo")
        self.assertEqual((response.status, response.getheader("Content-Type")), (200, "image/jpeg"))
        status, updated = self.json("POST", f"/api/claims/{claim['id']}/decision", {"action": "REFER_SIU"})
        self.assertEqual((status, updated["status"]), (200, "SIU_ESCALATED"))

    def test_validation_errors_name_the_field(self):
        payload = preset_payload("burst-pipe", with_files=False)
        payload["claimedAmount"] = "lots"
        status, error = self.json("POST", "/api/claims", payload)
        self.assertEqual((status, error.get("field")), (400, "claimedAmount"))

    def test_only_json_posts_are_accepted(self):
        response, _ = self.request("POST", "/api/claims/CLM-9042/decision", b"action=DENY",
                                   content_type="application/x-www-form-urlencoded")
        self.assertEqual(response.status, 415)
        response, _ = self.request("POST", "/api/claims", b"{not json")
        self.assertEqual(response.status, 400)

    def test_oversized_body_is_rejected(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.putrequest("POST", "/api/claims/CLM-9042/copilot")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(10 * 1024 * 1024))
        conn.endheaders()
        response = conn.getresponse()
        self.assertEqual(response.status, 413)
        conn.close()

    def test_wrong_method(self):
        response, _ = self.request("PUT", "/api/claims")
        self.assertEqual(response.status, 405)
        response, _ = self.request("GET", "/api/nothing-here")
        self.assertEqual(response.status, 404)

    def test_config_never_exposes_the_key_and_is_read_only_here(self):
        status, config = self.json("GET", "/api/config")
        self.assertEqual(status, 200)
        self.assertFalse(config["writable"])
        self.assertNotIn("apiKey", config)
        status, error = self.json("POST", "/api/config", {"apiKey": "AIzaSyNOPE"})
        self.assertEqual(status, 403)

    def test_status_reports_integrations_honestly(self):
        status, info = self.json("GET", "/api/status")
        self.assertEqual(status, 200)
        states = {i["id"]: i["state"] for i in info["integrations"]}
        self.assertEqual(states["gemini"], "not_configured")
        self.assertEqual(states["document-ai"], "not_configured")
        self.assertEqual(states["storage"], "local")
        self.assertEqual(states["photo-checks"], "active")
        self.assertEqual(states["vertex-search"], "planned")

    def test_connection_test_without_configuration(self):
        status, result = self.json("POST", "/api/config/test", {})
        self.assertEqual(status, 200)
        self.assertFalse(result["ok"])

    def test_rate_limit(self):
        with mock.patch.object(web, "RATE_LIMIT_TEST", 2):
            codes = [self.request("POST", "/api/config/test", {}, headers={"X-Test": str(i)})[0].status for i in range(3)]
        self.assertEqual(codes[-1], 429)

    def test_reset_is_forbidden_when_disabled(self):
        with mock.patch("omniclaim.service.ALLOW_DATA_RESET", False):
            status, _ = self.json("POST", "/api/admin/reset", {})
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
