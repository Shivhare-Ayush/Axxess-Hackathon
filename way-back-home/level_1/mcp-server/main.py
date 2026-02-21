"""
Clinical Coder MCP Server

This MCP server provides tools for analyzing patient data and mapping to ICD-11:
- analyze_clinical_notes:   Extract structured entities from transcripts / notes
- analyze_radiology:        Analyze medical imaging via Gemini Vision
- extract_patient_entities: Extract patient EMR entities (subject_id, conditions …)
- map_icd_codes:            Map extracted conditions to official ICD-11 codes

Built with FastMCP for simple, Pythonic MCP server development.
Deployed to Cloud Run with HTTP transport for remote access.
"""

import os
import json
import asyncio
import logging
from typing import Annotated

from pydantic import Field
from fastmcp import FastMCP

from google import genai
from google.genai import types as genai_types
import simple_icd_11 as icd

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

    Args:
        transcript:     Transcribed speech text (preferred input)
        clinical_notes: Free-text notes (used when transcript is empty)

    Returns:
        dict with chief_complaint, symptoms, vitals, mentioned_medications, confidence
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
    """
    Analyze a medical image (X-ray, MRI, CT, dermatological photo) for anomalies.

    Args:
        image_url: Cloud Storage URL of the medical image

    Returns:
        dict with image_type, findings, anatomical_region, severity, confidence
    """
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
    """
    Extract structured patient entities from raw EMR text.

    Identifies subject_id, chronic conditions, allergies, current medications,
    and risk flags that could affect the current encounter.

    Args:
        patient_context: Free-text EMR data, patient history, or clinical context
        subject_id:      Explicit patient ID — always takes precedence over text extraction

    Returns:
        dict with subject_id, conditions, allergies, medications, risk_flags, confidence
    """
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

    # Explicit subject_id parameter always takes precedence over extracted value
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
# TOOL: map_icd_codes
# =============================================================================

@mcp.tool()
def map_icd_codes(
    conditions: Annotated[
        list,
        Field(description="List of clinical condition strings to look up (e.g. ['pneumonia', 'hypertension'])")
    ]
) -> dict:
    """
    Map extracted clinical conditions to official ICD-11 codes.

    Uses the simple-icd-11 library for local lookups — no external API needed.

    Args:
        conditions: List of condition/symptom strings to map

    Returns:
        dict with codes list [{condition, icd11_code, description}] and mapped_count
    """
    logger.info(f">>> 🏷  Tool: 'map_icd_codes' called for {len(conditions)} condition(s)")

    results = []

    for condition in conditions:
        try:
            matches = icd.search(condition)

            if matches:
                code = matches[0]
                description = icd.get_description(code)
                results.append({
                    "condition": condition,
                    "icd11_code": code,
                    "description": description
                })
                logger.info(f"    ✓ '{condition}' → {code}")
            else:
                results.append({
                    "condition": condition,
                    "icd11_code": None,
                    "description": "No matching ICD-11 code found"
                })
                logger.warning(f"    ⚠ No code found for '{condition}'")

        except Exception as e:
            logger.error(f"    ✗ Error mapping '{condition}': {e}")
            results.append({
                "condition": condition,
                "icd11_code": None,
                "description": f"Lookup error: {str(e)}"
            })

    mapped_count = sum(1 for r in results if r["icd11_code"] is not None)
    logger.info(f"    ✓ Mapped {mapped_count}/{len(conditions)} conditions")

    return {
        "codes": results,
        "mapped_count": mapped_count
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
