# Security

## Action required: revoke the old API key

An earlier version committed a Gemini API key in `data/config.json`, and the app also served that file to anyone who opened `/data/config.json`. Google has already flagged the key: calls with it fail with "Your API key was reported as leaked".

The file is deleted in this version, but the key is still in the git history and in any copy of the repository, so **revoke it**. Whoever owns the key needs to:

1. Open the [Google AI Studio API keys page](https://aistudio.google.com/app/apikey), or **APIs & Services > Credentials** in the Google Cloud console for the key's project.
2. Delete the key that starts with `AIzaSyAw`.
3. Under **Billing > Reports**, check the project for unexpected Generative Language API usage since the key was published.
4. Don't create a replacement key for the deployed app. On Cloud Run it uses Vertex AI with its service account (see [DEPLOYMENT.md](DEPLOYMENT.md)). For local experiments, put a new key in `.env` or the Settings dialog; both are git-ignored.

Rewriting git history is optional once the key is revoked: a revoked key is useless. If the team wants it removed anyway, use `git filter-repo` and coordinate a force-push with everyone who has a clone.

## How this version handles secrets

- No keys or credentials are stored in the repository. `.env`, `data/config.json` and `data/runtime/` are git-ignored.
- On Cloud Run, Gemini is called with the service account through Application Default Credentials, so there is no key to leak.
- A key entered in the Settings dialog is stored in `data/runtime/settings.json`, which is git-ignored, never served over HTTP, and not copied into the container image (see `.dockerignore`).
- `GET /api/config` returns only a masked form of the key (`••••••••1234`).
- On Cloud Run the Settings dialog and data reset are read-only by default (`ALLOW_SETTINGS_UI=false`, `ALLOW_DATA_RESET=false`).

## Other protections

| Risk | Protection |
| --- | --- |
| Reading source code, data or settings over HTTP | Static allowlist: only `index.html`, `app.js`, `styles.css` and `samples/`. Path traversal is blocked. Covered by `tests/test_http.py`. |
| Stored cross-site scripting through claim fields or AI output | The web app escapes all API text before inserting it as HTML, and the page sends a Content Security Policy with `script-src 'self'`. |
| Cross-site form posts (for example, changing local settings from another site) | Every POST must be `application/json`, which a plain HTML form cannot send cross-site. |
| Oversized or malicious uploads | Body-size limits, per-file limits, decoding with Pillow (50-megapixel cap), allowed formats only, metadata stripped from stored images. |
| Running up the AI bill through a public URL | Per-client rate limits on analysis, copilot and connection tests. Cloud Run `--max-instances 1`. |
| Clickjacking and MIME sniffing | `X-Frame-Options: DENY`, `frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`. |
| Container compromise | Runs as a non-root user; only `data/runtime` is writable. |
| Tipping off a suspected fraudster | The letter for SIU referrals never mentions fraud or risk scores. |

## Not included in this demo

The deployment is public so judges can try it. A production deployment would add:
- adjuster authentication, for example Identity-Aware Proxy
- audit logging of decisions to a write-once store
- data-retention rules for claimant personal data in Firestore and Cloud Storage
- customer-managed encryption keys, if the insurer requires them

## Service account roles

The deploy script grants the Cloud Run service account only the roles for the services you enable:

| Service | Role |
| --- | --- |
| Gemini on Vertex AI | `roles/aiplatform.user` |
| Document AI | `roles/documentai.apiUser` |
| Firestore | `roles/datastore.user` |
| Cloud Storage | `roles/storage.objectAdmin`, on the claims bucket only |
| BigQuery | `roles/bigquery.jobUser` and `roles/bigquery.dataViewer` |

Stored files are only reachable through `GET /api/claims/{id}/photo` and `/document`, by names the app generated itself. The bucket is never public.
