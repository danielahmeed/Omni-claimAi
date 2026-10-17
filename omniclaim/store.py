"""Claim storage: a JSON file plus a folder of photos and documents.

The live data lives in data/runtime/ (git-ignored). On first start it is
built from the sample claims in data/seed/. Deleting data/runtime/ (or
POST /api/admin/reset when allowed) restores the samples.

Writes are atomic (write to a temp file, then rename) and guarded by a lock,
so the threaded HTTP server can serve several requests at once.

Note for Cloud Run: the container filesystem is per-instance and is reset on
every deploy or restart. Deploy with --max-instances=1 when using this store,
or set CLAIMS_STORE=firestore to use omniclaim/cloud_store.py instead.
"""

import copy
import json
import os
import re
import shutil
import threading
from pathlib import Path

from .config import RUNTIME_DIR

_ID = re.compile(r"^CLM-(\d{4,6})$")


class ClaimStore:
    backend = "local"

    def __init__(self, root: Path = RUNTIME_DIR):
        self.root = Path(root)
        self.claims_file = self.root / "claims.json"
        self.files_dir = self.root / "files"
        self._lock = threading.RLock()
        self._claims: dict[str, dict] = {}
        self._last_reserved = 0
        self.description = f"JSON file on the server ({self.root})."

    def check(self) -> None:
        """Nothing to verify for local storage."""

    # -- lifecycle -----------------------------------------------------------

    def load_or_seed(self, seeder) -> None:
        """Load runtime data, or build it with `seeder(store)` the first time."""
        with self._lock:
            if self.claims_file.exists():
                try:
                    data = json.loads(self.claims_file.read_text(encoding="utf-8"))
                    self._claims = {c["id"]: c for c in data}
                    return
                except (OSError, ValueError, KeyError):
                    pass  # Corrupt runtime file: rebuild from the samples.
            self._claims = {}
            self.files_dir.mkdir(parents=True, exist_ok=True)
            seeder(self)
            self._persist()

    def reset(self, seeder) -> None:
        with self._lock:
            if self.files_dir.exists():
                shutil.rmtree(self.files_dir)
            if self.claims_file.exists():
                self.claims_file.unlink()
            self._last_reserved = 0
            self.load_or_seed(seeder)

    def _persist(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.claims_file.with_suffix(".json.tmp")
        ordered = sorted(self._claims.values(), key=lambda c: c.get("createdAt", ""), reverse=True)
        tmp.write_text(json.dumps(ordered, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.claims_file)

    # -- claims --------------------------------------------------------------

    def all(self) -> list[dict]:
        with self._lock:
            claims = [copy.deepcopy(c) for c in self._claims.values()]
        return sorted(claims, key=lambda c: c.get("createdAt", ""), reverse=True)

    def get(self, claim_id: str) -> dict | None:
        with self._lock:
            claim = self._claims.get((claim_id or "").upper())
            return copy.deepcopy(claim) if claim else None

    def put(self, claim: dict) -> None:
        with self._lock:
            self._claims[claim["id"]] = copy.deepcopy(claim)
            self._persist()

    def next_id(self) -> str:
        """Reserve the next claim number, so concurrent requests never get the same one."""
        with self._lock:
            numbers = [int(m.group(1)) for cid in self._claims if (m := _ID.match(cid))]
            self._last_reserved = max([self._last_reserved, 9000, *numbers]) + 1
            return f"CLM-{self._last_reserved}"

    def photo_index(self) -> list[dict]:
        with self._lock:
            return [{"claimId": c["id"], "claimantName": c["claimantName"], "createdAt": c.get("createdAt"),
                     "dhash": c["photo"]["dhash"]}
                    for c in self._claims.values() if (c.get("photo") or {}).get("dhash")]

    def document_index(self) -> list[dict]:
        with self._lock:
            return [{"claimId": c["id"], "claimantName": c["claimantName"], "createdAt": c.get("createdAt"),
                     "sha256": c["document"]["sha256"]}
                    for c in self._claims.values() if (c.get("document") or {}).get("sha256")]

    def related_counts(self, claim: dict) -> dict:
        """Simple cross-claim signals inside this workspace."""
        name = claim["claimantName"].strip().lower()
        vendor = ((claim.get("document") or {}).get("vendor") or "").strip().lower()
        with self._lock:
            others = [c for c in self._claims.values() if c["id"] != claim["id"]]
        return {
            "sameClaimant": sum(1 for c in others if c["claimantName"].strip().lower() == name),
            "sameVendor": sum(1 for c in others if vendor and
                              ((c.get("document") or {}).get("vendor") or "").strip().lower() == vendor),
            "photoMatches": len((claim.get("photo") or {}).get("matches") or []),
        }

    # -- files ---------------------------------------------------------------

    def save_file(self, claim_id: str, kind: str, data: bytes, extension: str) -> str:
        name = f"{claim_id}-{kind}.{extension}"
        with self._lock:
            self.files_dir.mkdir(parents=True, exist_ok=True)
            (self.files_dir / name).write_bytes(data)
        return name

    def read_file(self, name: str) -> bytes | None:
        if not name or "/" in name or "\\" in name or name.startswith("."):
            return None
        path = self.files_dir / name
        try:
            return path.read_bytes()
        except OSError:
            return None
