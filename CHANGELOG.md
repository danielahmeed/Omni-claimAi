# Changelog

## 2.1.0 (2026-10-16)

Adds Document AI and durable storage in Firestore and Cloud Storage. Both are optional, switched on with one setting, and fall back safely.

### Added

- **Document AI Invoice Parser** (`DOCUMENT_AI_PROCESSOR`).
  - Every bill is read by Document AI first: line items, totals, vendor, invoice number and date.
  - The reading is stored on the claim and passed to Gemini, which judges each line against the photo.
  - The bill tab shows "Read by: Document AI Invoice Parser + Gemini" and the invoice number. The Analysis log has a "Document AI extraction" step.
  - Without Gemini, the extracted lines are shown and held for the adjuster.
  - If Document AI fails, Gemini reads the bill alone.
- `tools/create_document_ai_processor.py` creates the Invoice Parser processor, or finds the existing one, and prints its name.
- **Firestore + Cloud Storage claim store** (`CLAIMS_STORE=firestore`, `CLAIM_FILES_BUCKET`).
  - Claims in Firestore, photos and bills in a bucket.
  - Claims survive redeploys and are shared by several instances.
  - Claim numbers are reserved without a shared counter, so instances never collide.
  - The sample data is seeded once, with a lock.
  - If Firestore is unreachable at start-up, the app falls back to local storage and shows why.
- The deploy scripts can enable both:
  - Bash: `DOCUMENT_AI_PROCESSOR=...`, `USE_FIRESTORE=true`
  - PowerShell: `-DocumentAiProcessor`, `-UseFirestore`

  With Firestore they also create the database and bucket, grant only the needed roles, and allow 3 instances.
- New evidence value `NOT_CHECKED` ("Not checked against a photo") for bill lines that could not be compared with a photo.
- `docs/TESTING.md`, including how to run the Firestore and Cloud Storage emulators.
- 18 new tests (90 in total): Document AI with the real REST client against a fake endpoint, Firestore and Cloud Storage against the official emulators, the storage fallback, and concurrency of claim numbers.

### Changed

- Auto-approval now also requires a damage photo.
- New claims get their number only when they are saved, so rejected uploads no longer leave gaps.
- **How it works** shows the live state of Document AI and of storage instead of "roadmap".

### Fixed

- Two claims submitted at the same moment could get the same claim number.
- An error response sent before reading the request body (for example 415) could reach the client as a reset connection instead of the error message.

## 2.0.0 (2026-10-16)

A rebuild that makes the AI analysis real, removes the simulated parts, fixes security problems and adds tests and documentation.

### Added

- **Real multimodal assessment with Gemini on Vertex AI.**
  - The damage photo, the bill (image or PDF) and the policy wording are sent to `gemini-3.8-flash` with a strict JSON schema.
  - Gemini returns line-by-line verdicts against the photo, damage bounding boxes, clause assessments, findings, a risk score and a claimant explanation.
  - The client uses Vertex AI with Application Default Credentials (no API key on Cloud Run) or, for local experiments, a Gemini API key.
- **Photo forensics on every claim.**
  - EXIF metadata: capture date, device, editing software, GPS.
  - A perceptual-hash search across all stored claims, which finds reused photos even after resizing or re-compression.
  - A SHA-256 check for re-submitted documents.
- **Policy checks.** A policy register with periods, holders and deductibles: losses soon after the policy start, losses outside the policy period and claimant/holder mismatches are flagged.
- **Cost benchmark** over a 10,000-claim synthetic dataset, computed locally or in **BigQuery** when `BIGQUERY_BENCHMARK_TABLE` is set (with automatic fallback).
- **Deterministic routing and settlement** in `omniclaim/adjudication.py`, with documented thresholds.
- **Adjuster decisions:**
  - approve the recommended amount, approve the full amount, refer to SIU, or deny
  - each decision recomputes the payment and the letter
- **New-claim form** with photo and bill upload (drag and drop, previews, size and type checks) and four presets that attach real sample photos and invoices.
- **Workbench:**
  - the photo with damage boxes, and a camera-metadata view
  - findings labeled by source
  - an analysis log with real step timings
  - line items with reasons, policy clauses with verdicts, the cost benchmark chart, signals across the workspace
- **"How it works"** dialog showing the live status of each Google Cloud service in the running deployment.
- **AI settings** dialog: Vertex AI, API key or off; model and thinking level; connection test. Read-only on Cloud Run.
- **Demo mode** that is honest: recorded results only for the bundled sample files, labeled as such. Other uploads are marked "not analyzed".
- **Cloud Run deploy scripts** (`deploy/*.sh`, `deploy/*.ps1`), a non-root Docker image on Python 3.12, and a `/api/health` endpoint.
- **72 automated tests**, including the real `google-genai` SDK against a fake Gemini endpoint and HTTP security tests.
- **Documentation:** README, architecture, configuration, deployment, API, demo guide, security, submission checklist, and photo attribution.

### Changed

- The header metrics are computed from the claims in the workspace instead of fixed numbers (12,480 claims, 94.8% accuracy, $4.22M).
- `/api/health` and `/api/status` report real state instead of "ONLINE" for services that were never called.
- The AI indicator shows **Gemini live** only after a successful call; before, it showed "live" whenever any key string was set.
- The sample claims were rewritten so every amount adds up, and labeled **Sample scenario**. Claims that referred to systems the app does not connect to (salvage auctions, NICB, NOAA) now cite checks the app really performs.
- Tabs and labels describe what each part does instead of naming services that were not used.
- The model default is `gemini-3.8-flash` on the `global` location. The old settings listed shut-down and legacy models (2.0 Flash, 1.5 Pro/Flash).
- The HTTP server is multi-threaded, so a slow Gemini call no longer blocks other requests.
- The light theme and responsive layout from the earlier redesign are kept and extended to the new screens.

### Fixed

- Approving the full amount and then the adjusted amount left the old payment ($7,950 instead of $750), and the letter disagreed with the ledger.
- New claims always showed a car-bumper drawing and car repair lines, even for home water or glass claims.
- The "GCP Live Key" settings dialog was nested inside the architecture dialog and could not open.
- Claim fields were inserted into the page as raw HTML, which allowed stored cross-site scripting.
- The Copilot printed raw error text into its answers when the API key failed.

### Security

- Removed `data/config.json`, which contained a Gemini API key that Google has flagged as leaked. **Revoke that key** (see `docs/SECURITY.md`).
- The server no longer serves its own source code, data or configuration. Only an allowlist of web files is served.
- JSON-only POSTs, upload and body limits, per-client rate limits, a Content Security Policy and other security headers.
- Settings changes and data reset are disabled on Cloud Run by default.
- The container runs as a non-root user. Keys and runtime data are excluded from git and from the image.

### Removed

- `gcp_service.py` (replaced by the `omniclaim/` package).
- `data/claims.json` and `data/benchmarks.json`: the inconsistent seed data and the hard-coded metrics.
- `firebase.json`: it published the repository folder as a static site without the backend.
- The simulated five-step "pipeline" animation, the fake "Dispatch to insured" action, and the "Gemini Multimodal Accuracy" metric.
