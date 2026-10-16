# Architecture

OmniClaim is a single Python service (standard-library HTTP server, no web framework) that serves a static web app and a JSON API. It runs locally with `python server.py` and on Cloud Run as one container. Each Google Cloud service it uses is optional and switched on by configuration. Each falls back safely if it fails.

## Components

| File | Responsibility |
| --- | --- |
| `server.py` | Entry point. Builds the service, binds to `127.0.0.1` locally or `0.0.0.0` on Cloud Run, runs a background Gemini check, and shuts down cleanly on SIGTERM. |
| `omniclaim/app.py` | Wiring: chooses the claim store (Firestore or local), creates the Gemini and Document AI clients and the HTTP server. |
| `omniclaim/web.py` | HTTP routing, static-file allowlist, JSON-only POSTs, body-size limits, per-client rate limits, security headers. |
| `omniclaim/service.py` | The claim pipeline and every API operation: create, list, get, decide, copilot, settings, status. |
| `omniclaim/imaging.py` | Validates uploads, reads EXIF metadata, computes the perceptual hash, re-encodes images. |
| `omniclaim/checks.py` | Deterministic checks: reused photo or document, photo metadata, policy period and holder, cost benchmark, amount mismatches. |
| `omniclaim/docai.py` | Document AI Invoice Parser client (REST transport) and the parser that turns its entities into line items. |
| `omniclaim/ai.py` | Gemini client through the `google-genai` SDK (Vertex AI or API key), connection status, error messages. |
| `omniclaim/schemas.py` | Pydantic models for the JSON that Gemini must return. |
| `omniclaim/prompts.py` | Assessment and copilot prompts. |
| `omniclaim/demo_engine.py` | Demo mode when Gemini is not configured: recorded results for the bundled samples, honest "not analyzed" results otherwise, template copilot answers. |
| `omniclaim/adjudication.py` | Line-item normalization, routing, settlement, adjuster decisions, the claimant letter. |
| `omniclaim/benchmarks.py` | Cost benchmark from the local synthetic dataset or a BigQuery table. |
| `omniclaim/policies.py` | Policy wording and the policy register (`data/policies.json`). |
| `omniclaim/store.py` | Local claim storage: one JSON file plus a folder of files, with atomic writes. |
| `omniclaim/cloud_store.py` | Durable claim storage: Firestore for claims, Cloud Storage for photos and bills. |
| `omniclaim/config.py` | Environment variables, the local settings file, and the decision thresholds. |
| `index.html`, `app.js`, `styles.css` | The web app. Plain JavaScript, no build step. All API text is HTML-escaped before rendering. |

## What happens when a claim is submitted

`POST /api/claims` with the form fields and base64-encoded files. Each step is timed and stored in `claim.analysis.steps`; the app shows this as the **Analysis log**.

1. **Validate.** Required fields, date not in the future, amount range, policy-number format, file size (`MAX_UPLOAD_MB`), file type. Invalid input returns HTTP 400 with the name of the offending field.
2. **Photo checks.**
   - Pillow opens the image. Only JPEG, PNG and WebP are accepted, with a 50-megapixel limit.
   - Camera make and model, capture time, editing software and GPS are read from EXIF.
   - The image is rotated upright and re-encoded as JPEG with metadata removed, at most 1600 px.
   - A 64-bit difference hash (dHash) is compared with every stored claim's photo. A distance of 6 bits or less counts as the same photo, which survives resizing and re-compression.
