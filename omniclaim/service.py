"""The claim pipeline and the operations the HTTP API exposes."""

import base64
import binascii
import hashlib
import json
import logging
import os
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta

from . import __version__, adjudication, benchmarks, checks, demo_engine, imaging, policies, prompts
from .ai import AIError, GeminiService
from .docai import DocumentAIError, DocumentAIService
from .config import (ALLOW_DATA_RESET, AUTO_APPROVE_MAX_RISK, BASE_DIR, DUPLICATE_PHOTO_MAX_DISTANCE, MAX_UPLOAD_MB,
                     NEW_POLICY_ALERT_DAYS, ON_CLOUD_RUN, SEED_DIR, SIU_MIN_RISK, SUPPORTED_MODELS, Settings,
                     mask_secret)
from .schemas import ClaimAssessment
from .store import ClaimStore

log = logging.getLogger("omniclaim")

SEVERITY_RANK = {"CRITICAL": 0, "MEDIUM": 1, "INFO": 2}
ENGINE_LABELS = {
    "gemini": "Gemini",
    "recorded-demo": "Recorded demo result",
    "demo-generic": "Demo mode: not analyzed by AI",
    "sample": "Sample scenario (pre-recorded assessment)",
}
_POLICY_NUMBER = re.compile(r"^[A-Z0-9][A-Z0-9-]{2,39}$")


class SubmissionError(ValueError):
    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.field = field


class NotFound(LookupError):
    pass


@dataclass
class Upload:
    name: str
    mime: str
    data: bytes


class StepTimer:
    def __init__(self):
        self.steps: list[dict] = []
        self.started = time.perf_counter()

    @contextmanager
    def step(self, name: str):
        entry = {"name": name, "status": "done", "detail": "", "ms": 0}
        started = time.perf_counter()
        try:
            yield entry
        except Exception:
            entry["status"] = "failed"
            raise
        finally:
            entry["ms"] = round((time.perf_counter() - started) * 1000)
            self.steps.append(entry)

    def total_ms(self) -> int:
        return round((time.perf_counter() - self.started) * 1000)


# -- input validation -----------------------------------------------------------

def _text(payload: dict, key: str, label: str, min_len: int, max_len: int, required: bool = True) -> str:
    value = payload.get(key)
    value = "" if value is None else str(value).strip()
    if not value and required:
        raise SubmissionError(f"{label} is required.", key)
    if value and len(value) < min_len:
        raise SubmissionError(f"{label} is too short.", key)
    if len(value) > max_len:
        raise SubmissionError(f"{label} must be at most {max_len} characters.", key)
    return value


def _number(payload: dict, key: str, label: str, minimum: float, maximum: float, required: bool = True):
    value = payload.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise SubmissionError(f"{label} is required.", key)
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise SubmissionError(f"{label} must be a number.", key) from None
    if number != number or number < minimum or number > maximum:  # NaN or out of range
        raise SubmissionError(f"{label} must be between {minimum:,.0f} and {maximum:,.0f}.", key)
    return round(number, 2)


def _upload(payload: dict, key: str, label: str) -> Upload | None:
    value = payload.get(key)
    if not value:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("data"), str):
        raise SubmissionError(f"{label} upload is malformed.", key)
    data = value["data"]
    if data.startswith("data:") and "," in data:
        data = data.split(",", 1)[1]
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise SubmissionError(f"{label} upload is not valid base64.", key) from None
    if len(raw) > MAX_UPLOAD_MB * 1024 * 1024:
        raise SubmissionError(f"{label} is larger than {MAX_UPLOAD_MB} MB.", key)
    name = os.path.basename(str(value.get("name") or key))[:100] or key
    return Upload(name=name, mime=str(value.get("type") or "")[:100], data=raw)


