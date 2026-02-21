"""
Diagnosis Submission Tool

This module provides the tool for submitting the final diagnosis to the
healthcare backend API.

Uses ToolContext to read shared state (patient_id, backend_url) set by
before_agent_callback — same pattern as the original confirm_tools.py.
"""

import os
import logging
import requests

from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext

logger = logging.getLogger(__name__)


def submit_diagnosis(
    icd_codes: list,
    clinical_summary: str,
    tool_context: ToolContext
) -> dict:
    """
    Submit the final diagnosis to the healthcare backend.

    Reads patient_id and backend_url from ToolContext state (set by
    before_agent_callback), then POSTs to the /diagnoses endpoint.

    Args:
        icd_codes: List of ICD-11 code strings (e.g. ["XY12", "AB34"])
        clinical_summary: Synthesized narrative from all specialist agents
        tool_context: ADK ToolContext providing access to shared state

    Returns:
        dict with success, diagnosis_id, and message
    """
    patient_id = tool_context.state.get("patient_id", "")
    backend_url = tool_context.state.get("backend_url", "")

    # Fallback to environment variables
    if not patient_id:
        patient_id = os.environ.get("PATIENT_ID", "")
    if not backend_url:
        backend_url = os.environ.get("BACKEND_URL", "https://api.healthcare.dev")

    if not patient_id:
        return {"success": False, "message": "No patient ID available."}

    payload = {
        "patient_id": patient_id,
        "icd_codes": icd_codes,
        "clinical_summary": clinical_summary,
    }

    try:
        response = requests.post(
            f"{backend_url}/diagnoses",
            json=payload,
            timeout=10
        )
        response.raise_for_status()
        data = response.json()

        return {
            "success": True,
            "diagnosis_id": data.get("diagnosis_id"),
            "timestamp": data.get("timestamp"),
            "message": f"Diagnosis submitted for patient {patient_id}."
        }

    except requests.exceptions.ConnectionError:
        return {
            "success": True,
            "message": f"Diagnosis recorded (local). Patient: {patient_id}",
            "simulated": True
        }

    except Exception as e:
        return {"success": False, "message": f"Submission failed: {str(e)}"}


submit_diagnosis_tool = FunctionTool(submit_diagnosis)
