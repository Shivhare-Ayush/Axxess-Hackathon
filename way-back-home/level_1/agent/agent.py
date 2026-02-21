"""
Clinical Diagnostic Assistant - Root Agent

This is the main orchestrator agent that coordinates multi-modal patient
intake analysis to produce a preliminary diagnosis, ICD-11 codes, a
structured EMR entry, and a patient-facing recovery plan summary.

Architecture:
- Root Agent (ClinicalOrchestratorAI): Coordinates and synthesizes
  - Uses before_agent_callback to fetch patient config and set state
  - State is automatically shared with all sub-agents via InvocationContext
- ParallelAgent (DiagnosticCrew): Runs 3 specialists concurrently
  - ClinicalScribe:    Audio/text → ICD-11 codes (uses {audio_url}, {clinical_notes})
  - RadiologyAnalyst:  Medical imaging anomaly report (uses {image_url})
  - RecordsAnalyst:    EMR history RAG query (uses {patient_id})

Key ADK Pattern: before_agent_callback + {key} State Templating
- The callback runs ONCE when the agent starts processing
- It fetches patient data from the backend API
- It sets state values that sub-agents access via {key} templating
- No config file reading needed - works locally AND deployed
"""

import os
import logging
import httpx

from google.adk.agents import Agent, ParallelAgent
from google.adk.agents.callback_context import CallbackContext

# Import specialist agents
from agent.agents.clinical_scribe import clinical_scribe
from agent.agents.radiology_analyst import radiology_analyst
from agent.agents.records_analyst import records_analyst

# Import diagnosis submission tool
from agent.tools.diagnosis_tools import submit_diagnosis_tool

logger = logging.getLogger(__name__)


# =============================================================================
# BEFORE AGENT CALLBACK - Fetches patient config and sets state
# =============================================================================

async def setup_patient_context(callback_context: CallbackContext) -> None:
    """
    Fetch patient configuration and populate state for all agents.

    This callback:
    1. Reads PATIENT_ID and BACKEND_URL from environment
    2. Fetches patient data from the backend API
    3. Sets state values: audio_url, image_url, patient_id, clinical_notes, etc.
    4. Returns None to continue normal agent execution
    """
    patient_id = os.environ.get("PATIENT_ID", "")
    backend_url = os.environ.get("BACKEND_URL", "https://api.healthcare.dev")
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "")

    logger.info(f"[Callback] Setting up context for patient: {patient_id}")

    # Set project_id and backend_url in state immediately
    callback_context.state["project_id"] = project_id
    callback_context.state["backend_url"] = backend_url
    callback_context.state["patient_id"] = patient_id

    if not patient_id:
        logger.warning("[Callback] No PATIENT_ID set - using placeholder values")
        callback_context.state["audio_url"] = "Not available - set PATIENT_ID"
        callback_context.state["image_url"] = "Not available - set PATIENT_ID"
        callback_context.state["clinical_notes"] = "Not available - set PATIENT_ID"
        return None

    # Fetch patient data from backend API
    try:
        url = f"{backend_url}/patients/{patient_id}"
        logger.info(f"[Callback] Fetching from: {url}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        # Extract intake URLs
        intake_urls = data.get("intake_urls", {})

        # Set all state values for sub-agents to access
        callback_context.state["audio_url"] = intake_urls.get("audio", "Not available")
        callback_context.state["image_url"] = intake_urls.get("image", "Not available")
        callback_context.state["clinical_notes"] = data.get("clinical_notes", "Not available")

        logger.info(f"[Callback] State populated for patient: {patient_id}")

    except Exception as e:
        logger.error(f"[Callback] Error fetching patient config: {e}")
        callback_context.state["audio_url"] = f"Error: {e}"
        callback_context.state["image_url"] = f"Error: {e}"
        callback_context.state["clinical_notes"] = f"Error: {e}"

    return None


# =============================================================================
# DIAGNOSTIC CREW (PARALLEL)
# =============================================================================

diagnostic_crew = ParallelAgent(
    name="DiagnosticCrew",
    description="Runs clinical scribe, radiology, and records analysis in parallel.",
    sub_agents=[clinical_scribe, radiology_analyst, records_analyst]
)


# =============================================================================
# ROOT ORCHESTRATOR
# =============================================================================

root_agent = Agent(
    name="ClinicalOrchestratorAI",
    model="gemini-2.5-flash",
    description="Orchestrates multi-modal patient intake analysis and synthesizes a final clinical report.",
    instruction="""You are the Clinical Orchestrator AI coordinating a patient diagnostic workup.

## Patient Information
- Patient ID: {patient_id}

## Evidence Available to Specialists (set in state)
- Audio consultation: {audio_url}
- Medical imaging: {image_url}
- Clinical notes: {clinical_notes}

## Your Workflow

### STEP 1: DELEGATE TO DIAGNOSTIC CREW
Tell the DiagnosticCrew to analyze all patient data.
Each specialist will run concurrently and report independently.

### STEP 2: COLLECT SPECIALIST REPORTS
Each specialist will report in a structured format:
- "CLINICAL SCRIBE ANALYSIS: ..." — symptoms, ICD-11 codes
- "RADIOLOGY ANALYSIS: ..." — imaging findings and confidence
- "RECORDS ANALYSIS: ..." — historical risks and flags

### STEP 3: SYNTHESIZE
Combine all three reports into:
1. **Preliminary diagnostic hypothesis** — most likely condition(s) supported by ≥2 specialists
2. **ICD-11 code list** — from the Clinical Scribe, confirmed or supplemented by Radiology
3. **Structured EMR entry** — patient ID, date, presenting complaint, findings, assessment, plan
4. **Patient recovery plan** — jargon-free summary the patient can understand

### STEP 4: SUBMIT DIAGNOSIS
Call submit_diagnosis with the ICD-11 code list and the clinical summary.

## Response Style
Be precise and clinical in your synthesis. Flag any contradictions between specialist reports.
When records show risk flags, prominently note them in the EMR entry.
""",
    sub_agents=[diagnostic_crew],
    tools=[submit_diagnosis_tool],
    before_agent_callback=setup_patient_context
)
