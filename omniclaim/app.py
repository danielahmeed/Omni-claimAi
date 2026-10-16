"""Wiring: build the service objects and the HTTP server."""

import logging
from http.server import ThreadingHTTPServer
from pathlib import Path

from .ai import GeminiService
from .config import (ALLOW_SETTINGS_UI, CLAIM_FILES_BUCKET, CLAIMS_STORE, FIRESTORE_COLLECTION, FIRESTORE_DATABASE,
                     GOOGLE_CLOUD_PROJECT, RUNTIME_DIR, SETTINGS_FILE, Settings)
from .docai import DocumentAIService
from .service import ClaimService
from .store import ClaimStore
from .web import make_handler

log = logging.getLogger("omniclaim")


def create_store(runtime_dir: Path, backend: str = CLAIMS_STORE, cloud_store_factory=None):
    """Return (store, status). Falls back to local storage if Firestore is not usable."""
    if backend == "firestore":
        try:
            if cloud_store_factory is None:
                from .cloud_store import CloudClaimStore

                def cloud_store_factory():
                    return CloudClaimStore(GOOGLE_CLOUD_PROJECT, FIRESTORE_DATABASE, FIRESTORE_COLLECTION,
                                           CLAIM_FILES_BUCKET)
            store = cloud_store_factory()
            store.check()
            return store, {"state": "active", "detail": store.description}
        except Exception as exc:
            log.error("Firestore storage is not available, using local storage instead: %s", exc)
            store = ClaimStore(runtime_dir)
            return store, {"state": "error",
                           "detail": f"Firestore is not available ({type(exc).__name__}: {str(exc)[:250]}). "
                                     f"Using a local JSON file instead."}
    store = ClaimStore(runtime_dir)
    return store, {"state": "local", "detail": "Local JSON file on the server (data/runtime). "
                                               "Set CLAIMS_STORE=firestore for durable storage."}


def create_service(runtime_dir: Path = RUNTIME_DIR, settings: Settings | None = None, client_factory=None,
                   docai: DocumentAIService | None = None, store_backend: str = CLAIMS_STORE,
                   cloud_store_factory=None) -> ClaimService:
    runtime_dir = Path(runtime_dir)
    if settings is None:
        settings_file = SETTINGS_FILE if runtime_dir == RUNTIME_DIR else runtime_dir / "settings.json"
        settings = Settings(settings_file=settings_file, writable=ALLOW_SETTINGS_UI)
    gemini = GeminiService(settings, client_factory=client_factory)
    store, store_status = create_store(runtime_dir, store_backend, cloud_store_factory)
    return ClaimService(store, gemini, settings, docai=docai or DocumentAIService(), store_status=store_status)


def create_server(service: ClaimService, host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(service))
    server.daemon_threads = True
    return server
