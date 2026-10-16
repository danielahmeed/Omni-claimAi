"""Optional: Document AI Invoice Parser for repair bills.

When DOCUMENT_AI_PROCESSOR is set (projects/PROJECT/locations/us/processors/ID,
an Invoice Parser processor), every uploaded bill is first read by Document AI.
Its line items, totals, vendor and invoice number are stored on the claim and
passed to Gemini, which uses them as the reading of the bill and judges each
line against the photo. If Document AI fails, Gemini reads the bill on its own
and the failure is shown in the analysis log and on the status page.

The client uses the REST transport, so no gRPC runtime is needed.
"""

import re
import threading
import time

from .config import DOCUMENT_AI_PROCESSOR, DOCUMENT_AI_TIMEOUT_SECONDS

PROCESSOR_NAME = re.compile(
    r"^projects/([^/]+)/locations/([a-z0-9-]+)/processors/([A-Za-z0-9]+)(?:/processorVersions/[A-Za-z0-9._-]+)?$")
SUPPORTED_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/webp", "image/tiff", "image/gif", "image/bmp"}
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
MAX_LINE_ITEMS = 60


class DocumentAIError(Exception):
    """Document AI could not process the document. The message is safe to show."""


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def parse_amount(text: str) -> float | None:
    match = _NUMBER.search((text or "").replace(" ", ""))
    if not match:
        return None
    try:
        return round(float(match.group(0).replace(",", "")), 2)
    except ValueError:
        return None


def _money(entity) -> float | None:
    """Amount from the parser's normalized value, falling back to the printed text."""
    value = entity.normalized_value
    money = value.money_value
    if money.units or money.nanos:
        return round(money.units + money.nanos / 1e9, 2)
    if value.float_value:
        return round(value.float_value, 2)
    return parse_amount(value.text or entity.mention_text)


def _date(entity) -> str | None:
    date = entity.normalized_value.date_value
    if date.year and date.month and date.day:
        return f"{date.year:04d}-{date.month:02d}-{date.day:02d}"
    return _clean(entity.mention_text) or None


def parse_document(document) -> dict:
    """Turn a documentai.Document from the Invoice Parser into plain data."""
    result = {"vendor": None, "total": None, "currency": None, "invoiceId": None, "invoiceDate": None,
              "lineItems": [], "pages": len(document.pages)}
    for entity in document.entities:
        kind = entity.type_
        if kind == "supplier_name" and not result["vendor"]:
            result["vendor"] = _clean(entity.mention_text)[:120] or None
        elif kind == "total_amount":
            result["total"] = _money(entity)
            if entity.normalized_value.money_value.currency_code and not result["currency"]:
                result["currency"] = entity.normalized_value.money_value.currency_code
        elif kind == "currency" and not result["currency"]:
            result["currency"] = _clean(entity.mention_text)[:10] or None
        elif kind == "invoice_id" and not result["invoiceId"]:
            result["invoiceId"] = _clean(entity.mention_text)[:60] or None
        elif kind == "invoice_date" and not result["invoiceDate"]:
            result["invoiceDate"] = _date(entity)
        elif kind == "line_item" and len(result["lineItems"]) < MAX_LINE_ITEMS:
            props = {p.type_.split("/")[-1]: p for p in entity.properties}
            description = _clean(props["description"].mention_text if "description" in props else entity.mention_text)
            amount = _money(props["amount"]) if "amount" in props else None
            quantity = parse_amount(props["quantity"].mention_text) if "quantity" in props else None
            unit_price = _money(props["unit_price"]) if "unit_price" in props else None
            if amount is None and quantity is not None and unit_price is not None:
                amount = round(quantity * unit_price, 2)
            if description:
                result["lineItems"].append({"description": description[:300], "amount": amount,
                                            "quantity": quantity, "unitPrice": unit_price})
    return result


