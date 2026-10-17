"""Runtime configuration.

Settings are read from environment variables (the normal way on Cloud Run),
optionally from a local `.env` file, and, when running locally, from
`data/runtime/settings.json`, which the Settings dialog in the UI writes.
The runtime folder is git-ignored and is never served over HTTP.
"""

import json
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

try:  # Optional: load a local .env file for development.
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:  # pragma: no cover - python-dotenv is in requirements.txt
    pass

DATA_DIR = BASE_DIR / "data"
SEED_DIR = DATA_DIR / "seed"
RUNTIME_DIR = Path(os.environ.get("OMNICLAIM_RUNTIME_DIR", str(DATA_DIR / "runtime")))
SAMPLES_DIR = BASE_DIR / "samples"
POLICIES_FILE = DATA_DIR / "policies.json"
BENCHMARK_CSV = DATA_DIR / "benchmarks" / "historical_claims.csv"
RECORDED_DEMO_FILE = DATA_DIR / "demo_mode" / "recorded_analyses.json"
SETTINGS_FILE = RUNTIME_DIR / "settings.json"

ON_CLOUD_RUN = bool(os.environ.get("K_SERVICE"))


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


PORT = _env_int("PORT", 8080)
MAX_UPLOAD_MB = _env_int("MAX_UPLOAD_MB", 10)
RATE_LIMIT_ANALYZE = _env_int("RATE_LIMIT_ANALYZE_PER_10_MIN", 20)
RATE_LIMIT_CHAT = _env_int("RATE_LIMIT_CHAT_PER_10_MIN", 60)
RATE_LIMIT_TEST = _env_int("RATE_LIMIT_TEST_PER_10_MIN", 10)

# Settings can be changed from the UI only where that is safe: locally by
# default, never on a public Cloud Run URL unless explicitly enabled.
ALLOW_SETTINGS_UI = _env_bool("ALLOW_SETTINGS_UI", default=not ON_CLOUD_RUN)
ALLOW_DATA_RESET = _env_bool("ALLOW_DATA_RESET", default=not ON_CLOUD_RUN)

# Optional Google Cloud integrations (off unless configured).
GOOGLE_CLOUD_PROJECT = _env("GOOGLE_CLOUD_PROJECT")
DOCUMENT_AI_PROCESSOR = _env("DOCUMENT_AI_PROCESSOR")     # projects/P/locations/us/processors/ID
DOCUMENT_AI_TIMEOUT_SECONDS = max(10, _env_int("DOCUMENT_AI_TIMEOUT_SECONDS", 60))
BIGQUERY_BENCHMARK_TABLE = _env("BIGQUERY_BENCHMARK_TABLE")
CLAIMS_STORE = (_env("CLAIMS_STORE", "local") or "local").lower()   # "local" or "firestore"
FIRESTORE_DATABASE = _env("FIRESTORE_DATABASE", "(default)") or "(default)"
FIRESTORE_COLLECTION = _env("FIRESTORE_COLLECTION", "claims") or "claims"
CLAIM_FILES_BUCKET = _env("CLAIM_FILES_BUCKET")              # Cloud Storage bucket for photos and bills

# ---------------------------------------------------------------------------
# Decision rules. These are deliberately simple and live in one place so the
# behaviour is easy to explain to an adjuster or a judge.
# ---------------------------------------------------------------------------
AUTO_APPROVE_MAX_RISK = 19      # risk 0-19 may be paid automatically
SIU_MIN_RISK = 80               # risk 80-100 goes to the Special Investigations Unit
DUPLICATE_PHOTO_MAX_DISTANCE = 6  # perceptual-hash bits (out of 64) that may differ
NEW_POLICY_ALERT_DAYS = 14      # losses this soon after policy start are flagged

DEFAULT_MODEL = "gemini-3.8-flash"
SUPPORTED_MODELS = ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
THINKING_LEVELS = ["LOW", "MEDIUM", "HIGH"]
BACKENDS = ["vertex", "api-key", "none"]


