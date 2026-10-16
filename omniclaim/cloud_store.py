"""Optional: durable claim storage in Firestore, with files in Cloud Storage.

Enabled with CLAIMS_STORE=firestore and CLAIM_FILES_BUCKET=<bucket>. It has the
same interface as the local ClaimStore, so the rest of the app does not change:

* claims        -> Firestore collection FIRESTORE_COLLECTION (one document per claim)
* claim numbers -> reserved by creating <collection>_ids/CLM-<n>; Firestore allows only
                   one creator per document, so instances never hand out the same number
* sample data   -> seeded once; a lock document in <collection>_meta stops two instances
                   seeding together
* photos, bills -> Cloud Storage objects <collection>/<CLM-id>-<kind>.<ext>

Data survives redeploys, and the service can run more than one instance.
"""

import logging
import re
import threading
import time

from google.api_core import exceptions as api_exceptions
from google.cloud import firestore, storage

log = logging.getLogger("omniclaim.store")

_ID = re.compile(r"^CLM-(\d{4,6})$")
_SAFE_NAME = re.compile(r"^CLM-\d{4,6}-(photo|document)\.(jpg|pdf)$")
CONTENT_TYPES = {"jpg": "image/jpeg", "pdf": "application/pdf"}
SEED_WAIT_SECONDS = 90


class CloudClaimStore:
    backend = "firestore"

    def __init__(self, project: str | None, database: str, collection: str, bucket: str,
                 firestore_client=None, storage_client=None):
        if not bucket:
            raise ValueError("CLAIM_FILES_BUCKET must be set when CLAIMS_STORE=firestore.")
        self._db = firestore_client or firestore.Client(project=project or None, database=database)
        self._collection = collection
        self._claims = self._db.collection(collection)
        self._meta = self._db.collection(f"{collection}_meta")
        self._ids = self._db.collection(f"{collection}_ids")
        self._storage = storage_client or storage.Client(project=project or None)
        self._bucket_name = bucket
        self._bucket = self._storage.bucket(bucket)
        self._prefix = f"{collection}/"
        self._floor = None
        self._floor_lock = threading.Lock()
        self.description = (f"Firestore database {database}, collection '{collection}'; "
                            f"files in gs://{bucket}/{self._prefix}")

    # -- lifecycle -----------------------------------------------------------

    def check(self) -> None:
        """Fail fast with a clear error if Firestore or the bucket is not reachable."""
        list(self._claims.limit(1).stream())
        list(self._storage.list_blobs(self._bucket_name, prefix=self._prefix, max_results=1))

    def load_or_seed(self, seeder) -> None:
        if list(self._claims.limit(1).stream()):
            return
        lock = self._meta.document("seed")
        try:
            lock.create({"startedAt": firestore.SERVER_TIMESTAMP})
        except api_exceptions.AlreadyExists:
            log.info("Another instance is seeding the sample claims; waiting for it.")
            deadline = time.monotonic() + SEED_WAIT_SECONDS
            while time.monotonic() < deadline:
                if (lock.get().to_dict() or {}).get("finishedAt"):
                    return
                time.sleep(1)
            log.warning("Sample seeding by another instance did not finish within %s s.", SEED_WAIT_SECONDS)
            return
        try:
            seeder(self)
        except Exception:
            lock.delete()  # let the next start try again
            raise
        lock.set({"finishedAt": firestore.SERVER_TIMESTAMP}, merge=True)

    def reset(self, seeder) -> None:
        for collection in (self._claims, self._meta, self._ids):
            refs = list(collection.list_documents())
            for start in range(0, len(refs), 400):
                batch = self._db.batch()
                for ref in refs[start:start + 400]:
                    batch.delete(ref)
                batch.commit()
        for blob in self._storage.list_blobs(self._bucket_name, prefix=self._prefix):
            blob.delete()
        with self._floor_lock:
            self._floor = None
        self.load_or_seed(seeder)

    # -- claims --------------------------------------------------------------

    def all(self) -> list[dict]:
        claims = [snapshot.to_dict() for snapshot in self._claims.stream()]
        return sorted(claims, key=lambda c: c.get("createdAt", ""), reverse=True)

    def get(self, claim_id: str) -> dict | None:
        snapshot = self._claims.document((claim_id or "").upper()).get()
        return snapshot.to_dict() if snapshot.exists else None

    def put(self, claim: dict) -> None:
        self._claims.document(claim["id"]).set(claim)

    def next_id(self) -> str:
        """Reserve the next free claim number, safely across threads and Cloud Run instances.

        A number is reserved by *creating* the document <collection>_ids/CLM-<n>. Firestore lets
        only one caller create a given document, so a racing caller gets AlreadyExists at once
        and simply tries the next number: no shared counter, no lock contention.
        """
        with self._floor_lock:
            if self._floor is None:
                numbers = [int(m.group(1)) for ref in self._claims.list_documents() if (m := _ID.match(ref.id))]
                self._floor = max(numbers, default=9000)
            number = self._floor + 1
        for _ in range(1000):
            try:
                self._ids.document(f"CLM-{number}").create({"reservedAt": firestore.SERVER_TIMESTAMP})
            except api_exceptions.AlreadyExists:
                number += 1
                continue
            with self._floor_lock:
                self._floor = max(self._floor, number)
            return f"CLM-{number}"
        raise RuntimeError("Could not reserve a claim number.")

    def photo_index(self) -> list[dict]:
        return [{"claimId": c["id"], "claimantName": c["claimantName"], "createdAt": c.get("createdAt"),
                 "dhash": c["photo"]["dhash"]}
                for c in self.all() if (c.get("photo") or {}).get("dhash")]

    def document_index(self) -> list[dict]:
        return [{"claimId": c["id"], "claimantName": c["claimantName"], "createdAt": c.get("createdAt"),
                 "sha256": c["document"]["sha256"]}
                for c in self.all() if (c.get("document") or {}).get("sha256")]

    def related_counts(self, claim: dict) -> dict:
        name = claim["claimantName"].strip().lower()
        vendor = ((claim.get("document") or {}).get("vendor") or "").strip().lower()
        others = [c for c in self.all() if c["id"] != claim["id"]]
        return {
            "sameClaimant": sum(1 for c in others if c["claimantName"].strip().lower() == name),
            "sameVendor": sum(1 for c in others if vendor and
                              ((c.get("document") or {}).get("vendor") or "").strip().lower() == vendor),
            "photoMatches": len((claim.get("photo") or {}).get("matches") or []),
        }

    # -- files ---------------------------------------------------------------

    def save_file(self, claim_id: str, kind: str, data: bytes, extension: str) -> str:
        name = f"{claim_id}-{kind}.{extension}"
        blob = self._bucket.blob(self._prefix + name)
        blob.upload_from_string(data, content_type=CONTENT_TYPES.get(extension, "application/octet-stream"))
        return name

    def read_file(self, name: str) -> bytes | None:
        if not name or not _SAFE_NAME.match(name):
            return None
        try:
            return self._bucket.blob(self._prefix + name).download_as_bytes()
        except api_exceptions.NotFound:
            return None