def describe_error(exc: Exception, processor: str) -> str:
    try:
        from google.api_core import exceptions as api
    except ImportError:  # pragma: no cover
        api = None
    try:
        import google.auth.exceptions as auth_errors
    except ImportError:  # pragma: no cover
        auth_errors = None
    message = str(getattr(exc, "message", "") or exc)
    # REST errors start with "POST https://...: "; keep only the explanation.
    message = re.sub(r"^(GET|POST|PUT|PATCH|DELETE) \S+: ", "", message)[:300]
    # The REST transport raises HTTP-style errors (Forbidden, BadRequest, ...),
    # the gRPC transport raises the gRPC-style ones; handle both.
    if api and isinstance(exc, (api.PermissionDenied, api.Forbidden, api.Unauthorized, api.Unauthenticated)):
        return (f"Document AI denied the request: {message}. Grant the service account the Document AI API User role "
                "(roles/documentai.apiUser) and enable documentai.googleapis.com.")
    if api and isinstance(exc, api.NotFound):
        return f"Document AI processor not found ({processor}). Check DOCUMENT_AI_PROCESSOR. ({message})"
    if api and isinstance(exc, (api.InvalidArgument, api.BadRequest)):
        return f"Document AI could not process this file: {message}"
    if api and isinstance(exc, (api.ResourceExhausted, api.TooManyRequests)):
        return f"Document AI quota reached. Try again later. ({message})"
    if api and isinstance(exc, (api.DeadlineExceeded, api.GatewayTimeout, api.ServiceUnavailable,
                                api.InternalServerError)):
        return f"Document AI is temporarily unavailable. ({message})"
    if auth_errors and isinstance(exc, auth_errors.DefaultCredentialsError):
        return ("No Google Cloud credentials found for Document AI. Locally, run `gcloud auth application-default login`; "
                "on Cloud Run, use a service account with the Document AI API User role.")
    return f"{type(exc).__name__}: {message}"


class DocumentAIService:
    def __init__(self, processor: str = DOCUMENT_AI_PROCESSOR, client_factory=None,
                 timeout_s: int = DOCUMENT_AI_TIMEOUT_SECONDS):
        self.processor = (processor or "").strip()
        self._match = PROCESSOR_NAME.match(self.processor) if self.processor else None
        self._factory = client_factory or self._default_client
        self._timeout_s = timeout_s
        self._client = None
        self._lock = threading.Lock()
        if not self.processor:
            self._status = {"state": "not_configured", "detail": "", "lastLatencyMs": None}
        elif not self._match:
            self._status = {"state": "error", "lastLatencyMs": None,
                            "detail": "DOCUMENT_AI_PROCESSOR must look like projects/PROJECT/locations/us/processors/ID."}
        else:
            self._status = {"state": "configured", "detail": f"Processor {self.processor}; not called yet.",
                            "lastLatencyMs": None}

    def configured(self) -> bool:
        return bool(self._match)

    @staticmethod
    def _default_client(location: str):
        from google.api_core.client_options import ClientOptions
        from google.cloud import documentai

        return documentai.DocumentProcessorServiceClient(
            client_options=ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com"), transport="rest")

    def _get_client(self):
        with self._lock:
            if self._client is None:
                self._client = self._factory(self._match.group(2))
            return self._client

    def _record(self, state: str, detail: str, latency_ms: int | None = None):
        with self._lock:
            self._status = {"state": state, "detail": detail, "lastLatencyMs": latency_ms}

    def status(self) -> dict:
        with self._lock:
            status = dict(self._status)
        if status["state"] == "not_configured":
            status["detail"] = "Gemini reads bills directly. Set DOCUMENT_AI_PROCESSOR to add the Invoice Parser."
        return status

    def extract(self, data: bytes, mime_type: str) -> dict:
        if not self.configured():
            raise DocumentAIError("Document AI is not configured.")
        if mime_type not in SUPPORTED_MIME_TYPES:
            raise DocumentAIError(f"Document AI does not accept {mime_type} files.")
        from google.cloud import documentai

        started = time.perf_counter()
        try:
            request = documentai.ProcessRequest(
                name=self.processor, raw_document=documentai.RawDocument(content=data, mime_type=mime_type))
            response = self._get_client().process_document(request=request, timeout=self._timeout_s)
            extraction = parse_document(response.document)
        except Exception as exc:
            message = describe_error(exc, self.processor)
            self._record("error", message)
            raise DocumentAIError(message) from exc
        latency_ms = round((time.perf_counter() - started) * 1000)
        extraction["latencyMs"] = latency_ms
        extraction["processor"] = self._match.group(3)
        self._record("active", f"Processor {self._match.group(3)} ({self._match.group(2)}); last document "
                               f"{latency_ms} ms, {len(extraction['lineItems'])} line items.", latency_ms)
        return extraction