@dataclass
class AISettings:
    backend: str          # "vertex" | "api-key" | "none"
    api_key: str
    project: str
    location: str
    model: str
    thinking_level: str
    timeout_s: int

    def fingerprint(self) -> tuple:
        return (self.backend, self.api_key, self.project, self.location, self.model,
                self.thinking_level, self.timeout_s)


def _env_ai_settings() -> AISettings:
    api_key = _env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY")
    project = _env("GOOGLE_CLOUD_PROJECT")
    backend = _env("GEMINI_BACKEND").lower()
    if backend not in BACKENDS:
        backend = "vertex" if project else ("api-key" if api_key else "none")
    return AISettings(
        backend=backend,
        api_key=api_key,
        project=project,
        location=_env("GEMINI_LOCATION", "global") or "global",
        model=_env("GEMINI_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL,
        thinking_level=(_env("GEMINI_THINKING_LEVEL", "LOW") or "LOW").upper(),
        timeout_s=max(10, _env_int("GEMINI_TIMEOUT_SECONDS", 90)),
    )


class Settings:
    """Thread-safe holder for the effective AI settings."""

    EDITABLE = ("backend", "api_key", "project", "location", "model", "thinking_level")

    def __init__(self, settings_file: Path = SETTINGS_FILE, writable: bool = ALLOW_SETTINGS_UI):
        self._lock = threading.Lock()
        self._file = settings_file
        self.writable = writable
        self._overrides = self._load_overrides() if writable else {}

    def _load_overrides(self) -> dict:
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            return {k: v for k, v in data.items() if k in self.EDITABLE and isinstance(v, str)}
        except (OSError, ValueError):
            return {}

    def ai(self) -> AISettings:
        with self._lock:
            values = asdict(_env_ai_settings())
            values.update({k: v for k, v in self._overrides.items() if v or k == "api_key"})
            settings = AISettings(**values)
        if settings.backend not in BACKENDS:
            settings.backend = "none"
        if settings.thinking_level not in THINKING_LEVELS:
            settings.thinking_level = "LOW"
        return settings

    def update(self, changes: dict) -> AISettings:
        """Validate and persist settings edited in the UI (local use only)."""
        if not self.writable:
            raise PermissionError("Settings are managed by environment variables on this server.")
        clean = {}
        for key in self.EDITABLE:
            if key not in changes or changes[key] is None:
                continue
            value = str(changes[key]).strip()
            if key == "backend" and value not in BACKENDS:
                raise ValueError("backend must be one of: " + ", ".join(BACKENDS))
            if key == "thinking_level":
                value = value.upper()
                if value not in THINKING_LEVELS:
                    raise ValueError("thinking_level must be LOW, MEDIUM or HIGH")
            if key == "model" and value and not all(c.isalnum() or c in "-._" for c in value):
                raise ValueError("model name contains invalid characters")
            if key == "location" and value and not all(c.isalnum() or c == "-" for c in value):
                raise ValueError("location contains invalid characters")
            if len(value) > 300:
                raise ValueError(f"{key} is too long")
            clean[key] = value
        with self._lock:
            # An empty api_key in the request means "keep the saved key".
            if "api_key" in clean and not clean["api_key"]:
                clean.pop("api_key")
            self._overrides.update(clean)
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(json.dumps(self._overrides, indent=2), encoding="utf-8")
        return self.ai()

    def clear_api_key(self) -> None:
        if not self.writable:
            raise PermissionError("Settings are managed by environment variables on this server.")
        with self._lock:
            self._overrides["api_key"] = ""
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(json.dumps(self._overrides, indent=2), encoding="utf-8")


def mask_secret(value: str) -> str:
    """Show only that a key exists plus its last four characters."""
    if not value:
        return ""
    return "•" * 8 + value[-4:] if len(value) > 8 else "•" * 8
