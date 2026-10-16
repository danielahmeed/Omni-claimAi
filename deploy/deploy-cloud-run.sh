#!/usr/bin/env bash
# Deploy OmniClaim AI to Cloud Run with Gemini on Vertex AI (no API keys).
#
# Usage:
#   PROJECT_ID=my-project ./deploy/deploy-cloud-run.sh
#
# Optional settings (environment variables):
#   REGION=us-central1               Cloud Run region
#   SERVICE=omniclaim-ai             Cloud Run service name
#   GEMINI_MODEL=gemini-3.8-flash
#   DOCUMENT_AI_PROCESSOR=projects/P/locations/us/processors/ID   Invoice Parser (tools/create_document_ai_processor.py)
#   USE_FIRESTORE=true               store claims in Firestore and files in Cloud Storage
#   FIRESTORE_LOCATION=us-central1   location for a new Firestore database (default: REGION)
#   CLAIM_FILES_BUCKET=name          bucket for photos and bills (default: PROJECT_ID-omniclaim-files)
#   BIGQUERY_BENCHMARK_TABLE=my-project.omniclaim.historical_claims
#
# Requires the gcloud CLI, logged in with `gcloud auth login`, and billing enabled on the project.
set -euo pipefail

: "${PROJECT_ID:?Set PROJECT_ID to your Google Cloud project ID}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-omniclaim-ai}"
GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.8-flash}"
GEMINI_LOCATION="${GEMINI_LOCATION:-global}"
SA_NAME="${SA_NAME:-omniclaim-run}"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
DOCUMENT_AI_PROCESSOR="${DOCUMENT_AI_PROCESSOR:-}"
USE_FIRESTORE="${USE_FIRESTORE:-false}"
FIRESTORE_LOCATION="${FIRESTORE_LOCATION:-$REGION}"
CLAIM_FILES_BUCKET="${CLAIM_FILES_BUCKET:-${PROJECT_ID}-omniclaim-files}"
MAX_INSTANCES=1

cd "$(dirname "$0")/.."

grant() {  # grant <role> at project level to the service account
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" --role="$1" --condition=None --quiet >/dev/null
}

echo "==> Project ${PROJECT_ID}, region ${REGION}, service ${SERVICE}"
gcloud config set project "${PROJECT_ID}" >/dev/null

APIS="run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com aiplatform.googleapis.com"
[[ -n "${DOCUMENT_AI_PROCESSOR}" ]] && APIS="${APIS} documentai.googleapis.com"
[[ "${USE_FIRESTORE}" == "true" ]] && APIS="${APIS} firestore.googleapis.com storage.googleapis.com"
echo "==> Enabling APIs: ${APIS}"
# shellcheck disable=SC2086
gcloud services enable ${APIS}

echo "==> Service account ${SA_EMAIL}"
if ! gcloud iam service-accounts describe "${SA_EMAIL}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${SA_NAME}" --display-name="OmniClaim AI Cloud Run"
fi
grant roles/aiplatform.user

ENV_VARS="GEMINI_BACKEND=vertex,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GEMINI_LOCATION=${GEMINI_LOCATION},GEMINI_MODEL=${GEMINI_MODEL}"

if [[ -n "${DOCUMENT_AI_PROCESSOR}" ]]; then
  echo "==> Document AI processor ${DOCUMENT_AI_PROCESSOR}"
  grant roles/documentai.apiUser
  ENV_VARS="${ENV_VARS},DOCUMENT_AI_PROCESSOR=${DOCUMENT_AI_PROCESSOR}"
fi

if [[ "${USE_FIRESTORE}" == "true" ]]; then
  echo "==> Firestore database and bucket gs://${CLAIM_FILES_BUCKET}"
  if ! gcloud firestore databases describe >/dev/null 2>&1; then
    gcloud firestore databases create --location="${FIRESTORE_LOCATION}" --type=firestore-native
  fi
  if ! gcloud storage buckets describe "gs://${CLAIM_FILES_BUCKET}" >/dev/null 2>&1; then
    gcloud storage buckets create "gs://${CLAIM_FILES_BUCKET}" --location="${REGION}" --uniform-bucket-level-access
  fi
  grant roles/datastore.user
  gcloud storage buckets add-iam-policy-binding "gs://${CLAIM_FILES_BUCKET}" \
    --member="serviceAccount:${SA_EMAIL}" --role="roles/storage.objectAdmin" >/dev/null
  ENV_VARS="${ENV_VARS},CLAIMS_STORE=firestore,CLAIM_FILES_BUCKET=${CLAIM_FILES_BUCKET}"
  MAX_INSTANCES=3   # storage is shared, so several instances are safe
fi

if [[ -n "${BIGQUERY_BENCHMARK_TABLE:-}" ]]; then
  echo "==> Granting BigQuery read access for ${BIGQUERY_BENCHMARK_TABLE}"
  grant roles/bigquery.jobUser
  grant roles/bigquery.dataViewer
  ENV_VARS="${ENV_VARS},BIGQUERY_BENCHMARK_TABLE=${BIGQUERY_BENCHMARK_TABLE}"
fi

echo "==> Building and deploying (this takes a few minutes)"
gcloud run deploy "${SERVICE}" \
  --source . \
  --region "${REGION}" \
  --service-account "${SA_EMAIL}" \
  --allow-unauthenticated \
  --max-instances "${MAX_INSTANCES}" \
  --memory 1Gi \
  --cpu 1 \
  --timeout 120 \
  --set-env-vars "${ENV_VARS}" \
  --quiet

URL="$(gcloud run services describe "${SERVICE}" --region "${REGION}" --format='value(status.url)')"
echo
echo "Deployed: ${URL}"
echo "Check:    curl ${URL}/api/status"
