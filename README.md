# 🛡️ OmniClaim AI
### Autonomous Multimodal Insurance Claim Intelligence & Fraud Adjudication Platform
**Built for the Google Cloud Financial Services & InsurTech Challenge**

---

## 📌 Executive Summary
**OmniClaim AI** solves one of the most expensive and time-consuming bottlenecks in modern financial services: **insurance claims adjudication and claims fraud prevention**. 

Globally, property & casualty insurance fraud exceeds **$308 billion annually**, while legitimate policyholders wait an average of **10 to 14 days** for manual adjuster review. 

OmniClaim AI orchestrates **Gemini on Vertex AI**, **Document AI**, **Vertex AI Search (Policy RAG)**, and **BigQuery Analytics** into an end-to-end autonomous adjudication pipeline that:
- Accelerates low-risk claim settlement from **11.4 days down to under 15 seconds** (Straight-Through Processing).
- Cross-examines multimodal damage photos against line-item repair invoices to catch invoice inflation, phantom damage, and recycled photos.
- Evaluates complex policy terms and exclusions in real time with vector citations.
- Empowers adjusters with an interactive workbench and a context-aware **Gemini Claims Copilot**.

---

## 🏗️ Google Cloud Architecture & Technology Mapping

```
                                  [ MULTIMODAL INGESTION ]
                                             │
                                    ┌────────┴────────┐
                                    ▼                 ▼
                              Damage Photos      Estimates, Bills &
                             (JPEG/PNG/EXIF)     Crash Reports (PDF)
                                    │                 │
                                    ▼                 ▼
                             [ Cloud Pub/Sub Topic: claims.ingest.multimodal ]
                                             │
                                             ▼
                             [ Cloud Run: OmniClaim Core Engine ]
                                             │
        ┌────────────────────────────┼────────────────────────────┐
        ▼                            ▼                            ▼
[ Google Cloud Document AI ]  [ Vertex AI Search (RAG) ]   [ BigQuery Analytics ]
 • Specialized Invoice Parser   • Indexed Policy Corpus      • 250k+ Historical Claims
 • Entity & OCR Extraction      • text-embedding-005         • Labor Rate Percentiles
 • Key-Value Pairs              • Clause & Exclusion Match   • Provider Fraud Network
        │                            │                            │
        └────────────────────────────┼────────────────────────────┘
                                     ▼
                    [ Gemini on Vertex AI (2.0 Flash / 1.5 Pro) ]
                     • Multimodal Damage Segmentation
                     • Forensic Vision vs Invoice Discrepancy Check
                     • Step-by-Step Risk Scoring & Decision Tree
                     • Empathetic Claimant Letter Drafting
                                     │
                                     ▼
                      [ Adjudication & Triage Decision ]
                                     │
           ┌─────────────────────────┼─────────────────────────┐
           ▼                         ▼                         ▼
   [ Auto-Approval ]        [ Adjuster Review ]       [ SIU Escalation ]
   • Risk Score < 15        • Risk Score 15-60        • Risk Score > 60
   • Instant ACH Payout     • Interactive Workbench   • Fraud Dossier & Case File
   • Under 15 Seconds       • Gemini Copilot Chat     • Regulatory NICB Export
```

### Detailed Google Cloud Service Roles:
1. **Gemini on Vertex AI (Multimodal Reasoning Engine)**:
   - Evaluates visual damage severity directly from high-resolution imagery and cross-references it with invoiced repair operations (e.g. flagging invoiced suspension replacements when visual photos demonstrate only superficial bumper paint scratches).
   - Generates transparent, human-readable forensic reasoning and automatically writes legally compliant, empathetic Explanation of Benefits (EOB) letters for claimants.
2. **Document AI (Intelligent Document Processing)**:
   - Ingests scanned garage repair estimates, emergency plumbing remediation invoices, ACORD claim forms, and police incident reports.
   - Extracts structured tables, labor hourly rates, part descriptions, and provider licensing identifiers.
3. **Vertex AI Search / Agent Builder (Policy RAG Engine)**:
   - Semantically indexes complex insurance policy contracts, endorsements, deductibles, and exclusions.
   - Detects coverage applicability (e.g. verifying collision deductibles or detecting commercial livery/rideshare exclusions in real time).
4. **BigQuery (Transaction & Risk Graph Analytics)**:
   - Houses over 250,000 historical regional claims.
   - Computes statistical cost distributions (median, 75th percentile, 99th percentile) and tracks provider historical fraud rates and claimant 365-day claim velocity.
5. **Cloud Pub/Sub & Cloud Run**:
   - Decoupled, serverless asynchronous processing ensuring guaranteed message ingestion and sub-second scaling.

---

## 🚀 Key Features & Capabilities

| Capability | Legacy Industry Workflow | OmniClaim AI Solution |
| :--- | :--- | :--- |
| **Claim Processing Speed** | 10 - 14 business days | **Under 15 seconds** for auto-approval |
| **Estimate Fraud Detection** | Manual sample audits (catches < 12%) | **100% itemized audit** via Document AI & Gemini Vision |
| **Recycled Photo Detection** | Rarely detected | **Perceptual hashing & EXIF metadata integrity check** |
| **Policy Exclusion Checks** | Manual reading of 40-page policies | **Instant vector clause retrieval** with exact citations |
| **Customer Communications** | Generic boilerplates or delays | **Empathetic AI-drafted letters** explaining adjustments clearly |