def parse_submission(payload: dict) -> tuple[dict, Upload | None, Upload | None]:
    if not isinstance(payload, dict):
        raise SubmissionError("Request body must be a JSON object.")
    product = str(payload.get("product") or "auto").strip().lower()
    if product not in policies.PRODUCTS:
        raise SubmissionError("Product must be 'auto' or 'home'.", "product")
    policy_number = _text(payload, "policyNumber", "Policy number", 3, 40).upper()
    if not _POLICY_NUMBER.match(policy_number):
        raise SubmissionError("Policy number may contain only letters, digits and dashes.", "policyNumber")
    incident_raw = _text(payload, "incidentDate", "Incident date", 10, 10)
    incident = policies.parse_date(incident_raw)
    if not incident:
        raise SubmissionError("Incident date must be a date (YYYY-MM-DD).", "incidentDate")
    if incident > date.today() + timedelta(days=1) or incident.year < 1990:
        raise SubmissionError("Incident date cannot be in the future.", "incidentDate")
    claimed = _number(payload, "claimedAmount", "Amount claimed", 1, 5_000_000)
    deductible = _number(payload, "deductible", "Deductible", 0, 100_000, required=False)
    form = {
        "claimantName": _text(payload, "claimantName", "Claimant name", 2, 80),
        "policyNumber": policy_number,
        "product": product,
        "lossType": _text(payload, "lossType", "Loss type", 3, 120),
        "incidentDate": incident.isoformat(),
        "incidentLocation": _text(payload, "incidentLocation", "Location", 2, 120, required=False),
        "claimedAmount": claimed,
        "deductible": deductible,
        "description": _text(payload, "description", "Description", 10, 2000),
    }
    return form, _upload(payload, "photo", "Photo"), _upload(payload, "document", "Document")


def _sort_findings(findings: list[dict]) -> list[dict]:
    return sorted(findings, key=lambda f: SEVERITY_RANK.get(f["severity"], 3))


# -- the service ----------------------------------------------------------------

