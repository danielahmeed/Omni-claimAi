# Configuration

Every setting is optional. With nothing set, OmniClaim runs in demo mode.

Settings are read from:

1. **Environment variables.** This is the normal way on Cloud Run.
2. **A `.env` file** in the project folder, for local development. Copy `.env.example`. The file is git-ignored.
3. **The AI settings dialog**, local only. It writes `data/runtime/settings.json`, which is git-ignored and never served. Values saved there override environment variables. On Cloud Run the dialog is read-only.

Restart the server after editing `.env`. Changes made in the dialog apply immediately.

## Gemini

| Variable | Default | Meaning |
| --- | --- | --- |
| `GEMINI_BACKEND` | `vertex` if `GOOGLE_CLOUD_PROJECT` is set, else `api-key` if a key is set, else `none` | `vertex` (Gemini on Vertex AI), `api-key` (Gemini Developer API) or `none` (demo mode). |
| `GOOGLE_CLOUD_PROJECT` | | Google Cloud project for Vertex AI. |
| `GEMINI_LOCATION` | `global` | Vertex AI location. `gemini-3.8-flash` is served from `global` (also `us` and `eu`). |
| `GEMINI_API_KEY` | | Key from Google AI Studio, used when `GEMINI_BACKEND=api-key`. `GOOGLE_API_KEY` is also accepted. |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Model ID. `gemini-3.5-flash-lite` is a faster, cheaper alternative. |
| `GEMINI_THINKING_LEVEL` | `LOW` | `LOW`, `MEDIUM` or `HIGH`. Sent only to Gemini 3 and later models. Higher is more thorough and slower. |
| `GEMINI_TIMEOUT_SECONDS` | `90` | Request timeout. |
| `GEMINI_STARTUP_CHECK` | `true` | When Gemini is configured, make one small test call in the background at startup and log the result. |

### Vertex AI locally

```bash
gcloud auth application-default login
gcloud services enable aiplatform.googleapis.com --project YOUR_PROJECT_ID
```

```env
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
GEMINI_BACKEND=vertex
GEMINI_LOCATION=global
```

Your own Google account needs the **Vertex AI User** role on the project. Project owners and editors already have it.

### API key locally

```env
GEMINI_BACKEND=api-key
GEMINI_API_KEY=your-key
```

Or choose **AI settings > API key** in the app and paste the key. Never commit keys and never put them in files under `data/`, except `data/runtime/`, which is git-ignored.

## Optional services

Each service is off until its variable is set. If it fails, the app keeps working with the built-in fallback and shows the error in **How it works**.

### Document AI (Invoice Parser)

| Variable | Default | Meaning |
| --- | --- | --- |
| `DOCUMENT_AI_PROCESSOR` | | Full processor name, `projects/PROJECT/locations/us/processors/ID`. Create one with `python tools/create_document_ai_processor.py --project PROJECT`. When set, every bill is read by the Invoice Parser before Gemini judges it. Without it, Gemini reads the bill alone. |
| `DOCUMENT_AI_TIMEOUT_SECONDS` | `60` | Request timeout. |

The caller needs the **Document AI API User** role (`roles/documentai.apiUser`), and `documentai.googleapis.com` must be enabled.

### Firestore and Cloud Storage (durable storage)

| Variable | Default | Meaning |
| --- | --- | --- |
| `CLAIMS_STORE` | `local` | `local` (JSON file in `data/runtime`) or `firestore`. |
| `CLAIM_FILES_BUCKET` | | Cloud Storage bucket for photos and bills. Required with `CLAIMS_STORE=firestore`. |
| `FIRESTORE_DATABASE` | `(default)` | Firestore database ID. |
| `FIRESTORE_COLLECTION` | `claims` | Collection for claims. Claim-number reservations go to `<collection>_ids`, the seeding lock to `<collection>_meta`, and files to `gs://BUCKET/<collection>/`. Use a different name to keep separate data sets, for example for testing. |

The caller needs **Cloud Datastore User** (`roles/datastore.user`) on the project and **Storage Object Admin** (`roles/storage.objectAdmin`) on the bucket. `GOOGLE_CLOUD_PROJECT` selects the project; on Cloud Run it can be omitted.

### BigQuery (cost benchmarks)

| Variable | Default | Meaning |
| --- | --- | --- |
| `BIGQUERY_BENCHMARK_TABLE` | | `project.dataset.table` holding the historical claims (see [DEPLOYMENT.md](DEPLOYMENT.md#bigquery-optional)). If the query fails, the app uses the same dataset locally. |

## Server

| Variable | Default | Meaning |
| --- | --- | --- |
| `PORT` | `8080` | Port to listen on. Cloud Run sets this. |
| `HOST` | `127.0.0.1` locally, `0.0.0.0` on Cloud Run | Bind address. The Docker image sets `0.0.0.0`. |
| `MAX_UPLOAD_MB` | `10` | Maximum size of each uploaded file. |
| `ALLOW_SETTINGS_UI` | `true` locally, `false` on Cloud Run | Whether the AI settings dialog can change settings. Keep it `false` on any public URL. |
| `ALLOW_DATA_RESET` | `true` locally, `false` on Cloud Run | Whether **Reset demo data** (and `POST /api/admin/reset`) is allowed. |
| `RATE_LIMIT_ANALYZE_PER_10_MIN` | `20` | New claims per client per 10 minutes. `0` disables the limit. |
| `RATE_LIMIT_CHAT_PER_10_MIN` | `60` | Copilot questions per client per 10 minutes. |
| `RATE_LIMIT_TEST_PER_10_MIN` | `10` | Connection tests per client per 10 minutes. |
| `OMNICLAIM_RUNTIME_DIR` | `data/runtime` | Where claims, files and the local settings file are stored. |
| `LOG_LEVEL` | `INFO` | Python log level. |

"On Cloud Run" means the `K_SERVICE` variable is present, which Cloud Run always sets.

## Decision thresholds

These are constants in `omniclaim/config.py`, deliberately kept in code so changes are reviewed:

| Constant | Value | Meaning |
| --- | --- | --- |
| `AUTO_APPROVE_MAX_RISK` | 19 | Highest risk score that can be paid automatically. |
| `SIU_MIN_RISK` | 80 | Risk score from which claims go to SIU. |
| `DUPLICATE_PHOTO_MAX_DISTANCE` | 6 | Perceptual-hash bits (of 64) that may differ for two photos to count as the same. |
| `NEW_POLICY_ALERT_DAYS` | 14 | Losses this soon after the policy start are flagged. |

## Resetting data

- **Local store:** use **AI settings > Reset demo data**, or stop the server and delete `data/runtime/claims.json` and `data/runtime/files/`. The sample claims are rebuilt on the next start. Deleting `data/runtime/settings.json` clears any saved key.
- **Firestore store:** the same button works when `ALLOW_DATA_RESET=true`. It deletes the claims, the reservations, the seeding lock and the bucket files under the collection prefix, then reseeds. On Cloud Run it is off by default, because Firestore data otherwise survives deploys.