---

## 🧪 Pre-Loaded Demonstration Scenarios

1. **Auto Collision - Inflated Estimate & Part Mismatch (`CLM-9042`)**:
   - *Scenario*: Claimant submits bumper scratch, but body shop invoices $8,450 for complete rear axle and suspension replacement.
   - *Outcome*: Gemini flags critical discrepancy; Document AI disallows $7,200 in unsupported parts; authorizes adjusted settlement of $750.
2. **Water Damage Homeowners Claim - Fast-Track Approval (`CLM-8819`)**:
   - *Scenario*: Freezing temperature pipe burst behind kitchen ceiling with emergency plumbing invoice.
   - *Outcome*: Verified against Policy HO-SEC-1.C; 8/100 risk score; **Instant ACH auto-approval ($2,950)** in 2.3 seconds.
3. **Staged Syndicate Collision - Recycled Damage Photo (`CLM-9104`)**:
   - *Scenario*: Alleged single-car total loss on BMW M4 bound 6 days prior to claim.
   - *Outcome*: Perceptual hashing matches salvaged vehicle auction lot from Georgia 14 months prior. **Escalated to SIU with 96/100 fraud score**.
4. **Severe Hailstorm Glass Replacement (`CLM-8750`)**:
   - *Scenario*: Windshield star crack during convective hail cell.
   - *Outcome*: NOAA weather radar correlation via BigQuery; NAGS pricing schedule validation; **Auto-approved in 1.9s ($680)**.
5. **Commercial Rideshare Exclusion Dispute (`CLM-9231`)**:
   - *Scenario*: Claimant asserts personal commute collision, but Document AI highlights police report notes of active rideshare fare.
   - *Outcome*: Triggers Exclusion 4.B; automatically reroutes claimant to rideshare platform commercial policy.

---

## 🔑 Live Google Cloud & Vertex AI Integration

OmniClaim AI supports both **real live Google Cloud API calls** and zero-config local benchmark execution.

### Official SDKs Installed in `.venv`:
- `google-genai` (v1.47.0): Official Google GenAI SDK for Gemini 2.0 Flash and 1.5 Pro multimodal generation.
- `google-cloud-documentai` (v3.14.0): Official Document AI client for Form and Invoice parsing.
- Direct HTTPS fallback: Pure standard library execution with zero dependencies if running in minimal container environments.

### 2 Ways to Connect Your API Key:

#### Option A: Directly in the Web UI (Instant)
1. Open the app at `http://localhost:8080/index.html`.
2. Click **"GCP Live Key"** in the top navigation bar.
3. Paste your Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey) or Google Cloud Console.
4. Click **"Test Live Connection ⚡"** to verify latency and model response.
5. Click **"Save & Connect"**. The live indicator will pulse cyan, and Gemini 2.0 is immediately active!

#### Option B: Environment Variables or `.env` File
Create a `.env` file in the project root:
```bash
# Get your key from: https://aistudio.google.com/app/apikey
GEMINI_API_KEY=AIzaSyYourGeminiApiKeyHere

# Optional for Vertex AI enterprise endpoints
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=us-central1
DOCUMENT_AI_PROCESSOR_ID=projects/123/locations/us/processors/abc
GEMINI_MODEL=gemini-2.0-flash
```

---

## 💻 Local Installation & Quickstart

```bash
# 1. Navigate to the project root
cd /Users/danielahmed/Documents/Codex/2026-09-20/omniclaim-ai

# 2. Run the application server with the configured environment:
.venv/bin/python3 server.py

# 3. Open your browser and navigate to:
http://localhost:8080/index.html
```

---

## 📡 REST API Reference

- `GET /api/config`: Current GCP integration status, client library availability, and masked API key.
- `POST /api/config`: Updates API keys, project ID, location, or Document AI processor ID.
- `POST /api/config/test`: Tests the live connection against Gemini 2.0 and returns latency.
- `GET /api/health`: System health and status of Google Cloud microservices.
- `GET /api/claims`: Retrieves all active claims in the triage queue.
- `GET /api/claims/{id}`: Detailed multimodal inspection data for a specific claim.
- `POST /api/claims/analyze`: Ingests and runs live Gemini 2.0 multimodal reasoning for new claims.
- `POST /api/claims/{id}/action`: Adjuster decision recording (Approve, Adjust, SIU Escalate).
- `POST /api/claims/{id}/copilot`: Live conversational reasoning endpoint powered by Gemini 2.0.
- `GET /api/benchmarks`: BigQuery cohort analytics and regional labor rate percentiles.
- `GET /api/architecture`: Pipeline definition and Google Cloud architectural node data.

---

## 🏆 Innovation & Hackathon Alignment
OmniClaim AI directly solves the problem statement by demonstrating a tangible, production-grade financial services architecture where Google Cloud's AI suite works cohesively to deliver real economic value: preventing financial losses and providing an exceptional claimant experience.
