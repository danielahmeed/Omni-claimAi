"""Gemini access through the google-genai SDK.

Two connection types are supported:

* "vertex"  - Gemini on Vertex AI (Gemini Enterprise Agent Platform). Uses
              Application Default Credentials: the Cloud Run service account
              in production, `gcloud auth application-default login` locally.
              No API key is needed.
* "api-key" - the Gemini Developer API with a Google AI Studio key, for quick
              local experiments.

The service tracks whether the last real call succeeded, so the UI shows
"Live" only after Gemini has actually answered.
"""

import json
import re
import threading
import time
from datetime import datetime, timezone

from pydantic import ValidationError

from .config import AISettings, Settings
from .prompts import ASSESSMENT_INSTRUCTIONS, COPILOT_INSTRUCTIONS
from .schemas import ClaimAssessment

try:
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types

    SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - google-genai is in requirements.txt
    genai = genai_errors = types = None
    SDK_AVAILABLE = False

try:
    import google.auth.exceptions as auth_errors
except ImportError:  # pragma: no cover
    auth_errors = None

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None


class AIError(Exception):
    """A Gemini call failed. The message is safe to show in the UI."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _supports_thinking_level(model: str) -> bool:
    """Gemini 3 and later accept thinking_level; older models reject it."""
    match = re.match(r"gemini-(\d+)", model or "")
    return bool(match) and int(match.group(1)) >= 3


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def describe_error(exc: Exception, settings: AISettings) -> str:
    """Turn SDK, auth and network errors into an actionable message."""
    if genai_errors and isinstance(exc, genai_errors.APIError):
        code = getattr(exc, "code", None) or 0
        status = str(getattr(exc, "status", "") or "")
        message = str(getattr(exc, "message", "") or exc)
        if code in (401, 403) or status == "PERMISSION_DENIED" or "API key" in message or "API_KEY" in message:
            if settings.backend == "vertex":
                return (f"Vertex AI denied the request: {message} Check that the Vertex AI API is enabled in project "
                        f"'{settings.project}' and that the service account has the Vertex AI User role (roles/aiplatform.user).")
            return f"The Gemini API key was rejected: {message}"
        if code == 404:
            where = f" in location '{settings.location}'" if settings.backend == "vertex" else ""
            return f"Model '{settings.model}' was not found{where}. Check GEMINI_MODEL and GEMINI_LOCATION. ({message})"
        if code == 429:
            return f"Gemini quota or rate limit reached. Wait a minute and try again. ({message})"
        if code >= 500:
            return f"Gemini had a temporary server error ({code}). Try again. ({message})"
        return f"Gemini rejected the request ({code}): {message}"
    if auth_errors and isinstance(exc, auth_errors.DefaultCredentialsError):
        return ("No Google Cloud credentials found. Locally, run `gcloud auth application-default login`; "
                "on Cloud Run, deploy with a service account that has the Vertex AI User role.")
    if auth_errors and isinstance(exc, auth_errors.GoogleAuthError):
        return f"Google Cloud authentication failed: {exc}"
    if httpx and isinstance(exc, httpx.TimeoutException):
        return f"Gemini did not answer within {settings.timeout_s} seconds. Try again."
    if httpx and isinstance(exc, httpx.HTTPError):
        return f"Could not reach Gemini: {exc}"
    if isinstance(exc, (ValidationError, json.JSONDecodeError)):
        return f"Gemini returned an answer in an unexpected format ({type(exc).__name__}). Try again."
    return f"{type(exc).__name__}: {exc}"[:500]


class GeminiService:
    def __init__(self, settings: Settings, client_factory=None):
        self._settings = settings
        self._client_factory = client_factory or self._default_client
        self._lock = threading.Lock()
        self._client = None
        self._client_key = None
        self._status = {"fingerprint": None, "state": None, "lastError": None,
                        "lastCheckedAt": None, "lastLatencyMs": None}

    # -- configuration -----------------------------------------------------

    def settings(self) -> AISettings:
        return self._settings.ai()

    @staticmethod
    def is_configured(settings: AISettings) -> bool:
        if not SDK_AVAILABLE:
            return False
        if settings.backend == "vertex":
            return bool(settings.project)
        if settings.backend == "api-key":
            return bool(settings.api_key)
        return False

    @staticmethod
    def _default_client(settings: AISettings):
        http_options = types.HttpOptions(timeout=settings.timeout_s * 1000)
        if settings.backend == "vertex":
            return genai.Client(enterprise=True, project=settings.project, location=settings.location,
                                http_options=http_options)
        return genai.Client(api_key=settings.api_key, http_options=http_options)

    def _get_client(self, settings: AISettings):
        key = settings.fingerprint()
        with self._lock:
            if self._client is None or self._client_key != key:
                self._client = self._client_factory(settings)
                self._client_key = key
            return self._client

    def status(self) -> dict:
        settings = self.settings()
        configured = self.is_configured(settings)
        with self._lock:
            current = dict(self._status)
        if current["fingerprint"] != settings.fingerprint():
            current = {"state": None, "lastError": None, "lastCheckedAt": None, "lastLatencyMs": None}
        state = current["state"] or ("configured" if configured else "not_configured")
        if not configured:
            state = "not_configured"
        if not SDK_AVAILABLE:
            hint = "The google-genai package is not installed (pip install -r requirements.txt)."
        elif settings.backend == "vertex" and not settings.project:
            hint = "Set GOOGLE_CLOUD_PROJECT to use Gemini on Vertex AI."
        elif settings.backend == "api-key" and not settings.api_key:
            hint = "Set GEMINI_API_KEY to use the Gemini Developer API."
        elif settings.backend == "none":
            hint = "Gemini is switched off. Claims are analyzed in demo mode."
        else:
            hint = ""
        return {
            "state": state,
            "configured": configured,
            "backend": settings.backend,
            "model": settings.model,
            "location": settings.location if settings.backend == "vertex" else None,
            "project": settings.project if settings.backend == "vertex" else None,
            "thinkingLevel": settings.thinking_level if _supports_thinking_level(settings.model) else None,
            "sdkAvailable": SDK_AVAILABLE,
            "lastError": current["lastError"],
            "lastCheckedAt": current["lastCheckedAt"],
            "lastLatencyMs": current["lastLatencyMs"],
            "hint": hint,
        }

    def _record(self, settings: AISettings, ok: bool, latency_ms: int | None = None, error: str | None = None):
        with self._lock:
            self._status = {
                "fingerprint": settings.fingerprint(),
                "state": "live" if ok else "error",
                "lastError": None if ok else error,
                "lastCheckedAt": _now(),
                "lastLatencyMs": latency_ms if ok else None,
            }

    # -- calls ---------------------------------------------------------------

    def _generate(self, settings: AISettings, contents, config):
        if not self.is_configured(settings):
            raise AIError("Gemini is not configured.")
        started = time.perf_counter()
        try:
            client = self._get_client(settings)
            response = client.models.generate_content(model=settings.model, contents=contents, config=config)
            text = response.text
            if not text:
                reason = ""
                if response.prompt_feedback and response.prompt_feedback.block_reason:
                    reason = f" (blocked: {response.prompt_feedback.block_reason})"
                elif response.candidates and response.candidates[0].finish_reason:
                    reason = f" (finish reason: {response.candidates[0].finish_reason})"
                raise AIError(f"Gemini returned an empty answer{reason}.")
        except AIError as exc:
            self._record(settings, ok=False, error=str(exc))
            raise
        except Exception as exc:
            message = describe_error(exc, settings)
            self._record(settings, ok=False, error=message)
            raise AIError(message) from exc
        latency_ms = round((time.perf_counter() - started) * 1000)
        self._record(settings, ok=True, latency_ms=latency_ms)
        return text, latency_ms

    def _config(self, settings: AISettings, **kwargs):
        if _supports_thinking_level(settings.model):
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=settings.thinking_level)
        # No tools are used, so switch off the SDK's automatic function calling.
        kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
        return types.GenerateContentConfig(**kwargs)

    def test_connection(self) -> dict:
        settings = self.settings()
        if not self.is_configured(settings):
            status = self.status()
            return {"ok": False, "message": status["hint"] or "Gemini is not configured.", "model": settings.model}
        try:
            text, latency_ms = self._generate(
                settings, "Reply with exactly: OK",
                self._config(settings, system_instruction="You are a connectivity check. Reply with exactly: OK"))
        except AIError as exc:
            return {"ok": False, "message": str(exc), "model": settings.model}
        return {"ok": True, "message": text.strip()[:200], "latencyMs": latency_ms, "model": settings.model,
                "backend": settings.backend}

    def assess_claim(self, context_text: str, photo_jpeg: bytes | None,
                     document: tuple[bytes, str] | None) -> tuple[ClaimAssessment, int, AISettings]:
        settings = self.settings()
        parts = [types.Part.from_text(text=context_text)]
        if photo_jpeg:
            parts += [types.Part.from_text(text="DAMAGE PHOTO:"),
                      types.Part.from_bytes(data=photo_jpeg, mime_type="image/jpeg")]
        else:
            parts.append(types.Part.from_text(text="DAMAGE PHOTO: none provided."))
        if document:
            data, mime_type = document
            parts += [types.Part.from_text(text="SUPPORTING DOCUMENT:"),
                      types.Part.from_bytes(data=data, mime_type=mime_type)]
        else:
            parts.append(types.Part.from_text(text="SUPPORTING DOCUMENT: none provided."))
        parts.append(types.Part.from_text(text="Return your assessment as JSON in the required format."))
        config = self._config(settings, system_instruction=ASSESSMENT_INSTRUCTIONS,
                              response_mime_type="application/json", response_schema=ClaimAssessment)
        text, latency_ms = self._generate(settings, [types.Content(role="user", parts=parts)], config)
        try:
            assessment = ClaimAssessment.model_validate_json(_strip_code_fence(text))
        except ValidationError as exc:
            message = describe_error(exc, settings)
            self._record(settings, ok=False, error=message)
            raise AIError(message) from exc
        return assessment, latency_ms, settings

    def copilot(self, prompt: str) -> tuple[str, int, AISettings]:
        settings = self.settings()
        text, latency_ms = self._generate(settings, prompt,
                                          self._config(settings, system_instruction=COPILOT_INSTRUCTIONS))
        return text.strip(), latency_ms, settings
