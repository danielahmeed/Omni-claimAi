# Deploying to Cloud Run

The app deploys as one container to Cloud Run. Every Google Cloud call uses the service's own service account, so no API key exists anywhere.

## Prerequisites

- A Google Cloud project with billing enabled.
- The [gcloud CLI](https://cloud.google.com/sdk/docs/install), logged in with `gcloud auth login`. For the Document AI tool, also run `gcloud auth application-default login`.
- Permission to enable APIs, create service accounts, grant roles and deploy to Cloud Run. Project Owner is enough.

## One command

From the project folder:

```bash
PROJECT_ID=your-project ./deploy/deploy-cloud-run.sh
```

```powershell
.\deploy\deploy-cloud-run.ps1 -ProjectId your-project
```

This deploys the core: Gemini on Vertex AI, with claims kept in the container. To add the optional services, see the sections below, then run the script with all of them:

```bash
PROJECT_ID=your-project USE_FIRESTORE=true \
  DOCUMENT_AI_PROCESSOR=projects/your-project/locations/us/processors/PROCESSOR_ID \
  BIGQUERY_BENCHMARK_TABLE=your-project.omniclaim.historical_claims \
  ./deploy/deploy-cloud-run.sh
```

```powershell
.\deploy\deploy-cloud-run.ps1 -ProjectId your-project -UseFirestore `
  -DocumentAiProcessor projects/your-project/locations/us/processors/PROCESSOR_ID `
  -BigQueryTable your-project.omniclaim.historical_claims
```

| Option (Bash / PowerShell) | Default | Meaning |
| --- | --- | --- |
| `REGION` / `-Region` | `us-central1` | Cloud Run region (also used for a new Firestore database and bucket) |
| `SERVICE` / `-Service` | `omniclaim-ai` | Service name |
| `GEMINI_MODEL` / `-GeminiModel` | `gemini-3.8-flash` | Model |
| `DOCUMENT_AI_PROCESSOR` / `-DocumentAiProcessor` | | Invoice Parser processor name |
| `USE_FIRESTORE=true` / `-UseFirestore` | off | Firestore + Cloud Storage storage |
| `FIRESTORE_LOCATION` / `-FirestoreLocation` | the region | Location for a new Firestore database |
| `CLAIM_FILES_BUCKET` / `-FilesBucket` | `PROJECT-omniclaim-files` | Bucket for photos and bills |
| `BIGQUERY_BENCHMARK_TABLE` / `-BigQueryTable` | | BigQuery table for benchmarks |

At the end the script prints the service URL. That URL is your product link.

## What the script does

1. Enables Cloud Run, Cloud Build, Artifact Registry and Vertex AI. With the options, it also enables Document AI, or Firestore and Cloud Storage.
2. Creates the service account `omniclaim-run` and grants it only what is enabled:

   | Role | For |
   | --- | --- |
   | `roles/aiplatform.user` | Gemini |
   | `roles/documentai.apiUser` | Document AI |
   | `roles/datastore.user` | Firestore |
   | `roles/storage.objectAdmin` | The claims bucket only |
   | `roles/bigquery.jobUser` and `roles/bigquery.dataViewer` | BigQuery |
3. With Firestore: creates the `(default)` Firestore database (Native mode) and the bucket (uniform access) if they don't exist yet.
4. Builds the container from the `Dockerfile` with Cloud Build (`gcloud run deploy --source .`).
5. Deploys with:
   - the environment variables for the enabled services
   - `--allow-unauthenticated`, so judges can open the URL
   - `--max-instances 1`, or 3 with Firestore, because storage is then shared
   - 1 vCPU, 1 GiB of memory and a 120-second request timeout

## Document AI (Invoice Parser)

1. Enable the API and create the processor. The tool reuses an existing processor with the same name, so it is safe to run twice:

   ```bash
   gcloud services enable documentai.googleapis.com --project your-project
   gcloud auth application-default login
   pip install -r requirements.txt
   python tools/create_document_ai_processor.py --project your-project --location us
   ```

   It prints a name like `projects/your-project/locations/us/processors/1a2b3c4d5e6f`. Alternatively, create an **Invoice Parser** in the Google Cloud console under **Document AI > Processor gallery** and copy its name from the processor page.

2. Deploy with `DOCUMENT_AI_PROCESSOR=<that name>` (or `-DocumentAiProcessor`).

Every new claim's bill is then read by the Invoice Parser first. The Analysis log shows a "Document AI extraction" step, and the bill tab says "Read by: Document AI Invoice Parser + Gemini" with the invoice number.

## Firestore and Cloud Storage

Deploy with `USE_FIRESTORE=true` (or `-UseFirestore`). The script creates what is missing and sets `CLAIMS_STORE=firestore` and `CLAIM_FILES_BUCKET`.

- Claims are stored in the Firestore collection `claims`, and photos and bills under `gs://BUCKET/claims/`.
- The six sample claims are seeded on the first start only, and data then survives redeploys.
- Claim numbers are reserved safely across instances.

To use an existing database or bucket, set `FIRESTORE_DATABASE` or `CLAIM_FILES_BUCKET` and grant the roles above yourself.

## BigQuery (optional)

This loads the benchmark dataset into BigQuery so the cost benchmark is a real BigQuery query:

```bash
bq --location=US mk --dataset PROJECT_ID:omniclaim
bq load --source_format=CSV --skip_leading_rows=1 PROJECT_ID:omniclaim.historical_claims \
  data/benchmarks/historical_claims.csv \
  claim_id:STRING,loss_category:STRING,state:STRING,claim_year:INTEGER,claim_amount:FLOAT,approved_amount:FLOAT,days_to_settle:INTEGER,confirmed_fraud:BOOLEAN
```

Then deploy with `BIGQUERY_BENCHMARK_TABLE=PROJECT_ID.omniclaim.historical_claims`.

## Check the deployment

1. `curl https://YOUR-URL/api/health` returns `{"status": "ok"}`.
2. Open the URL. The header pill shows **Gemini live (Vertex AI)** once the start-up check has run, which takes a few seconds.
3. Open **How it works**. Each enabled service should be **Active** or **Configured**, never **Error**. If one shows Error, its detail line says why, for example a missing role.
4. Open **New claim**, choose **Inflated repair bill** and click **Analyze claim**. Expect:
   - "Analyzed by Gemini `gemini-3.8-flash` via Vertex AI"
   - damage boxes on the photo
   - line items with reasons
   - with Document AI: a "Document AI extraction" step in the Analysis log
5. With Firestore, redeploy and check that the new claim is still there.

`/api/status` returns the same information as JSON, and the Cloud Run logs show a "Gemini check OK" line or the exact error at start-up.

## Data

| Store | Behavior on Cloud Run |
| --- | --- |
| Local (default) | Resets to the six sample claims on every deploy or restart, which gives every judge a clean start. `--max-instances 1` keeps one shared store. |
| Firestore | Persistent. To start over, delete the `claims`, `claims_ids` and `claims_meta` collections and the `claims/` folder in the bucket, or set `ALLOW_DATA_RESET=true` and use **Reset demo data**. |

## Updating

Run the deploy script again with the same options. Cloud Run creates a new revision and switches traffic to it.

## Cost and clean-up

Cloud Run scales to zero when idle. Gemini and Document AI are billed per use, and Firestore, Cloud Storage and BigQuery by storage and operations. At demo volume this is cents. Check the current prices before any load testing. The rate limits (`RATE_LIMIT_*`) cap how many analyses one visitor can trigger.

To remove everything:

```bash
gcloud run services delete omniclaim-ai --region us-central1
gcloud storage rm --recursive gs://PROJECT_ID-omniclaim-files      # if you used Firestore
gcloud iam service-accounts delete omniclaim-run@PROJECT_ID.iam.gserviceaccount.com
bq rm -r -d PROJECT_ID:omniclaim                                    # if you created the BigQuery dataset
```

Delete the Document AI processor in the console (**Document AI > My processors**). Delete the Firestore data in the console, or remove the database with `gcloud firestore databases delete --database="(default)"`.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| "Vertex AI denied the request ... roles/aiplatform.user" | Grant the service account the Vertex AI User role and make sure `aiplatform.googleapis.com` is enabled. |
| "Model 'gemini-3.8-flash' was not found in location ..." | Use `GEMINI_LOCATION=global`. Regions such as `us-central1` may not serve this model. |
| Document AI shows **Error**: "denied the request ... roles/documentai.apiUser" | Grant that role and enable `documentai.googleapis.com`. |
| Document AI: "processor not found" | `DOCUMENT_AI_PROCESSOR` must be the full name (`projects/.../locations/us/processors/...`) and the location must match the processor. |
| Storage shows **Error** and "Using a local JSON file instead" | Firestore or the bucket is not reachable. Check the database exists, `roles/datastore.user`, `roles/storage.objectAdmin` on the bucket, and `CLAIM_FILES_BUCKET`. The detail line has the exact error. |
| "No Google Cloud credentials found" (locally) | Run `gcloud auth application-default login`. |
| "Gemini quota or rate limit reached" | Wait a minute, or request a higher quota in the console. |
| The header says **Demo mode** on Cloud Run | `GOOGLE_CLOUD_PROJECT` is missing from the service's environment variables. Redeploy with the script. |
| Claims disappeared after a deploy | Expected with the local store. Use Firestore for persistence. |
| The deploy asks to create an Artifact Registry repository | Answer yes. `--source` deploys store the image there. |
