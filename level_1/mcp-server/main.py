"""
Clinical Coder MCP Server

This MCP server provides tools for analyzing patient data and mapping to ICD-11:
- analyze_clinical_notes:   Extract structured entities from transcripts / notes
- analyze_radiology:        Analyze medical imaging via Gemini Vision
- extract_patient_entities: Extract patient EMR entities (subject_id, conditions …)
- map_icd_codes:            Map extracted conditions to official ICD-11 codes (WHO REST API)

Built with FastMCP for simple, Pythonic MCP server development.
Deployed to Cloud Run with HTTP transport for remote access.
"""

import os
import json
import asyncio
import logging
import time
import requests
import re
from typing import Annotated

from pydantic import Field
from fastmcp import FastMCP

from google import genai
from google.genai import types as genai_types

# =============================================================================
# LOGGING SETUP
# =============================================================================

logging.basicConfig(
    format="[%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# =============================================================================
# FASTMCP SERVER INITIALIZATION
# =============================================================================

mcp = FastMCP("Clinical Coder MCP Server 🏥")

# =============================================================================
# GEMINI CLIENT
# =============================================================================

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

if not PROJECT_ID:
    logger.warning("GOOGLE_CLOUD_PROJECT not set - Gemini tools will fail")

client = genai.Client(
    vertexai=True,
    project=PROJECT_ID,
    location=LOCATION
)

logger.info(f"Clinical Coder MCP Server initialized (project: {PROJECT_ID})")


# =============================================================================
# WHO ICD-11 REST API CLIENT (replaces simple_icd_11)
# =============================================================================

_icd_token: str | None = None
_icd_token_expiry: float = 0

ICD_TOKEN_URL = "https://icdaccessmanagement.who.int/connect/token"
ICD_SEARCH_URL = "https://id.who.int/icd/release/11/2024-01/mms/search"


def _get_icd_token() -> str:
    global _icd_token, _icd_token_expiry
    if _icd_token and time.time() < _icd_token_expiry:
        return _icd_token

    client_id = os.environ.get("ICD_CLIENT_ID", "")
    client_secret = os.environ.get("ICD_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        raise ValueError("ICD_CLIENT_ID and ICD_CLIENT_SECRET environment variables must be set.")

    resp = requests.post(
        ICD_TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "icdapi_access",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    _icd_token = data["access_token"]
    _icd_token_expiry = time.time() + data.get("expires_in", 3600) - 60
    logger.info("[ICD] Token refreshed.")
    return _icd_token


def _search_icd(condition: str) -> dict:
    """Search WHO ICD-11 API for a single condition. Returns {code, title, error}."""
    if not condition or not condition.strip():
        return {"code": None, "title": None, "error": "Empty query"}
    try:
        token = _get_icd_token()
        resp = requests.get(
            ICD_SEARCH_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Accept-Language": "en",
                "API-Version": "v2",
            },
            params={
                "q": condition,
                "useFlexisearch": "true",
                "flatResults": "true",
                "highlightingEnabled": "false",
            },
            timeout=15,
        )
        resp.raise_for_status()
        entities = resp.json().get("destinationEntities", [])
        if not entities:
            return {"code": None, "title": None, "error": "No match found"}
        top = entities[0]
        code = top.get("theCode") or top.get("code", "")
        title = re.sub(r"<[^>]+>", "", top.get("title", ""))
        return {"code": code, "title": title, "error": None}
    except Exception as e:
        logger.error(f"[ICD] Error searching '{condition}': {e}")
        return {"code": None, "title": None, "error": str(e)}


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def parse_json_response(text: str) -> dict:
    """Parse JSON from a response string, handling markdown code fences."""
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}")
        return {
            "error": f"Failed to parse JSON: {str(e)}",
            "raw_response": text[:500]
        }


# =============================================================================
# TOOL: analyze_clinical_notes
# =============================================================================

@mcp.tool()
def analyze_clinical_notes(
    transcript: Annotated[
        str,
        Field(description="Transcribed audio text from the patient consultation")
    ],
    clinical_notes: Annotated[
        str,
        Field(description="Raw doctor notes or free-text clinical observations (optional)")
    ] = ""
) -> dict:
    """
    Extract structured clinical entities from a consultation transcript or doctor notes.

    Uses Gemini to identify chief complaint, symptoms, vitals, and medications.
    """
    text = transcript or clinical_notes
    logger.info(f">>> 📋 Tool: 'analyze_clinical_notes' called ({len(text)} chars)")

    prompt = f"""Analyze this clinical text and extract structured entities.

Return ONLY valid JSON (no markdown, no explanation):
{{
    "chief_complaint": "primary reason for visit",
    "symptoms": ["symptom1", "symptom2"],
    "vitals": {{"bp": "...", "hr": "...", "temp": "...", "rr": "...", "spo2": "..."}},
    "mentioned_medications": ["med1", "med2"],
    "confidence": 0.0
}}

Clinical text: {text}
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        result = parse_json_response(response.text)
    except Exception as e:
        logger.error(f"    ✗ analyze_clinical_notes failed: {e}")
        result = {"error": str(e)}

    result.setdefault("chief_complaint", "")
    result.setdefault("symptoms", [])
    result.setdefault("vitals", {})
    result.setdefault("mentioned_medications", [])
    result.setdefault("confidence", 0.0)

    logger.info(f"    ✓ chief_complaint='{result.get('chief_complaint')}'")
    return result


# =============================================================================
# TOOL: analyze_radiology
# =============================================================================

RADIOLOGY_PROMPT = """Analyze this medical image and extract structured findings.

Return ONLY valid JSON (no markdown, no explanation):
{
    "image_type": "X-ray|MRI|CT|dermatological|other",
    "findings": ["finding1", "finding2"],
    "anatomical_region": "body region examined",
    "severity": "none|mild|moderate|severe",
    "confidence": 0.0
}
"""


@mcp.tool()
def analyze_radiology(
    image_url: Annotated[
        str,
        Field(description="Cloud Storage URL (gs://...) of the medical image")
    ]
) -> dict:
    """Analyze a medical image (X-ray, MRI, CT, dermatological photo) for anomalies."""
    logger.info(f">>> 🩻 Tool: 'analyze_radiology' called for '{image_url}'")

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                RADIOLOGY_PROMPT,
                genai_types.Part.from_uri(file_uri=image_url, mime_type="image/jpeg")
            ]
        )
        result = parse_json_response(response.text)
    except Exception as e:
        logger.error(f"    ✗ analyze_radiology failed: {e}")
        result = {"error": str(e)}

    result.setdefault("image_type", "unknown")
    result.setdefault("findings", [])
    result.setdefault("anatomical_region", "unknown")
    result.setdefault("severity", "unknown")
    result.setdefault("confidence", 0.0)

    logger.info(f"    ✓ image_type='{result.get('image_type')}', findings={len(result.get('findings', []))}")
    return result


# =============================================================================
# TOOL: extract_patient_entities
# =============================================================================

@mcp.tool()
def extract_patient_entities(
    patient_context: Annotated[
        str,
        Field(description="Raw EMR text or patient context to extract entities from")
    ],
    subject_id: Annotated[
        str,
        Field(description="Patient / subject identifier (overrides any ID found in text)")
    ] = ""
) -> dict:
    """Extract structured patient entities from raw EMR text."""
    logger.info(f">>> 🗂  Tool: 'extract_patient_entities' called (subject_id='{subject_id}')")

    prompt = f"""Extract structured patient entities from this EMR text.

Return ONLY valid JSON (no markdown, no explanation):
{{
    "subject_id": "patient identifier found in text",
    "conditions": ["condition1", "condition2"],
    "allergies": ["allergen1"],
    "medications": ["med1", "med2"],
    "risk_flags": ["flag1"],
    "confidence": 0.0
}}

EMR text: {patient_context}
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        result = parse_json_response(response.text)
    except Exception as e:
        logger.error(f"    ✗ extract_patient_entities failed: {e}")
        result = {"error": str(e)}

    if subject_id:
        result["subject_id"] = subject_id

    result.setdefault("subject_id", "")
    result.setdefault("conditions", [])
    result.setdefault("allergies", [])
    result.setdefault("medications", [])
    result.setdefault("risk_flags", [])
    result.setdefault("confidence", 0.0)

    logger.info(f"    ✓ subject_id='{result.get('subject_id')}', conditions={result.get('conditions')}")
    return result


# =============================================================================
# TOOL: map_icd_codes  (WHO REST API — replaces broken simple_icd_11)
# =============================================================================

@mcp.tool()
def map_icd_codes(
    conditions: Annotated[
        list,
        Field(description="List of clinical condition strings to look up (e.g. ['pneumonia', 'hypertension'])")
    ]
) -> dict:
    """
    Map extracted clinical conditions to official ICD-11 codes via WHO REST API.

    Args:
        conditions: List of condition/symptom strings to map

    Returns:
        dict with codes list [{condition, icd11_code, description}] and mapped_count
    """
    logger.info(f">>> 🏷  Tool: 'map_icd_codes' called for {len(conditions)} condition(s)")

    results = []

    for condition in conditions:
        match = _search_icd(condition)

        if match["code"]:
            results.append({
                "condition": condition,
                "icd11_code": match["code"],
                "description": match["title"],
            })
            logger.info(f"    ✓ '{condition}' → {match['code']} ({match['title']})")
        else:
            results.append({
                "condition": condition,
                "icd11_code": None,
                "description": match.get("error", "No matching ICD-11 code found"),
            })
            logger.warning(f"    ⚠ No code for '{condition}': {match.get('error')}")

    mapped_count = sum(1 for r in results if r["icd11_code"] is not None)
    logger.info(f"    ✓ Mapped {mapped_count}/{len(conditions)} conditions")

    return {
        "codes": results,
        "mapped_count": mapped_count,
    }


# =============================================================================
# SERVER STARTUP (HTTP Transport for Cloud Run)
# =============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))

    logger.info(f"🚀 Clinical Coder MCP Server starting on port {port}")
    logger.info(f"📍 MCP endpoint: http://0.0.0.0:{port}/mcp")
    logger.info(f"🔧 Tools: analyze_clinical_notes, analyze_radiology, extract_patient_entities, map_icd_codes")

    asyncio.run(
        mcp.run_async(
            transport="http",
            host="0.0.0.0",
            port=port,
        )
    )