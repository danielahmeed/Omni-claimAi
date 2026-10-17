# Testing

## Unit and integration tests

```bash
python -m unittest discover -s tests
```

There are 90 tests. 86 run anywhere, without network access or credentials, in about 15 seconds. The 4 Firestore tests also need the emulators (below) and are skipped without them.

| File | What it covers |
| --- | --- |
| `test_gemini_integration.py` | The real `google-genai` SDK against a local fake Gemini endpoint, in Vertex AI and API-key mode. Checks the exact request: photo and bill parts, JSON schema, thinking level, no unsupported parameters, auth header. Also checks the handling of 403/404/500 and malformed answers, and that a failed call never auto-approves. |
| `test_docai.py` | The real `google-cloud-documentai` REST client against a local fake Document AI endpoint. Covers the request body, entity parsing (normalized money, printed amounts, quantity × unit price), permission errors, the pipeline with and without Gemini, failure fallback, and `tools/create_document_ai_processor.py`. |
| `test_cloud_store.py` | Firestore + Cloud Storage store against the emulators: the full pipeline, files in the bucket, a second instance seeing the same data, unique claim numbers across threads and instances, single seeding, reset. Also the fallback to local storage when Firestore is unusable (always runs). |
| `test_benchmarks.py` | Local statistics, category inference, the BigQuery query with its parameters, fallback on errors, refusal of unsafe table names. |
| `test_service.py` | Sample data consistency, the four presets, reused photo/document detection, PDFs, unique claim numbers under concurrency, validation, reset. |
| `test_adjudication.py` | Routing rules, settlement arithmetic, decisions (including the old stale-payment bug), value sanitizing, the checks. |
| `test_imaging.py` | EXIF parsing, GPS, metadata stripping, hash stability under resizing, rejection of bad files. |
| `test_http.py` | Routing, the static-file allowlist, security headers, JSON-only POSTs, 413/415/405/404/429 responses, read-only settings. |

The tests never call Google Cloud. `tests/helpers.py` sets every integration explicitly, so `GEMINI_*`, `DOCUMENT_AI_*` or `CLAIMS_STORE` variables in your shell cannot make them reach real services.

## Running the Firestore and Cloud Storage tests

They use the official Firestore emulator (needs Java 11+) and the `gcp-storage-emulator` Python package.

1. Start the Firestore emulator. With the gcloud CLI:

   ```bash
   gcloud emulators firestore start --host-port=127.0.0.1:8085
   ```

   Without gcloud, download the emulator jar that `firebase-tools` uses, `cloud-firestore-emulator-v1.19.8.jar` from `https://storage.googleapis.com/firebase-preview-drop/emulator/`, and run:

   ```bash
   java -jar cloud-firestore-emulator-v1.19.8.jar --host 127.0.0.1 --port 8085
   ```

2. Start a Cloud Storage emulator with a test bucket. Use a separate virtual environment so it does not mix with the app's packages:

   ```bash
   pip install gcp-storage-emulator
   gcp-storage-emulator start --host=127.0.0.1 --port=9023 --in-memory --default-bucket=omniclaim-test-files
   ```

3. Run the tests with the emulator addresses:

   ```bash
   FIRESTORE_EMULATOR_HOST=127.0.0.1:8085 STORAGE_EMULATOR_HOST=http://127.0.0.1:9023 \
     python -m unittest tests.test_cloud_store -v
   ```

   In PowerShell:

   ```powershell
   $env:FIRESTORE_EMULATOR_HOST = "127.0.0.1:8085"; $env:STORAGE_EMULATOR_HOST = "http://127.0.0.1:9023"
   python -m unittest tests.test_cloud_store -v
   ```

Each test uses its own collection name, so runs do not interfere with each other.

## Running the whole app against the emulators

With the emulators running, the app itself can use them:

```bash
FIRESTORE_EMULATOR_HOST=127.0.0.1:8085 STORAGE_EMULATOR_HOST=http://127.0.0.1:9023 \
GOOGLE_CLOUD_PROJECT=demo-omniclaim CLAIMS_STORE=firestore CLAIM_FILES_BUCKET=omniclaim-test-files \
GEMINI_BACKEND=none python server.py
```

`GEMINI_BACKEND=none` keeps Gemini in demo mode even though a project is set.

## Checks in a real browser

Before each release, the web app was driven with Puppeteer and a local Chrome in three set-ups:

- **Demo mode.** Every sample claim and tab, the four presets, decisions (full, then recommended: the payment and letter update to $750), the copilot, the dialogs, form validation, and the 390 px phone layout (no horizontal scrolling). No console errors or failed requests.
- **Live mode.** The server pointed at a fake Gemini endpoint through `GOOGLE_GEMINI_BASE_URL`. Checked: "Gemini live" after the start-up check, the Gemini engine line on new claims, the failure banner on a 403, the median analysis-time metric, and copilot answers via Gemini.
- **Cloud Run mode.** `K_SERVICE` set and no credentials. Checked: read-only settings (403), reset disabled, an actionable "no credentials" message, and fallback without auto-approval.

## Static checks

```bash
python -m pyflakes server.py omniclaim tests tools   # pip install pyflakes
node --check app.js
```