class ClaimService:
    def __init__(self, store: ClaimStore, gemini: GeminiService, settings: Settings,
                 docai: DocumentAIService | None = None, store_status: dict | None = None):
        self.store = store
        self.gemini = gemini
        self.settings = settings
        self.docai = docai or DocumentAIService(processor="")
        self.store_status = store_status or {"state": "local", "detail": "Local JSON file on the server (data/runtime)."}

    def initialize(self) -> None:
        self.store.load_or_seed(self._seed)

    def reset(self) -> None:
        if not ALLOW_DATA_RESET:
            raise PermissionError("Resetting data is disabled on this server.")
        self.store.reset(self._seed)

    def _seed(self, store: ClaimStore) -> None:
        seeds = json.loads((SEED_DIR / "claims.json").read_text(encoding="utf-8"))
        for seed in sorted(seeds, key=lambda s: s["createdAt"]):
            photo = None
            if seed.get("photo"):
                path = BASE_DIR / seed["photo"]
                photo = Upload(name=path.name, mime="image/jpeg", data=path.read_bytes())
            claim = self._build(dict(seed["form"]), photo, None, sample=seed)
            log.info("Seeded sample claim %s (%s)", claim["id"], claim["status"])

    # -- analysis pipeline ----------------------------------------------------

    def analyze(self, payload: dict) -> dict:
        form, photo, document = parse_submission(payload)
        return self._build(form, photo, document)

    def _build(self, form: dict, photo: Upload | None, document: Upload | None, sample: dict | None = None) -> dict:
        timer = StepTimer()
        existing_id = sample["id"] if sample else None  # new claims get a number once they are ready to save
        created_at = sample["createdAt"] if sample else adjudication.now_iso()
        incident = policies.parse_date(form["incidentDate"])
        policy = policies.lookup(form["policyNumber"])
        category = benchmarks.infer_category(form["product"], form["lossType"], form["description"])
        deductible = form["deductible"] if form.get("deductible") is not None else policies.default_deductible(policy, category)
        check_findings: list[dict] = []

        photo_info, photo_for_ai, processed_photo = None, None, None
        with timer.step("Photo checks") as step:
            if photo:
                try:
                    processed_photo = imaging.process_photo(photo.data)
                except imaging.InvalidUpload as exc:
                    raise SubmissionError(str(exc), "photo") from None
                matches = checks.find_photo_matches(processed_photo.dhash, self.store.photo_index(), exclude_id=existing_id)
                photo_info = {"fileName": photo.name, "width": processed_photo.width, "height": processed_photo.height,
                              "dhash": processed_photo.dhash, "metadata": processed_photo.metadata,
                              "matches": matches, "file": None}
                photo_for_ai = processed_photo.jpeg
                check_findings += checks.photo_findings(processed_photo.metadata, matches, incident)
                step["detail"] = (f"{len(matches)} earlier claim(s) with a matching photo" if matches
                                  else "No matching photo in earlier claims") + \
                                 ("; camera metadata found" if processed_photo.metadata.get("hasExif") else "; no camera metadata")
            else:
                step["status"], step["detail"] = "skipped", "No photo submitted"

        document_info, document_for_ai, stored_document, document_mime = None, None, None, None
        with timer.step("Document checks") as step:
            if document:
                sha = hashlib.sha256(document.data).hexdigest()
                if imaging.is_pdf(document.data):
                    document_mime = "application/pdf"
                    document_for_ai = (document.data, "application/pdf")
                    stored_document = (document.data, "pdf", "application/pdf")
                else:
                    try:
                        processed_doc = imaging.process_document_image(document.data)
                    except imaging.InvalidUpload as exc:
                        raise SubmissionError(f"{exc} PDFs are also accepted.", "document") from None
                    document_mime = imaging.IMAGE_FORMATS[processed_doc.source_format]
                    document_for_ai = (processed_doc.jpeg, "image/jpeg")
                    stored_document = (processed_doc.jpeg, "jpg", "image/jpeg")
                matches = checks.find_document_matches(sha, self.store.document_index(), exclude_id=existing_id)
                document_info = {"fileName": document.name, "sha256": sha, "matches": matches, "file": None,
                                 "mimeType": stored_document[2]}
                check_findings += checks.document_findings(matches)
                step["detail"] = ("Same file found in an earlier claim" if matches else "Document not seen before") + \
                                 (" (PDF)" if stored_document[1] == "pdf" else "")
            else:
                step["status"], step["detail"] = "skipped", "No document submitted"

        docai_result = None
        if document_info and self.docai.configured():
            with timer.step("Document AI extraction") as step:
                try:
                    docai_result = self.docai.extract(document.data, document_mime)
                    document_info["documentAi"] = docai_result
                    total = docai_result.get("total")
                    step["detail"] = (f"Invoice Parser read {len(docai_result['lineItems'])} line item(s)"
                                      + (f", total ${total:,.2f}" if total is not None else ""))
                except DocumentAIError as exc:
                    step["status"], step["detail"] = "failed", str(exc)
                    log.warning("Document AI extraction failed: %s", exc)

        with timer.step("Policy and cost checks") as step:
            policy_info, policy_findings = checks.policy_check(policy, form["product"], form["claimantName"], incident)
            benchmark = benchmarks.compute(category, form["claimedAmount"])
            check_findings += policy_findings + checks.benchmark_findings(benchmark, form["claimedAmount"])
            step["detail"] = (("Policy found" if policy else "Policy not in register") +
                              f"; amount at the {benchmark['claimPercentile']:.0f}th percentile of "
                              f"{benchmark['sampleSize']:,} similar claims ({benchmark['source']})")

        automated_checks = {
            "photo_metadata": photo_info["metadata"] if photo_info else None,
            "reused_photo_matches": photo_info["matches"] if photo_info else [],
            "reused_document_matches": document_info["matches"] if document_info else [],
            "policy_check": policy_info,
            "cost_benchmark": {k: benchmark[k] for k in ("categoryLabel", "sampleSize", "median", "p75", "p95",
                                                          "claimPercentile")},
            "findings": [{k: f[k] for k in ("title", "severity", "detail")} for f in check_findings],
        }
        if docai_result:
            automated_checks["document_ai_extraction"] = {
                k: docai_result[k] for k in ("vendor", "invoiceId", "invoiceDate", "currency", "total", "lineItems")}

        engine, notice, model, backend = None, None, None, None
        assessment: ClaimAssessment | None = None
        if sample:
            with timer.step("AI assessment") as step:
                assessment, engine = ClaimAssessment.model_validate(sample["assessment"]), "sample"
                step["detail"] = "Pre-recorded sample assessment (no live AI call for sample claims)"
        elif self.gemini.is_configured(self.gemini.settings()):
            with timer.step("Gemini assessment") as step:
                context = prompts.assessment_context(
                    {**form, "deductible": deductible, "loss_category": benchmark["categoryLabel"]},
                    automated_checks, policies.form_for(form["product"]), policy)
                try:
                    assessment, latency_ms, used = self.gemini.assess_claim(context, photo_for_ai, document_for_ai)
                    engine, model, backend = "gemini", used.model, used.backend
                    step["detail"] = f"{used.model} via {'Vertex AI' if used.backend == 'vertex' else 'Gemini API'}"
                except AIError as exc:
                    step["status"], step["detail"] = "failed", str(exc)
                    notice = f"The Gemini call failed, so demo mode was used instead. {exc}"
                    log.warning("Gemini assessment failed for a claim by %s: %s", form["claimantName"], exc)
        if assessment is None:
            with timer.step("Demo assessment") as step:
                recorded = demo_engine.recorded_assessment(
                    document_info["sha256"] if document_info else None,
                    photo_info["dhash"] if photo_info else None)
                if recorded:
                    assessment, engine = recorded[0], "recorded-demo"
                    step["detail"] = f"Replayed the recorded result for the sample '{recorded[1]}'"
                else:
                    assessment = demo_engine.generic_assessment(bool(photo), bool(document), docai_result)
                    engine = "demo-generic"
                    step["detail"] = ("No AI assessment; uploads were not analyzed"
                                      + ("; bill lines from Document AI held for review" if docai_result else ""))

        with timer.step("Routing and settlement") as step:
            claim_id = existing_id or self.store.next_id()
            claim = self._assemble(claim_id, created_at, form, deductible, category, assessment, engine,
                                   photo_info, document_info, policy_info, benchmark, check_findings,
                                   sample=sample)
            claim["analysis"]["notice"] = notice  # a failed Gemini call blocks auto-approval
            adjudication.finalize(claim)
            step["detail"] = f"{adjudication.STATUS_LABELS[claim['status']]}: {claim['routingReason']}"

        claim["analysis"].update({"model": model, "backend": backend, "notice": notice, "steps": timer.steps,
                                  "durationMs": timer.total_ms()})
        if engine in ("recorded-demo", "demo-generic"):
            reason = "Gemini call failed" if notice else "Gemini not configured"
            claim["analysis"]["label"] = f"{ENGINE_LABELS[engine]} ({reason})"
        claim["history"].append({"at": created_at, "event": f"Routed to {adjudication.STATUS_LABELS[claim['status']].lower()}",
                                 "by": "OmniClaim"})

        if processed_photo:
            claim["photo"]["file"] = self.store.save_file(claim_id, "photo", processed_photo.jpeg, "jpg")
        if stored_document:
            claim["document"]["file"] = self.store.save_file(claim_id, "document", stored_document[0], stored_document[1])
        if sample and sample.get("decision"):
            d = sample["decision"]
            adjudication.apply_decision(claim, d["action"], d.get("notes", ""), at=d.get("at"), by=d.get("by", "Adjuster"))
        self.store.put(claim)
        return claim

    def _assemble(self, claim_id, created_at, form, deductible, category, assessment: ClaimAssessment, engine,
                  photo_info, document_info, policy_info, benchmark, check_findings, sample=None) -> dict:
        items = adjudication.normalize_line_items(assessment)
        ai_source = {"gemini": "gemini", "recorded-demo": "recorded-demo", "sample": "sample"}.get(engine, "demo")
        ai_findings = [{"title": f.title.strip()[:120], "severity": f.severity, "detail": f.detail.strip()[:600],
                        "source": ai_source} for f in assessment.findings[:10]]
        items_total = round(sum(i["billedAmount"] for i in items), 2) if items else None
        amount_checks = checks.amount_findings(form["claimedAmount"], assessment.document_total, items_total)

        form_clauses = {c["id"]: c for c in policies.form_for(form["product"])["clauses"]}
        clauses = []
        for c in assessment.clause_assessments:
            known = form_clauses.get(c.clause_id.strip())
            if known:
                clauses.append({"clauseId": known["id"], "title": known["title"], "text": known["text"],
                                "verdict": c.verdict, "explanation": c.explanation.strip()[:500]})

        risk = max(0, min(100, int(assessment.risk_score)))
        reused = bool(photo_info and photo_info["matches"]) or bool(document_info and document_info["matches"])
        if reused:
            risk = max(risk, 90)

        if document_info is None and (items or (sample and assessment.document_type not in ("None provided", ""))):
            document_info = {"fileName": None, "sha256": None, "matches": [], "file": None, "mimeType": None}
        if document_info is not None:
            reader = {"gemini": "Gemini", "recorded-demo": "Recorded demo result", "sample": "Sample data"}.get(engine)
            if document_info.get("documentAi"):
                reader = "Document AI Invoice Parser + Gemini" if engine == "gemini" else "Document AI Invoice Parser"
            document_info.update({"type": assessment.document_type, "vendor": assessment.vendor_name,
                                  "total": assessment.document_total, "extractedBy": reader})

        regions = adjudication.damage_regions(assessment) if photo_info else []
        return {
            "id": claim_id,
            "isSample": bool(sample),
            "createdAt": created_at,
            "claimantName": form["claimantName"],
            "policyNumber": form["policyNumber"],
            "product": form["product"],
            "lossType": form["lossType"],
            "lossCategory": category,
            "incidentDate": form["incidentDate"],
            "incidentLocation": form.get("incidentLocation") or "",
            "description": form["description"],
            "claimedAmount": form["claimedAmount"],
            "deductible": deductible,
            "status": None,
            "riskScore": risk,
            "riskLevel": None,
            "riskRationale": assessment.risk_rationale.strip()[:800],
            "recommendedAction": None,
            "routingReason": None,
            "photo": photo_info,
            "illustration": (sample or {}).get("illustration"),
            "document": document_info,
            "damageSummary": assessment.photo_description.strip()[:1200],
            "damageRegions": regions,
            "lineItems": items,
            "findings": _sort_findings(check_findings + ai_findings + amount_checks),
            "coverage": {"decision": assessment.coverage_decision, "clauses": clauses,
                         "form": policies.form_for(form["product"])["name"]},
            "policy": policy_info,
            "benchmark": benchmark,
            "explanation": assessment.claimant_explanation.strip()[:1200],
            "analysis": {"engine": engine, "label": ENGINE_LABELS.get(engine, engine), "analyzedAt": created_at},
            "decision": None,
            "history": [{"at": created_at, "event": "Claim submitted", "by": "Claimant"}],
            "settlement": None,
            "letter": None,
        }

    # -- other operations ----------------------------------------------------------

    def list_claims(self) -> list[dict]:
        return self.store.all()

    def get_claim(self, claim_id: str) -> dict:
        claim = self.store.get(claim_id)
        if not claim:
            raise NotFound(f"Claim {claim_id} not found.")
        claim["related"] = self.store.related_counts(claim)
        return claim

    def claim_file(self, claim_id: str, kind: str) -> tuple[bytes, str, str]:
        claim = self.get_claim(claim_id)
        info = claim.get(kind) or {}
        data = self.store.read_file(info.get("file"))
        if data is None:
            raise NotFound(f"Claim {claim_id} has no stored {kind}.")
        mime = "image/jpeg" if kind == "photo" else (info.get("mimeType") or "application/octet-stream")
        return data, mime, info.get("fileName") or f"{claim_id}-{kind}"

    def decide(self, claim_id: str, payload: dict) -> dict:
        claim = self.get_claim(claim_id)
        claim.pop("related", None)
        action = str((payload or {}).get("action") or "").upper()
        legacy = {"APPROVE": "APPROVE_FULL", "APPROVE_ADJUSTED": "APPROVE_RECOMMENDED", "ESCALATE_SIU": "REFER_SIU",
                  "REJECT": "DENY"}
        action = legacy.get(action, action)
        if action not in adjudication.DECISIONS:
            raise SubmissionError("Unknown decision. Use APPROVE_RECOMMENDED, APPROVE_FULL, REFER_SIU or DENY.", "action")
        adjudication.apply_decision(claim, action, str((payload or {}).get("notes") or ""))
        self.store.put(claim)
        return self.get_claim(claim_id)

    def copilot(self, claim_id: str, payload: dict) -> dict:
        claim = self.get_claim(claim_id)
        question = str((payload or {}).get("question") or (payload or {}).get("query") or "").strip()
        if not question:
            raise SubmissionError("Ask a question.", "question")
        if len(question) > 1000:
            raise SubmissionError("Questions must be at most 1000 characters.", "question")
        history = (payload or {}).get("history") or []
        if not isinstance(history, list):
            history = []
        history = [h for h in history if isinstance(h, dict)][-6:]
        notice = None
        if self.gemini.is_configured(self.gemini.settings()):
            try:
                answer, latency_ms, used = self.gemini.copilot(
                    prompts.copilot_prompt(self._copilot_summary(claim), history, question))
                return {"answer": answer, "engine": "gemini", "model": used.model, "latencyMs": latency_ms}
            except AIError as exc:
                notice = f"Gemini call failed ({exc}). Showing a template answer instead."
        return {"answer": demo_engine.demo_copilot_answer(claim, question), "engine": "demo", "notice": notice}

    @staticmethod
    def _copilot_summary(claim: dict) -> dict:
        keep = ("id", "status", "claimantName", "policyNumber", "product", "lossType", "incidentDate",
                "incidentLocation", "description", "claimedAmount", "deductible", "riskScore", "riskLevel",
                "riskRationale", "recommendedAction", "routingReason", "damageSummary", "lineItems", "findings",
                "coverage", "policy", "settlement", "decision", "letter")
        summary = {k: claim.get(k) for k in keep}
        summary["benchmark"] = {k: claim["benchmark"].get(k) for k in ("categoryLabel", "sampleSize", "median", "p75",
                                                                       "p95", "claimPercentile", "dataset")}
        if claim.get("photo"):
            summary["photo"] = {"metadata": claim["photo"]["metadata"], "matches": claim["photo"]["matches"]}
        if claim.get("document"):
            summary["document"] = {k: claim["document"].get(k) for k in ("type", "vendor", "total", "matches")}
        summary["analysis"] = claim["analysis"].get("label")
        return summary

    # -- settings and status -------------------------------------------------------

    def config_view(self) -> dict:
        s = self.settings.ai()
        return {
            "writable": self.settings.writable,
            "backend": s.backend,
            "apiKeySet": bool(s.api_key),
            "apiKeyMasked": mask_secret(s.api_key),
            "project": s.project,
            "location": s.location,
            "model": s.model,
            "thinkingLevel": s.thinking_level,
            "supportedModels": SUPPORTED_MODELS,
        }

    def update_config(self, payload: dict) -> dict:
        mapping = {"backend": "backend", "apiKey": "api_key", "project": "project", "location": "location",
                   "model": "model", "thinkingLevel": "thinking_level"}
        changes = {internal: (payload or {}).get(external) for external, internal in mapping.items()
                   if external in (payload or {})}
        try:
            if (payload or {}).get("clearApiKey"):
                self.settings.clear_api_key()
            self.settings.update(changes)
        except ValueError as exc:
            raise SubmissionError(str(exc)) from None
        return self.config_view()

    def status(self) -> dict:
        ai = self.gemini.status()
        ai_state = {"live": "active", "configured": "configured", "error": "error"}.get(ai["state"], "not_configured")
        bq = benchmarks.status()
        bq_state = {"active": "active", "configured": "configured", "error": "error"}.get(bq["state"], "local")
        docai = self.docai.status()
        backend_label = "Vertex AI" if ai["backend"] == "vertex" else "Gemini API (API key)"
        if ai["state"] == "live":
            ai_detail = f"{ai['model']} via {backend_label}; last call {ai['lastLatencyMs']} ms."
        elif ai["state"] == "error":
            ai_detail = ai["lastError"] or "The last call failed."
        elif ai["configured"]:
            ai_detail = f"{ai['model']} via {backend_label}; not called yet."
        else:
            ai_detail = ai["hint"] or "Not configured; demo mode."
        claims = self.store.all()
        return {
            "version": __version__,
            "runtime": {"cloudRun": ON_CLOUD_RUN, "service": os.environ.get("K_SERVICE"),
                        "revision": os.environ.get("K_REVISION")},
            "ai": ai,
            "settings": {"writable": self.settings.writable, "dataResetAllowed": ALLOW_DATA_RESET},
            "rules": {"autoApproveMaxRisk": AUTO_APPROVE_MAX_RISK, "siuMinRisk": SIU_MIN_RISK,
                      "duplicatePhotoMaxDistance": DUPLICATE_PHOTO_MAX_DISTANCE,
                      "newPolicyAlertDays": NEW_POLICY_ALERT_DAYS, "maxUploadMb": MAX_UPLOAD_MB},
            "claims": {"total": len(claims), "samples": sum(1 for c in claims if c.get("isSample"))},
            "integrations": [
                {"id": "gemini", "name": "Gemini on Vertex AI", "state": ai_state, "detail": ai_detail,
                 "role": "Reads the damage photo and the bill, checks each line against the photo and the policy "
                         "wording, scores risk and drafts the claimant explanation."},
                {"id": "cloud-run", "name": "Cloud Run", "state": "active" if ON_CLOUD_RUN else "local",
                 "detail": (f"Service {os.environ.get('K_SERVICE')}, revision {os.environ.get('K_REVISION')}."
                            if ON_CLOUD_RUN else "Running locally with python server.py."),
                 "role": "Hosts the API and the web app in one container."},
                {"id": "photo-checks", "name": "Photo forensics", "state": "active",
                 "detail": "Camera metadata and perceptual-hash search across every stored claim.",
                 "role": "Flags reused photos, edited photos and photos taken before the incident."},
                {"id": "document-ai", "name": "Document AI Invoice Parser", "state": docai["state"],
                 "detail": docai["detail"],
                 "role": "Reads the line items, totals and vendor from each bill before Gemini checks them against "
                         "the photo."},
                {"id": "bigquery", "name": "BigQuery cost benchmarks", "state": bq_state, "detail": bq["detail"],
                 "role": "Compares the claimed amount with similar past claims."},
                {"id": "storage", "name": "Firestore and Cloud Storage", "state": self.store_status["state"],
                 "detail": self.store_status["detail"],
                 "role": "Stores claims durably across deploys and instances; photos and bills go to Cloud Storage."},
                {"id": "vertex-search", "name": "Vertex AI Search", "state": "planned",
                 "detail": "The policy wording is short enough to give to Gemini directly.",
                 "role": "Retrieval over large policy libraries."},
                {"id": "pubsub", "name": "Pub/Sub", "state": "planned",
                 "detail": "Claims are processed synchronously by the API today.",
                 "role": "Asynchronous intake at high volume."},
            ],
        }
