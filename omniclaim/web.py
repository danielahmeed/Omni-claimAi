"""HTTP API and static file server, built on the Python standard library.

Only an explicit allowlist of files is served (index.html, app.js, styles.css
and the samples/ folder). Source code, data/ and configuration are never
reachable over HTTP.
"""

import json
import logging
import re
import threading
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler
from urllib.parse import unquote, urlparse

from .config import (BASE_DIR, MAX_UPLOAD_MB, ON_CLOUD_RUN, RATE_LIMIT_ANALYZE, RATE_LIMIT_CHAT, RATE_LIMIT_TEST,
                     SAMPLES_DIR)
from .service import ClaimService, NotFound, SubmissionError

log = logging.getLogger("omniclaim.http")

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}
SAMPLE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                ".json": "application/json; charset=utf-8", ".pdf": "application/pdf"}
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'self'; "
    "form-action 'self'; frame-ancestors 'none'"
)
UPLOAD_BODY_LIMIT = int(MAX_UPLOAD_MB * 1024 * 1024 * 2 * 1.4) + 256 * 1024  # two base64 files + form
SMALL_BODY_LIMIT = 256 * 1024
CLAIM_ID = r"(CLM-\d{4,6})"

ROUTES = [
    ("GET", re.compile(r"^/api/health$"), "health"),
    ("GET", re.compile(r"^/api/status$"), "status"),
    ("GET", re.compile(r"^/api/config$"), "get_config"),
    ("POST", re.compile(r"^/api/config$"), "update_config"),
    ("POST", re.compile(r"^/api/config/test$"), "test_config"),
    ("GET", re.compile(r"^/api/claims$"), "list_claims"),
    ("POST", re.compile(r"^/api/claims(?:/analyze)?$"), "create_claim"),
    ("GET", re.compile(rf"^/api/claims/{CLAIM_ID}$", re.I), "get_claim"),
    ("GET", re.compile(rf"^/api/claims/{CLAIM_ID}/(photo|document)$", re.I), "claim_file"),
    ("POST", re.compile(rf"^/api/claims/{CLAIM_ID}/(?:decision|action)$", re.I), "decide"),
    ("POST", re.compile(rf"^/api/claims/{CLAIM_ID}/copilot$", re.I), "copilot"),
    ("POST", re.compile(r"^/api/admin/reset$"), "reset"),
]


class HttpError(Exception):
    def __init__(self, status: int, message: str, field: str | None = None):
        super().__init__(message)
        self.status, self.message, self.field = status, message, field


class RateLimiter:
    """Sliding-window limit per client and action (in memory, per instance)."""

    def __init__(self, window_s: int = 600):
        self.window = window_s
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int) -> bool:
        if limit <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True


