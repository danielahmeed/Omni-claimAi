"""Shared test helpers: temporary service, sample payloads and a fake Gemini endpoint."""

import base64
import json
import os
import shutil
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("GEMINI_BACKEND", "none")  # Tests never call the real Gemini.

from omniclaim.app import create_service  # noqa: E402
from omniclaim.config import BASE_DIR, Settings  # noqa: E402
from omniclaim.docai import DocumentAIService  # noqa: E402

PRESETS = json.loads((BASE_DIR / "samples" / "presets.json").read_text(encoding="utf-8"))["presets"]


def file_upload(relative_path: str, mime: str = "image/jpeg") -> dict:
    path = BASE_DIR / relative_path.lstrip("/")
    return {"name": path.name, "type": mime, "data": base64.b64encode(path.read_bytes()).decode()}


def preset_payload(preset_id: str, with_files: bool = True) -> dict:
    preset = next(p for p in PRESETS if p["id"] == preset_id)
    payload = dict(preset["form"])
    if with_files:
        payload["photo"] = file_upload(preset["photo"])
        payload["document"] = file_upload(preset["document"], "image/png")
    return payload


class TempService:
    """A ClaimService on a throw-away data folder."""

    def __init__(self, backend: str = "none", client_factory=None, writable: bool = True, docai=None,
                 store_backend: str = "local", cloud_store_factory=None, **settings):
        self.dir = Path(tempfile.mkdtemp(prefix="omniclaim-test-"))
        settings_file = self.dir / "settings.json"
        # Pin every integration so a developer's own environment variables cannot make tests call Google Cloud.
        settings_file.write_text(json.dumps({"backend": backend, **settings}), encoding="utf-8")
        self.settings = Settings(settings_file=settings_file, writable=True)
        self.settings.writable = writable
        self.service = create_service(runtime_dir=self.dir, settings=self.settings, client_factory=client_factory,
                                      docai=docai or DocumentAIService(processor=""), store_backend=store_backend,
                                      cloud_store_factory=cloud_store_factory)
        self.service.initialize()

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class FakeGemini:
    """A tiny HTTP server that answers like the Gemini generateContent endpoint.

    Every request is recorded so tests can assert on what the SDK sent.
    """

    def __init__(self):
        self.requests: list[dict] = []
        self.responses: list[tuple[int, dict]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                fake.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
                status, payload = fake.responses.pop(0) if fake.responses else (500, {"error": {"message": "no response queued"}})
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def reply_text(self, text: str):
        self.responses.append((200, {
            "candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 10, "totalTokenCount": 20},
        }))

    def reply_json(self, payload: dict):
        self.reply_text(json.dumps(payload))

    def reply_error(self, status: int, message: str, status_text: str = "INVALID_ARGUMENT"):
        self.responses.append((status, {"error": {"code": status, "message": message, "status": status_text}}))

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def recorded_assessment(name: str) -> dict:
    data = json.loads((BASE_DIR / "data" / "demo_mode" / "recorded_analyses.json").read_text(encoding="utf-8"))
    return next(a["assessment"] for a in data["analyses"] if a["name"] == name)