3. **Document checks.** The SHA-256 of the uploaded file is compared with earlier claims to catch an identical bill submitted twice. Images are re-encoded (at most 2200 px); PDFs are kept as they are.
4. **Document AI extraction** (when `DOCUMENT_AI_PROCESSOR` is set). The original file is sent to the Invoice Parser. Its line items, totals, vendor, invoice number and date are stored on the claim and passed to Gemini (see below). If Document AI fails, the step is marked failed and Gemini reads the bill on its own.
5. **Policy and cost checks.**
   - The policy number is looked up in the register to check the policy period, the named holder, the product and the deductible.
   - Losses within 14 days of the policy start are flagged.
   - The claimed amount is placed in the distribution of similar historical claims (median, 75th and 95th percentile, and this claim's percentile), computed in BigQuery or locally.
6. **AI assessment** (see below), or demo mode.
7. **Routing and settlement** in plain code (see below). The claim number is reserved here, so rejected uploads never use one up.
8. The claim, its photo and its document are saved, and the full claim is returned.

## The Document AI request

`DocumentAIService.extract` calls `process_document` on the processor named in `DOCUMENT_AI_PROCESSOR` with the official `google-cloud-documentai` client:
- It uses the REST transport, so no gRPC runtime is needed.
- The endpoint is `https://LOCATION-documentai.googleapis.com`, where the location comes from the processor name.
- It authenticates with Application Default Credentials.

The request carries the original upload as a `RawDocument` (PDF, JPEG, PNG or WebP).

`parse_document` reads these Invoice Parser entities:

| Entity | Used as |
| --- | --- |
| `line_item`, with `line_item/description`, `line_item/amount`, `line_item/quantity`, `line_item/unit_price` | Line items. The amount comes from the normalized money value, then the printed text, then quantity × unit price. |
| `total_amount`, `currency` | Document total and currency |
| `supplier_name` | Vendor |
| `invoice_id`, `invoice_date` | Invoice number and date |

Gemini receives this as `automated_checks.document_ai_extraction`, with the instruction to use those lines and amounts as the reading of the bill unless the image clearly shows otherwise. The bill tab shows "Read by: Document AI Invoice Parser + Gemini" and the invoice number.

Errors are mapped to actionable messages. For example, permission denied becomes "grant roles/documentai.apiUser". Both the REST-style (`Forbidden`, `BadRequest`) and gRPC-style (`PermissionDenied`, `InvalidArgument`) exceptions are handled.

`tools/create_document_ai_processor.py` creates the Invoice Parser processor, or finds the existing one, and prints its name.

## The Gemini request

`GeminiService.assess_claim` sends one `generate_content` request through the official `google-genai` SDK:

- **Client.**
  - Vertex AI: `genai.Client(enterprise=True, project=GOOGLE_CLOUD_PROJECT, location=GEMINI_LOCATION)`, authenticated with Application Default Credentials. On Cloud Run these are the service account's credentials, so no key exists anywhere.
  - API-key mode: `genai.Client(api_key=...)` against the Gemini Developer API.
- **Model.** `gemini-3.8-flash` by default, served from the `global` location on Vertex AI. It accepts images and PDFs.
- **Contents.** One user turn with:
  - a JSON "claim file": the claim form, the automated check results (including any Document AI extraction), the policy record and the full policy wording
  - the damage photo (JPEG)
  - the bill (JPEG or PDF), each preceded by a label
- **System instruction.** The assessor instructions in `prompts.py`:
  - read every line exactly
  - judge each line against the photo
  - mark damaged areas with `box_2d` coordinates
  - apply the policy clauses
  - score risk on a stated scale
  - write a short explanation without amounts or fraud wording
- **Structured output.** `response_mime_type="application/json"` and `response_schema=ClaimAssessment`, a Pydantic model in `schemas.py`. The answer is validated with Pydantic again before use.
- **Thinking.** `thinking_config.thinking_level` (default `LOW`, configurable), sent only to Gemini 3 and later models. Automatic function calling is switched off because no tools are used.
- **Not sent:** `temperature`, `top_p`, `top_k`, `candidate_count` and penalties. Gemini 3.x ignores or rejects them.

If the call fails (credentials, permissions, quota, timeout, malformed answer):
- the claim falls back to demo mode
- the failure is recorded in the analysis log
- the claim shows a visible notice with an actionable message
- the status indicator switches to **Gemini error**
- the claim is never auto-approved

The status shows **Gemini live** only after a real call has succeeded.

## Decision rules

All thresholds are in `omniclaim/config.py`.

| Rule | Condition |
| --- | --- |
| SIU referral | The photo or document was already used in another claim (risk raised to at least 90), or risk is 80 or higher. |
| Adjuster review, recommend denial | Gemini (or the sample) found that an exclusion applies (`NOT_COVERED`). |
| Auto-approve | Risk 19 or lower, coverage `COVERED`, a damage photo, an itemized bill with every line `ALLOW`, no `CRITICAL` or `MEDIUM` findings, the claim was actually analyzed (not demo-generic), and no Gemini call failed. |
| Adjuster review | Everything else. The reasons are listed in `routingReason`. |

**Settlement.** These are computed in `adjudication.compute_settlement` and covered by regression tests:

- recommended = the allowed amounts of `ALLOW` and `REDUCE` lines, capped at the claimed amount
- held = the billed amount of `REVIEW` lines
- disallowed = claimed - recommended - held
- payment = approved (or recommended) - deductible, never below zero, and zero while the claim is with SIU or denied

**Decisions.** The adjuster can approve the recommended amount, approve the full amount, refer to SIU or deny. Every decision recomputes the settlement and rebuilds the letter, so the letter always matches the numbers.

## Data model (a claim)

```jsonc
{
  "id": "CLM-9232", "isSample": false, "createdAt": "2026-10-16T09:35:00+00:00",
  "claimantName": "...", "policyNumber": "...", "product": "auto|home",
  "lossType": "...", "lossCategory": "auto_collision", "incidentDate": "2026-10-14",
  "incidentLocation": "...", "description": "...", "claimedAmount": 8450.0, "deductible": 500.0,
  "status": "AUTO_APPROVED|ADJUSTER_REVIEW|SIU_ESCALATED|APPROVED|DENIED",
  "riskScore": 72, "riskLevel": "LOW|MODERATE|HIGH|CRITICAL", "riskRationale": "...",
  "recommendedAction": "AUTO_APPROVE|APPROVE_ADJUSTED|REVIEW|SIU_REFERRAL|DENY", "routingReason": "...",
  "photo": { "fileName": "...", "width": 1068, "height": 1600, "dhash": "1f76...", "file": "CLM-9232-photo.jpg",
             "metadata": { "hasExif": true, "cameraMake": "...", "capturedAt": "...", "editedWith": null, "gps": null },
             "matches": [ { "claimId": "CLM-8977", "distance": 0 } ] },
  "illustration": null,
  "document": { "fileName": "...", "sha256": "...", "type": "Repair invoice", "vendor": "...", "total": 8450.0,
                "extractedBy": "Document AI Invoice Parser + Gemini", "matches": [],
                "file": "CLM-9232-document.jpg", "mimeType": "image/jpeg",
                "documentAi": { "vendor": "...", "invoiceId": "APC-26-1014-07", "invoiceDate": "2026-10-15",
                                "currency": "USD", "total": 8450.0, "pages": 1, "latencyMs": 1800, "processor": "abc123",
                                "lineItems": [ { "description": "...", "amount": 3800.0, "quantity": null, "unitPrice": null } ] } },
  "damageSummary": "...", "damageRegions": [ { "label": "...", "severity": "MINOR", "box": [300, 525, 690, 765] } ],
  "lineItems": [ { "description": "...", "billedAmount": 3800.0,
                   "photoEvidence": "SUPPORTED|NOT_SUPPORTED|NOT_VISIBLE|NOT_APPLICABLE|NOT_CHECKED",
                   "recommendation": "ALLOW|REDUCE|DISALLOW|REVIEW", "allowedAmount": 0.0, "reason": "..." } ],
  "findings": [ { "title": "...", "severity": "CRITICAL|MEDIUM|INFO", "detail": "...", "source": "gemini|photo-check|..." } ],
  "coverage": { "decision": "COVERED|PARTIALLY_COVERED|NOT_COVERED|NEEDS_REVIEW", "form": "...",
                "clauses": [ { "clauseId": "SEC-4.A", "title": "...", "text": "...", "verdict": "NOT_MET", "explanation": "..." } ] },
  "policy": { "found": true, "holder": "...", "effectiveDate": "...", "daysSincePolicyStart": 347, "inPolicyPeriod": true },
  "benchmark": { "category": "auto_collision", "sampleSize": 4400, "median": 2854, "p75": 4582, "p95": 8908,
                 "claimPercentile": 94.0, "source": "local-dataset|bigquery", "dataset": "..." },
  "settlement": { "claimed": 8450, "recommended": 1250, "held": 0, "disallowed": 7200, "deductible": 500,
                  "approved": null, "net": 750, "basis": "recommended|approved|on-hold|denied" },
  "explanation": "...", "letter": "...",
  "analysis": { "engine": "gemini|recorded-demo|demo-generic|sample", "label": "...", "model": "gemini-3.8-flash",
                "backend": "vertex|api-key", "durationMs": 6400, "notice": null,
                "steps": [ { "name": "Photo checks", "status": "done|skipped|failed", "detail": "...", "ms": 41 } ] },
  "decision": { "action": "APPROVE_RECOMMENDED", "label": "...", "approvedAmount": 1250, "by": "Adjuster", "at": "..." },
  "history": [ { "at": "...", "event": "Claim submitted", "by": "Claimant" } ]
}
```

`damageRegions[].box` is `[ymin, xmin, ymax, xmax]` scaled 0-1000, as Gemini returns it. The app draws it over the stored photo. A claim is about 10-20 KB, well within Firestore's 1 MiB document limit; photos and bills are stored separately.

## Demo mode and sample data

| Data | What is real |
| --- | --- |
| Photo, document, policy and cost checks | Always real, in every mode. |
| New claims with Gemini configured | Fully live: Gemini reads the uploaded files (and Document AI, when configured). |
| New claims without Gemini, using a bundled sample photo and bill | The AI part is a recorded result for that exact pair (`data/demo_mode/recorded_analyses.json`). It is labeled "Recorded demo result". |
| New claims without Gemini, with Document AI configured | Document AI's line items are shown, marked "Not checked against a photo" and held for the adjuster. |
| New claims without Gemini or Document AI, with any other files | Not analyzed by AI. The claim says so and goes to an adjuster. Nothing is invented. |
| The six sample claims | The AI part is pre-recorded (`data/seed/claims.json`) and the claims are labeled "Sample scenario". Their checks run live at start-up. |
| Policy wording and register | Fictional (`data/policies.json`). |
| Benchmark dataset | Synthetic, 10,000 rows (`tools/generate_benchmark_data.py`). |
| Workspace metrics in the header | Computed from the claims currently in the workspace. |

## Storage

Both stores have the same interface: `load_or_seed`, `reset`, `all`, `get`, `put`, `next_id`, `photo_index`, `document_index`, `related_counts`, `save_file`, `read_file` and `check`. The rest of the app does not know which one is in use.

**Local (default):** `ClaimStore` keeps all claims in `data/runtime/claims.json` and files in `data/runtime/files/`. It writes to a temporary file and then renames it, under a lock. Claim numbers are reserved under the same lock, so concurrent requests never get the same number. On Cloud Run this store is per instance and resets on every deploy, so the deploy script uses `--max-instances 1` with it.

**Firestore + Cloud Storage** (`CLAIMS_STORE=firestore`, `CLAIM_FILES_BUCKET=...`): `CloudClaimStore`.

| Data | Where |
| --- | --- |
| Claims | One Firestore document per claim in the collection `FIRESTORE_COLLECTION` (default `claims`), keyed by claim number |
| Photos and bills | Cloud Storage objects `gs://BUCKET/claims/CLM-9232-photo.jpg` and `...-document.jpg` or `.pdf` |
| Claim numbers | Reserved by *creating* `claims_ids/CLM-<n>`. Firestore allows only one creator per document, so a racing instance gets `AlreadyExists` and tries the next number. There is no shared counter and no lock contention. |
| Sample data | Seeded once. The first instance creates `claims_meta/seed`; other instances that start at the same time wait for it to finish. |

Data survives redeploys, and the service can run several instances. The deploy script allows 3. At start-up the app checks that it can reach Firestore and list the bucket. If not, it falls back to the local store and **How it works** shows the error.

## Security design

- **No secrets in the repository.**
  - On Cloud Run, every Google Cloud call uses the service account.
  - Locally, a key can be set in `.env` or in the Settings dialog, which writes `data/runtime/settings.json`. Both are git-ignored.
  - The API only ever returns the key masked.
- **Least-privilege service account.** It only gets roles for what is enabled:

  | Role | For |
  | --- | --- |
  | `roles/aiplatform.user` | Gemini |
  | `roles/documentai.apiUser` | Document AI |
  | `roles/datastore.user` | Firestore |
  | `roles/storage.objectAdmin` | Only the claims bucket |
  | `roles/bigquery.jobUser` and `roles/bigquery.dataViewer` | BigQuery |
- **Settings are read-only on Cloud Run** (`ALLOW_SETTINGS_UI=false` by default there), so visitors cannot change the AI connection. Data reset is disabled there too.
- **Static allowlist.** Only `index.html`, `app.js`, `styles.css` and `samples/` are served. Source code, `data/` and configuration return 404, and path traversal is blocked. Stored files are served only through the claim API, by validated names.
- **JSON-only POSTs.** Every POST must be `application/json`, which blocks cross-site form submissions. Unread request bodies are drained before an error is sent, so clients get the error message instead of a reset connection.
- **Upload limits.** Bodies are capped by size, and files are validated by decoding them, not by trusting their names.
- **Rate limits.** Per client: claim analysis, copilot and connection tests (in memory, per instance).
- **Escaping.** The web app escapes all API text before inserting it as HTML.
- **Headers.** The page is served with a Content Security Policy (`script-src 'self'`), `X-Frame-Options: DENY` and `nosniff`.
- **Container.** Runs as a non-root user.
- **No fraud wording in letters.** The claimant letter for SIU referrals never mentions fraud.

For a real deployment, put the service behind authentication, for example Identity-Aware Proxy, so only adjusters can open it.

## Testing

See [TESTING.md](TESTING.md). In short:
- The Gemini, Document AI and BigQuery code is tested with the real Google client libraries against local fake endpoints.
- The Firestore and Cloud Storage store is tested against the official Firestore emulator and a Cloud Storage emulator.
- The web app is checked in a real browser in demo mode, live mode (with a fake Gemini) and simulated Cloud Run mode.

## Roadmap

1. Vertex AI Search over full policy documents and endorsements, replacing the inline policy wording for large libraries.
2. Pub/Sub intake so claims are analyzed asynchronously at volume.
3. Identity-Aware Proxy or Firebase Auth for adjuster sign-in.
4. Streaming decisions into BigQuery for fraud analytics and model monitoring.
5. Document AI custom extractor trained on the insurer's own estimate formats.
