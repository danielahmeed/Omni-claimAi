"""Firestore + Cloud Storage claim store.

The integration tests run against the official Firestore emulator and a Cloud
Storage emulator (see docs/TESTING.md). They are skipped unless
FIRESTORE_EMULATOR_HOST and STORAGE_EMULATOR_HOST are set. The fallback test
always runs.
"""

import os
import threading
import time
import unittest
import uuid
import warnings

from tests.helpers import TempService, preset_payload

warnings.filterwarnings("ignore", category=FutureWarning)

EMULATORS = bool(os.environ.get("FIRESTORE_EMULATOR_HOST") and os.environ.get("STORAGE_EMULATOR_HOST"))
BUCKET = os.environ.get("OMNICLAIM_TEST_BUCKET", "omniclaim-test-files")
PROJECT = "demo-omniclaim"


def make_store(collection: str | None = None):
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import firestore, storage

    from omniclaim.cloud_store import CloudClaimStore

    return CloudClaimStore(PROJECT, "(default)", collection or f"claims_test_{uuid.uuid4().hex[:8]}", BUCKET,
                           firestore_client=firestore.Client(project=PROJECT),
                           storage_client=storage.Client(project=PROJECT, credentials=AnonymousCredentials()))


class FallbackTest(unittest.TestCase):
    def test_unusable_firestore_falls_back_to_local_storage(self):
        def broken_factory():
            raise RuntimeError("403 Firestore API has not been used in project demo")

        env = TempService(store_backend="firestore", cloud_store_factory=broken_factory)
        try:
            self.assertEqual(env.service.store.backend, "local")
            self.assertEqual(len(env.service.list_claims()), 6)
            storage = next(i for i in env.service.status()["integrations"] if i["id"] == "storage")
            self.assertEqual(storage["state"], "error")
            self.assertIn("Firestore API has not been used", storage["detail"])
        finally:
            env.close()


@unittest.skipUnless(EMULATORS, "Firestore/Cloud Storage emulators not running (see docs/TESTING.md)")
class FirestoreStoreTest(unittest.TestCase):
    def test_full_pipeline_on_firestore_and_cloud_storage(self):
        store = make_store()
        env = TempService(store_backend="firestore", cloud_store_factory=lambda: store)
        try:
            service = env.service
            claims = {c["id"]: c for c in service.list_claims()}
            self.assertEqual(len(claims), 6)
            self.assertEqual(claims["CLM-9104"]["status"], "SIU_ESCALATED")
            self.assertEqual([m["claimId"] for m in claims["CLM-9104"]["photo"]["matches"]], ["CLM-8977"])
            storage = next(i for i in service.status()["integrations"] if i["id"] == "storage")
            self.assertEqual(storage["state"], "active")

            claim = service.analyze(preset_payload("reused-photo"))
            self.assertEqual(claim["id"], "CLM-9232")
            self.assertEqual(sorted(m["claimId"] for m in claim["photo"]["matches"]), ["CLM-8977", "CLM-9104"])
            photo, mime, _ = service.claim_file(claim["id"], "photo")
            self.assertEqual(mime, "image/jpeg")
            self.assertTrue(photo.startswith(b"\xff\xd8"))
            document, _, _ = service.claim_file(claim["id"], "document")
            self.assertTrue(document.startswith(b"\xff\xd8"))

            service.decide(claim["id"], {"action": "DENY"})
            reopened = make_store(store._collection)  # a second instance sees the same data
            self.assertEqual(reopened.get(claim["id"])["status"], "DENIED")
            self.assertEqual(reopened.next_id(), "CLM-9233")
            self.assertIsNone(reopened.read_file("../../etc/passwd"))
        finally:
            env.close()

    def test_claim_numbers_are_unique_across_threads_and_instances(self):
        collection = f"claims_test_{uuid.uuid4().hex[:8]}"
        stores = [make_store(collection), make_store(collection)]
        ids, lock = [], threading.Lock()

        def take(store):
            for _ in range(5):
                claim_id = store.next_id()
                with lock:
                    ids.append(claim_id)

        threads = [threading.Thread(target=take, args=(stores[i % 2],)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(ids), 20)
        self.assertEqual(len(set(ids)), 20, "every claim number must be unique")

    def test_only_one_instance_seeds(self):
        collection = f"claims_test_{uuid.uuid4().hex[:8]}"
        calls = []

        def seeder(store):
            calls.append(1)
            time.sleep(1.0)
            store.put({"id": "CLM-9001", "claimantName": "Seed", "createdAt": "2026-01-01T00:00:00+00:00"})

        first, second = make_store(collection), make_store(collection)
        threads = [threading.Thread(target=s.load_or_seed, args=(seeder,)) for s in (first, second)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(calls), 1)
        self.assertEqual([c["id"] for c in first.all()], ["CLM-9001"])

    def test_reset_restores_the_samples(self):
        store = make_store()
        env = TempService(store_backend="firestore", cloud_store_factory=lambda: store)
        try:
            env.service.analyze(preset_payload("burst-pipe"))
            self.assertEqual(len(env.service.list_claims()), 7)
            from unittest import mock

            from omniclaim import service as service_module
            with mock.patch.object(service_module, "ALLOW_DATA_RESET", True):
                env.service.reset()
            self.assertEqual(len(env.service.list_claims()), 6)
            self.assertEqual(env.service.store.next_id(), "CLM-9232")
        finally:
            env.close()


if __name__ == "__main__":
    unittest.main()
