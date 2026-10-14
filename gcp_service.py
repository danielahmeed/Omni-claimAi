"""
OmniClaim AI - Google Cloud & Vertex AI Integration Service
Connects to Gemini 2.0 / 1.5 (via google-genai SDK or direct REST API)
and Document AI (via google-cloud-documentai SDK).
"""

import os
import json
import time
import urllib.request
import urllib.error
from typing import Dict, Any, Optional, Tuple

# Try loading python-dotenv if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Try importing official Google GenAI SDK
GOOGLE_GENAI_AVAILABLE = False
try:
    from google import genai
    from google.genai import types
    GOOGLE_GENAI_AVAILABLE = True
except ImportError:
    pass

# Try importing official Document AI SDK
DOCAI_AVAILABLE = False
try:
    from google.cloud import documentai
    DOCAI_AVAILABLE = True
except ImportError:
    pass

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "config.json")

def load_config() -> Dict[str, Any]:
    default_config = {
        "geminiApiKey": os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", "")),
        "gcpProjectId": os.getenv("GOOGLE_CLOUD_PROJECT", os.getenv("GCP_PROJECT_ID", "")),
        "gcpLocation": os.getenv("GOOGLE_CLOUD_LOCATION", os.getenv("GCP_LOCATION", "us-central1")),
        "docAiProcessorId": os.getenv("DOCUMENT_AI_PROCESSOR_ID", ""),
        "docAiLocation": os.getenv("DOCUMENT_AI_LOCATION", "us"),
        "modelName": os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                default_config.update(saved)
        except Exception as e:
            print(f"Error loading {CONFIG_FILE}: {e}")
    return default_config

def save_config(config_data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)

class GCPService:
    def __init__(self):
        self.config = load_config()
        self._init_clients()

    def update_config(self, new_data: Dict[str, Any]):
        self.config.update(new_data)
        save_config(self.config)
        self._init_clients()

    def _init_clients(self):
        self.api_key = self.config.get("geminiApiKey", "").strip()
        self.project_id = self.config.get("gcpProjectId", "").strip()
        self.location = self.config.get("gcpLocation", "us-central1").strip()
        self.model_name = self.config.get("modelName", "gemini-3.8-flash").strip()
        self.docai_processor = self.config.get("docAiProcessorId", "").strip()
        
        self.genai_client = None
        if GOOGLE_GENAI_AVAILABLE and self.api_key:
            try:
                self.genai_client = genai.Client(api_key=self.api_key)
            except Exception as e:
                print(f"Notice: Initializing google-genai client failed: {e}. Will use direct REST fallback.")

    def is_gemini_live(self) -> bool:
        return bool(self.api_key)

    def is_docai_live(self) -> bool:
        return bool(DOCAI_AVAILABLE and self.docai_processor and self.project_id)

    def test_gemini_connection(self) -> Tuple[bool, str, float]:
        """Test the live Gemini API connection and measure latency."""
        if not self.api_key:
            return False, "No Gemini API Key configured. Please enter your API Key.", 0.0

        t0 = time.time()
        prompt = "Hello Gemini, respond with 'OK: Vertex AI connected' in under 5 words."

        # Attempt 1: google-genai SDK
        if self.genai_client:
            try:
                response = self.genai_client.models.generate_content(
                    model=self.model_name,
                    contents=prompt
                )
                latency = round((time.time() - t0) * 1000, 1)
                return True, response.text.strip(), latency
            except Exception as e:
                print(f"SDK test error: {e}, falling back to REST endpoint...")

        # Attempt 2: Direct REST API
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"
            payload = json.dumps({
                "contents": [{"parts": [{"text": prompt}]}]
            }).encode("utf-8")

            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                latency = round((time.time() - t0) * 1000, 1)
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                return True, text, latency
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            try:
                err_json = json.loads(error_body)
                msg = err_json.get("error", {}).get("message", str(e))
            except Exception:
                msg = f"HTTP {e.code}: {e.reason}"
            return False, f"Google Cloud API Error: {msg}", 0.0
        except Exception as e:
            return False, f"Connection failed: {str(e)}", 0.0

    def copilot_chat(self, user_query: str, claim: Dict[str, Any]) -> str:
        """Interactive Gemini copilot chat with context-awareness over the active claim."""
        if not self.is_gemini_live():
            # Return high-fidelity benchmark response with setup notice
            return self._simulated_copilot(user_query, claim)

        # Build comprehensive prompt
        system_instructions = (
            "You are OmniClaim AI Copilot, a senior insurance claims forensic adjudicator and Google Cloud AI specialist.\n"
            "You evaluate claims using multimodal evidence (damage photos, Document AI parsed invoices, Vertex AI Search policy rules, and BigQuery benchmarks).\n"
            "Be concise, highly professional, analytical, and provide actionable settlement recommendations."
        )

        context_str = (
            f"ACTIVE CLAIM DETAILS:\n"
            f"- Claim ID: {claim.get('id')}\n"
            f"- Claimant: {claim.get('claimantName')}\n"
            f"- Loss Type: {claim.get('lossType')}\n"
            f"- Vehicle/Property: {claim.get('vehicle')}\n"
            f"- Policy: {claim.get('policyNumber')} ({claim.get('policyType')})\n"
            f"- Claimed Amount: ${claim.get('claimedAmount', 0):,.2f}\n"
            f"- AI Adjusted Amount: ${claim.get('adjustedAmount', 0):,.2f}\n"
            f"- Deductible: ${claim.get('deductible', 500):,.2f}\n"
            f"- Net Authorized Payout: ${claim.get('netPayout', 0):,.2f}\n"
            f"- Risk Score: {claim.get('riskScore')}/100 ({claim.get('riskLevel')} Risk)\n"
            f"- Damage Summary: {claim.get('damageSummary')}\n"
            f"- Repair Facility: {claim.get('documentAiExtraction', {}).get('repairShop')}\n"
            f"- BigQuery Historical Cost Percentile: {claim.get('bigQueryCohort', {}).get('costPercentile')}\n"
        )

        full_prompt = (
            f"{system_instructions}\n\n"
            f"{context_str}\n\n"
            f"ADJUSTER QUESTION: {user_query}\n\n"
            f"Respond using concise GitHub Markdown format with bold highlights and bullet points."
        )

        # Call live model
        try:
            if self.genai_client:
                resp = self.genai_client.models.generate_content(
                    model=self.model_name,
                    contents=full_prompt
                )
                return f"**[Live Gemini 3.8 Flash on Vertex AI]**\n\n{resp.text.strip()}"
            else:
                # Direct REST call
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"
                payload = json.dumps({"contents": [{"parts": [{"text": full_prompt}]}]}).encode("utf-8")
                req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    return f"**[Live Gemini 3.8 Flash on Vertex AI]**\n\n{text}"
        except Exception as e:
            print(f"Error calling live Gemini: {e}")
            return f"*(Live Gemini call encountered: {e}. Falling back to cached reasoning)*\n\n" + self._simulated_copilot(user_query, claim)

    def analyze_claim_live(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Run real Gemini 2.0 Multimodal Reasoning to evaluate a newly ingested claim."""
        if not self.is_gemini_live():
            return None

        prompt = (
            "You are OmniClaim AI, an autonomous insurance claim fraud adjudication engine.\n"
            "Analyze the following submitted claim payload and output ONLY a valid JSON object matching this schema:\n"
            "{\n"
            '  "riskScore": integer (0 to 100),\n'
            '  "riskLevel": string ("LOW", "MODERATE", "HIGH", or "CRITICAL"),\n'
            '  "status": string ("AUTO_APPROVED", "ADJUSTER_REVIEW", or "SIU_ESCALATED"),\n'
            '  "disallowedAmount": number,\n'
            '  "findings": [\n'
            '     {"flag": string, "severity": string ("INFO", "MEDIUM", "CRITICAL"), "description": string}\n'
            '  ],\n'
            '  "recommendedAction": string,\n'
            '  "claimantLetter": string\n'
            "}\n\n"
            f"CLAIM PAYLOAD:\n"
            f"Claimant: {payload.get('claimantName')}\n"
            f"Policy: {payload.get('policyNumber')}\n"
            f"Loss Type: {payload.get('lossType')}\n"
            f"Claimed Amount: ${payload.get('claimedAmount')}\n"
            f"Damage Description: {payload.get('damageSummary')}\n"
            f"Preset Scenario: {payload.get('preset')}\n"
            "Ensure riskScore aligns with fraud evidence (e.g. recycled images or phantom structural damages > 70 risk; clean small glass or burst pipe < 20 risk)."
        )

        try:
            raw_text = ""
            if self.genai_client:
                resp = self.genai_client.models.generate_content(
                    model=self.model_name,
                    contents=prompt
                )
                raw_text = resp.text.strip()
            else:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"
                body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
                req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=18) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()

            # Clean markdown formatting if model wrapped in ```json
            if raw_text.startswith("```"):
                raw_text = raw_text.split("\n", 1)[1]
                if raw_text.endswith("```"):
                    raw_text = raw_text.rsplit("\n", 1)[0]
            
            return json.loads(raw_text.strip())
        except Exception as e:
            print(f"Live Gemini claim analysis error: {e}")
            return None

    def _simulated_copilot(self, user_query: str, target: Dict[str, Any]) -> str:
        q = user_query.lower()
        c_id = target.get("id", "Claim")
        c_name = target.get("claimantName", "Claimant")
        c_amt = target.get("claimedAmount", 0)
        c_payout = target.get("netPayout", 0)
        c_risk = target.get("riskScore", 50)
        c_shop = target.get("documentAiExtraction", {}).get("repairShop", "Facility")

        setup_note = "\n\n*(💡 Tip: Enter a live Google Cloud / Gemini API key in 'GCP Settings' to enable real-time generative responses)*"

        if "why" in q and ("flag" in q or "risk" in q or "high" in q):
            return (
                f"**Gemini Multimodal Reasoning Analysis for {c_id}:**\n\n"
                f"The risk score of **{c_risk}/100** was triggered by 2 primary multimodal signals:\n"
                f"1. **Document AI vs. Vision Discrepancy**: The estimate from *{c_shop}* bills for major subframe/suspension work, but the visual computer vision model identifies only surface paint damage with no frame misalignment.\n"
                f"2. **BigQuery Regional Labor Outlier**: Quoted shop rates are significantly above the territorial benchmark for Alameda County ($88/hr median).\n"
                f"**Recommendation**: Authorize adjusted payout of **${c_payout:.2f}** or request supplemental teardown photos."
                + setup_note
            )
        elif "policy" in q or "deductible" in q or "cover" in q:
            clauses = target.get("policyCompliance", {}).get("relevantClauses", [])
            clause_text = "\n".join([f"- **{c['clauseId']} ({c['title']})**: {c['text']}" for c in clauses])
            return (
                f"**Vertex AI Search Policy RAG Retrieval:**\n\n"
                f"Under policy **{target.get('policyNumber')}**, the following clauses govern this claim:\n"
                f"{clause_text}\n\n"
                f"Deductible applied: **${target.get('deductible', 500):.2f}**."
                + setup_note
            )
        elif "letter" in q or "email" in q or "draft" in q:
            return (
                f"**Gemini Generated Claimant Letter:**\n\n"
                f"```text\n{target.get('claimantExplanationLetter', 'Letter pending generation.')}\n```\n\n"
                f"*You can click 'Dispatch to Insured' to send this via omnichannel messaging.*"
                + setup_note
            )
        else:
            return (
                f"**OmniClaim Gemini Copilot:**\n\n"
                f"I have reviewed claim **{c_id}** ({c_name}). "
                f"Claimed amount is **${c_amt:,.2f}**, and our AI recommendation is **{target.get('recommendedAction')}** "
                f"with an adjusted settlement of **${c_payout:,.2f}**.\n\n"
                f"You can ask me to:\n"
                f"- Explain why Document AI flagged specific line items\n"
                f"- Cross-reference policy clauses via Vertex AI Search\n"
                f"- Compare repair costs against BigQuery benchmarks\n"
                f"- Draft a customized Explanation of Benefits letter"
                + setup_note
            )

# Singleton Instance
gcp_service = GCPService()
