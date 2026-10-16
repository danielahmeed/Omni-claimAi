# API reference

All endpoints are under `/api`. Responses are JSON. Errors look like `{"error": "message", "field": "fieldName"}`, where `field` appears only for validation errors.

POST requests must send `Content-Type: application/json`; anything else gets **415**. Bodies are limited to 256 KB, except new claims (two files of up to `MAX_UPLOAD_MB` each, base64-encoded).

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Liveness check: `{"status": "ok"}` |
| GET | `/api/status` | AI connection state, integrations, decision rules, claim counts |
| GET | `/api/config` | Current AI settings (the key is masked) |
| POST | `/api/config` | Change AI settings (local only; **403** on Cloud Run) |
| POST | `/api/config/test` | Make a small Gemini call and report latency or the error |
| GET | `/api/claims` | All claims, newest first |
| POST | `/api/claims` | Submit and analyze a new claim |
| GET | `/api/claims/{id}` | One claim, plus `related` counts across the workspace |
| GET | `/api/claims/{id}/photo` | The stored photo (JPEG, metadata removed) |
| GET | `/api/claims/{id}/document` | The stored bill (JPEG or PDF) |
| POST | `/api/claims/{id}/decision` | Record an adjuster decision |
| POST | `/api/claims/{id}/copilot` | Ask the copilot about a claim |
| POST | `/api/admin/reset` | Restore the sample data (local only; **403** on Cloud Run) |

`POST /api/claims/analyze` and `POST /api/claims/{id}/action` are kept as aliases for older clients.

## Submit a claim

`POST /api/claims`

```json
{
  "claimantName": "Aaron Mitchell",
  "policyNumber": "POL-AUTO-31877",
  "product": "auto",
  "lossType": "Collision: scrape against a parking garage pillar",
  "incidentDate": "2026-10-14",
  "incidentLocation": "Oakland, CA",
  "claimedAmount": 8450,
  "deductible": "",
  "description": "Scraped the left rear wheel arch against a concrete pillar...",
  "photo": { "name": "scrape.jpg", "type": "image/jpeg", "data": "<base64>" },
  "document": { "name": "invoice.pdf", "type": "application/pdf", "data": "<base64>" }
}
```

| Field | Rules |
| --- | --- |
| `claimantName` | Required, 2-80 characters |
| `policyNumber` | Required, letters, digits and dashes, 3-40 characters |
| `product` | `auto` or `home` |
| `lossType` | Required, 3-120 characters |
| `incidentDate` | Required, `YYYY-MM-DD`, not in the future |
| `incidentLocation` | Optional, up to 120 characters |
| `claimedAmount` | Required, 1 to 5,000,000 |
| `deductible` | Optional, 0 to 100,000. When empty, the deductible comes from the policy register (or 500). |
| `description` | Required, 10-2000 characters |
| `photo` | Optional. JPEG, PNG or WebP. A `data:` URL prefix is accepted. |
| `document` | Optional. JPEG, PNG, WebP or PDF. |

Responses:
- **201** with the full claim (see [ARCHITECTURE.md](ARCHITECTURE.md#data-model-a-claim)).
- **400** with `field` set when the input is invalid, for example `{"error": "Photo is not a readable image...", "field": "photo"}`.
- **429** when the per-client rate limit is reached.

```bash
curl -s -X POST http://localhost:8080/api/claims \
  -H "Content-Type: application/json" \
  -d '{"claimantName":"Ann Lee","policyNumber":"POL-AUTO-31877","product":"auto","lossType":"Collision","incidentDate":"2026-10-14","claimedAmount":900,"description":"Low-speed bump in a car park."}'
```

## Record a decision

`POST /api/claims/{id}/decision`

```json
{ "action": "APPROVE_RECOMMENDED", "notes": "Optional note" }
```

| `action` | Effect |
| --- | --- |
| `APPROVE_RECOMMENDED` | Status `APPROVED`, approved amount = recommended amount |
| `APPROVE_FULL` | Status `APPROVED`, approved amount = claimed amount |
| `REFER_SIU` | Status `SIU_ESCALATED`, payment on hold |
| `DENY` | Status `DENIED`, payment 0 |

Returns the updated claim with a recomputed `settlement` and `letter`. Older names (`APPROVE`, `APPROVE_ADJUSTED`, `ESCALATE_SIU`, `REJECT`) are still accepted.

## Ask the copilot

`POST /api/claims/{id}/copilot`

```json
{ "question": "Which billed lines are not supported by the photo?",
  "history": [ { "role": "user", "text": "previous question" }, { "role": "model", "text": "previous answer" } ] }
```

The response is one of:
- `{"answer": "...", "engine": "gemini", "model": "gemini-3.8-flash", "latencyMs": 2100}`
- `{"answer": "...", "engine": "demo", "notice": null}`, a template answer built from the claim data when Gemini is not configured or fails

Only the last six history turns are used.

## Status

`GET /api/status` (shortened):

```json
{
  "version": "2.1.0",
  "runtime": { "cloudRun": true, "service": "omniclaim-ai", "revision": "omniclaim-ai-00003-abc" },
  "ai": { "state": "live", "backend": "vertex", "model": "gemini-3.8-flash", "location": "global",
          "lastLatencyMs": 5200, "lastError": null },
  "settings": { "writable": false, "dataResetAllowed": false },
  "rules": { "autoApproveMaxRisk": 19, "siuMinRisk": 80, "duplicatePhotoMaxDistance": 6, "newPolicyAlertDays": 14, "maxUploadMb": 10 },
  "integrations": [ { "id": "gemini", "name": "Gemini on Vertex AI", "state": "active", "detail": "...", "role": "..." } ]
}
```

`integrations[].id` is one of `gemini`, `cloud-run`, `photo-checks`, `document-ai`, `bigquery`, `storage`, `vertex-search` or `pubsub`. Each has a `state`:
- `active`: working
- `configured`: set up, not used yet
- `error`: see `detail`
- `not_configured`
- `local`: the built-in fallback is in use
- `planned`

`ai.state` is one of:
- `not_configured`: demo mode
- `configured`: set up, not called yet
- `live`: the last call succeeded
- `error`: the last call failed, and `lastError` says why

## Configure (local only)

`POST /api/config`

```json
{ "backend": "vertex", "project": "my-project", "location": "global", "model": "gemini-3.8-flash", "thinkingLevel": "LOW" }
```

```json
{ "backend": "api-key", "apiKey": "..." }
```

An empty or missing `apiKey` keeps the saved key. `{"clearApiKey": true}` removes it. Returns the same object as `GET /api/config`, which never includes the key itself.
