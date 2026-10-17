# Deploy OmniClaim AI to Cloud Run with Gemini on Vertex AI (no API keys). Windows PowerShell version.
#
# Usage:
#   .\deploy\deploy-cloud-run.ps1 -ProjectId my-project
#   .\deploy\deploy-cloud-run.ps1 -ProjectId my-project -UseFirestore `
#       -DocumentAiProcessor projects/my-project/locations/us/processors/abc123 `
#       -BigQueryTable my-project.omniclaim.historical_claims
#
# Requires the gcloud CLI, logged in with `gcloud auth login`, and billing enabled on the project.
param(
  [Parameter(Mandatory = $true)][string]$ProjectId,
  [string]$Region = "us-central1",
  [string]$Service = "omniclaim-ai",
  [string]$GeminiModel = "gemini-3.8-flash",
  [string]$GeminiLocation = "global",
  [string]$ServiceAccountName = "omniclaim-run",
  [string]$DocumentAiProcessor = "",
  [switch]$UseFirestore,
  [string]$FirestoreLocation = "",
  [string]$FilesBucket = "",
  [string]$BigQueryTable = ""
)
$ErrorActionPreference = "Stop"
$SaEmail = "$ServiceAccountName@$ProjectId.iam.gserviceaccount.com"
if (-not $FirestoreLocation) { $FirestoreLocation = $Region }
if (-not $FilesBucket) { $FilesBucket = "$ProjectId-omniclaim-files" }
$MaxInstances = 1
Set-Location (Join-Path $PSScriptRoot "..")

function Invoke-Gcloud {
  & gcloud @args
  if ($LASTEXITCODE -ne 0) { throw "gcloud $($args -join ' ') failed with exit code $LASTEXITCODE" }
}

function Grant-Role([string]$Role) {
  Invoke-Gcloud projects add-iam-policy-binding $ProjectId --member="serviceAccount:$SaEmail" --role=$Role --condition=None --quiet | Out-Null
}

function Test-Gcloud {
  & gcloud @args *> $null
  return ($LASTEXITCODE -eq 0)
}

Write-Host "==> Project $ProjectId, region $Region, service $Service"
Invoke-Gcloud config set project $ProjectId

$Apis = @("run.googleapis.com", "cloudbuild.googleapis.com", "artifactregistry.googleapis.com", "aiplatform.googleapis.com")
if ($DocumentAiProcessor) { $Apis += "documentai.googleapis.com" }
if ($UseFirestore) { $Apis += @("firestore.googleapis.com", "storage.googleapis.com") }
Write-Host "==> Enabling APIs: $($Apis -join ' ')"
Invoke-Gcloud services enable @Apis

Write-Host "==> Service account $SaEmail"
if (-not (Test-Gcloud iam service-accounts describe $SaEmail)) {
  Invoke-Gcloud iam service-accounts create $ServiceAccountName --display-name="OmniClaim AI Cloud Run"
}
Grant-Role "roles/aiplatform.user"

$EnvVars = "GEMINI_BACKEND=vertex,GOOGLE_CLOUD_PROJECT=$ProjectId,GEMINI_LOCATION=$GeminiLocation,GEMINI_MODEL=$GeminiModel"

if ($DocumentAiProcessor) {
  Write-Host "==> Document AI processor $DocumentAiProcessor"
  Grant-Role "roles/documentai.apiUser"
  $EnvVars = "$EnvVars,DOCUMENT_AI_PROCESSOR=$DocumentAiProcessor"
}

if ($UseFirestore) {
  Write-Host "==> Firestore database and bucket gs://$FilesBucket"
  if (-not (Test-Gcloud firestore databases describe)) {
    Invoke-Gcloud firestore databases create --location=$FirestoreLocation --type=firestore-native
  }
  if (-not (Test-Gcloud storage buckets describe "gs://$FilesBucket")) {
    Invoke-Gcloud storage buckets create "gs://$FilesBucket" --location=$Region --uniform-bucket-level-access
  }
  Grant-Role "roles/datastore.user"
  Invoke-Gcloud storage buckets add-iam-policy-binding "gs://$FilesBucket" --member="serviceAccount:$SaEmail" --role="roles/storage.objectAdmin" | Out-Null
  $EnvVars = "$EnvVars,CLAIMS_STORE=firestore,CLAIM_FILES_BUCKET=$FilesBucket"
  $MaxInstances = 3   # storage is shared, so several instances are safe
}

if ($BigQueryTable) {
  Write-Host "==> Granting BigQuery read access for $BigQueryTable"
  Grant-Role "roles/bigquery.jobUser"
  Grant-Role "roles/bigquery.dataViewer"
  $EnvVars = "$EnvVars,BIGQUERY_BENCHMARK_TABLE=$BigQueryTable"
}

Write-Host "==> Building and deploying (this takes a few minutes)"
Invoke-Gcloud run deploy $Service --source . --region $Region --service-account $SaEmail `
  --allow-unauthenticated --max-instances $MaxInstances --memory 1Gi --cpu 1 --timeout 120 `
  --set-env-vars $EnvVars --quiet

$Url = & gcloud run services describe $Service --region $Region --format="value(status.url)"
Write-Host ""
Write-Host "Deployed: $Url"
Write-Host "Check:    curl $Url/api/status"