def make_handler(service: ClaimService):
    limiter = RateLimiter()

    class Handler(BaseHTTPRequestHandler):
        server_version = "OmniClaim"
        sys_version = ""
        timeout = 120  # seconds; a stalled client cannot hold a thread forever

        # -- plumbing ---------------------------------------------------------

        def log_message(self, fmt, *args):  # Replace the default stderr logging.
            log.debug(fmt, *args)

        def _client(self) -> str:
            forwarded = self.headers.get("X-Forwarded-For", "")
            if ON_CLOUD_RUN and forwarded:
                return forwarded.split(",")[-1].strip()
            return self.client_address[0]

        def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("X-Frame-Options", "DENY")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            self._status = status

        def _json(self, status: int, payload) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8", {"Cache-Control": "no-store"})

        def _drain_body(self) -> None:
            """Read and discard an unread request body before sending an error.

            Closing a connection with unread data makes the OS reset it, and the client then
            sees a network error instead of our JSON message.
            """
            if self._body_read or self.command not in ("POST", "PUT", "PATCH", "DELETE"):
                return
            self._body_read = True
            try:
                remaining = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return
            if remaining <= 0 or remaining > UPLOAD_BODY_LIMIT:
                return
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)

        def _read_json(self, limit: int) -> dict:
            if "application/json" not in (self.headers.get("Content-Type") or ""):
                raise HttpError(415, "Send the request body as application/json.")
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise HttpError(400, "Invalid Content-Length header.") from None
            if length > limit:
                self._body_read = True  # refuse without reading: the point is not to accept it
                raise HttpError(413, f"Request too large. Files may be at most {MAX_UPLOAD_MB} MB each.")
            self._body_read = True
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise HttpError(400, "Request body must be valid JSON.") from None
            if not isinstance(data, dict):
                raise HttpError(400, "Request body must be a JSON object.")
            return data

        def _limit(self, action: str, limit: int) -> None:
            if not limiter.allow(f"{action}:{self._client()}", limit):
                raise HttpError(429, "Too many requests. Please wait a few minutes and try again.")

        def _dispatch(self, method: str):
            started = time.perf_counter()
            self._status = 500
            self._body_read = False
            path = urlparse(self.path).path
            try:
                if method in ("GET", "HEAD") and (path in STATIC_FILES or path.startswith("/samples/")):
                    self._static(path)
                    return
                allowed_methods = []
                for route_method, pattern, name in ROUTES:
                    match = pattern.match(path)
                    if not match:
                        continue
                    if route_method != ("GET" if method == "HEAD" else method):
                        allowed_methods.append(route_method)
                        continue
                    getattr(self, "api_" + name)(*[g.upper() if g.upper().startswith("CLM-") else g.lower()
                                                   for g in match.groups()])
                    return
                if allowed_methods:
                    raise HttpError(405, "Method not allowed.")
                raise HttpError(404, "Not found.")
            except HttpError as exc:
                self._drain_body()
                self._json(exc.status, {"error": exc.message, **({"field": exc.field} if exc.field else {})})
            except SubmissionError as exc:
                self._json(400, {"error": str(exc), **({"field": exc.field} if exc.field else {})})
            except NotFound as exc:
                self._drain_body()
                self._json(404, {"error": str(exc)})
            except PermissionError as exc:
                self._drain_body()
                self._json(403, {"error": str(exc)})
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            except Exception:
                log.exception("Unhandled error for %s %s", method, path)
                self._drain_body()
                self._json(500, {"error": "Something went wrong on the server. Check the server log for details."})
            finally:
                log.info("%s %s %s %d ms", method, path, self._status, round((time.perf_counter() - started) * 1000))

        def do_GET(self):
            self._dispatch("GET")

        def do_HEAD(self):
            self._dispatch("HEAD")

        def do_POST(self):
            self._dispatch("POST")

        def do_PUT(self):
            self._dispatch("PUT")

        def do_DELETE(self):
            self._dispatch("DELETE")

        # -- static files -----------------------------------------------------

        def _static(self, path: str) -> None:
            if path in STATIC_FILES:
                name, content_type = STATIC_FILES[path]
                file_path = BASE_DIR / name
                extra = {"Cache-Control": "no-cache"}
                if name == "index.html":
                    extra["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
            else:
                relative = unquote(path[len("/samples/"):])
                file_path = (SAMPLES_DIR / relative).resolve()
                content_type = SAMPLE_TYPES.get(file_path.suffix.lower())
                if not content_type or SAMPLES_DIR.resolve() not in file_path.parents:
                    raise HttpError(404, "Not found.")
                extra = {"Cache-Control": "public, max-age=3600"}
            try:
                body = file_path.read_bytes()
            except OSError:
                raise HttpError(404, "Not found.") from None
            self._send(200, body, content_type, extra)

        # -- API ----------------------------------------------------------------

        def api_health(self):
            self._json(200, {"status": "ok"})

        def api_status(self):
            self._json(200, service.status())

        def api_get_config(self):
            self._json(200, service.config_view())

        def api_update_config(self):
            payload = self._read_json(SMALL_BODY_LIMIT)
            self._json(200, service.update_config(payload))

        def api_test_config(self):
            self._read_json(SMALL_BODY_LIMIT)
            self._limit("test", RATE_LIMIT_TEST)
            self._json(200, service.gemini.test_connection())

        def api_list_claims(self):
            self._json(200, service.list_claims())

        def api_create_claim(self):
            payload = self._read_json(UPLOAD_BODY_LIMIT)
            self._limit("analyze", RATE_LIMIT_ANALYZE)
            self._json(201, service.analyze(payload))

        def api_get_claim(self, claim_id):
            self._json(200, service.get_claim(claim_id))

        def api_claim_file(self, claim_id, kind):
            data, mime, name = service.claim_file(claim_id, kind)
            safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:100]
            self._send(200, data, mime, {"Cache-Control": "private, max-age=300",
                                         "Content-Disposition": f'inline; filename="{safe_name}"'})

        def api_decide(self, claim_id):
            payload = self._read_json(SMALL_BODY_LIMIT)
            self._json(200, service.decide(claim_id, payload))

        def api_copilot(self, claim_id):
            payload = self._read_json(SMALL_BODY_LIMIT)
            self._limit("chat", RATE_LIMIT_CHAT)
            self._json(200, service.copilot(claim_id, payload))

        def api_reset(self):
            self._read_json(SMALL_BODY_LIMIT)
            service.reset()
            self._json(200, {"ok": True, "claims": len(service.list_claims())})

    return Handler
