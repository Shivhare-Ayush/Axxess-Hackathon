"""
Clinical Diagnostic Assistant - Root Agent

Architecture:
- Root Agent (ClinicalOrchestratorAI): Orchestrates and synthesizes
  - Uses before_agent_callback to fetch patient config and set state
- ParallelAgent (DiagnosticCrew): Runs 3 specialists concurrently
  - ClinicalScribe:    Audio/text → symptoms + ICD-11 codes
  - RadiologyAnalyst:  Medical imaging anomaly report
  - RecordsAnalyst:    EMR history analysis
- clinical_coding_tool: ICD-11 WHO API + openFDA treatment lookup
"""

import os
import logging
import httpx

# NOTE: Do NOT import Gemini directly — use model="gemini-2.5-flash" string.
# The Gemini class is not needed and causes import errors in some ADK versions.
from google.adk.agents import Agent, ParallelAgent
from google.adk.agents.callback_context import CallbackContext

# Specialist agents
from agent.agents.clinical_scribe import clinical_scribe
from agent.agents.radiology_analyst import radiology_analyst
from agent.agents.records_analyst import records_analyst

# Tools
from agent.tools.diagnosis_tools import submit_diagnosis_tool
from agent.tools.clinical_coding_tool import clinical_coding_tool

logger = logging.getLogger(__name__)


# =============================================================================
# BEFORE AGENT CALLBACK
# =============================================================================

async def setup_patient_context(callback_context: CallbackContext) -> None:
    """
    Runs once when the agent starts.
    Fetches patient config from backend API and populates shared state
    so all sub-agents can access {audio_url}, {image_url}, {clinical_notes}.
    """
    patient_id = os.environ.get("PATIENT_ID", "")
    backend_url = os.environ.get("BACKEND_URL", "https://api.healthcare.dev")
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "")

    logger.info(f"[Callback] Setting up context for patient: {patient_id}")

    callback_context.state["project_id"] = project_id
    callback_context.state["backend_url"] = backend_url
    callback_context.state["patient_id"] = patient_id

    if not patient_id:
        logger.warning("[Callback] No PATIENT_ID set - using placeholder values")
        callback_context.state["audio_url"] = "Not provided"
        callback_context.state["image_url"] = "Not provided"
        callback_context.state["clinical_notes"] = "Not provided"
        return None

    try:
        url = f"{backend_url}/patients/{patient_id}"
        logger.info(f"[Callback] Fetching from: {url}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        intake_urls = data.get("intake_urls", {})
        callback_context.state["audio_url"] = intake_urls.get("audio", "Not available")
        callback_context.state["image_url"] = intake_urls.get("image", "Not available")
        callback_context.state["clinical_notes"] = data.get("clinical_notes", "Not available")

        logger.info(f"[Callback] State populated for patient: {patient_id}")

    except Exception as e:
        logger.error(f"[Callback] Error fetching patient config: {e}")
        callback_context.state["audio_url"] = "Error fetching data"
        callback_context.state["image_url"] = "Error fetching data"
        callback_context.state["clinical_notes"] = "Error fetching data"

    return None


# =============================================================================
# DIAGNOSTIC CREW (PARALLEL)
# =============================================================================

diagnostic_crew = ParallelAgent(
    name="DiagnosticCrew",
    description="Runs ClinicalScribe, RadiologyAnalyst, and RecordsAnalyst concurrently.",
    sub_agents=[clinical_scribe, radiology_analyst, records_analyst],
)


# =============================================================================
# ROOT ORCHESTRATOR
# =============================================================================

root_agent = Agent(
    name="ClinicalOrchestratorAI",
    model="gemini-2.5-flash",
    description=(
        "Orchestrates multi-modal patient intake analysis and synthesizes "
        "a final AI-assisted preliminary clinical assessment."
    ),
    instruction="""You are the Clinical Orchestrator AI coordinating a patient diagnostic workup.

⚠️ IMPORTANT: You provide AI-assisted preliminary assessments to support clinicians.
You do NOT prescribe treatments or replace licensed medical judgment.

## Patient Context
- Patient ID: {patient_id}
- Audio consultation: {audio_url}
- Medical imaging: {image_url}
- Clinical notes: {clinical_notes}

---

## WORKFLOW

### STEP 1 — DELEGATE TO DIAGNOSTIC CREW
Transfer to DiagnosticCrew to analyze all available patient data concurrently.
Each specialist runs independently and reports back.

### STEP 2 — COLLECT SPECIALIST REPORTS
Wait for all three specialists to complete:
- **CLINICAL SCRIBE**: symptoms, chief complaint, vitals, ICD-11 codes
- **RADIOLOGY ANALYSIS**: imaging findings and confidence
- **RECORDS ANALYSIS**: patient history, risk flags, medications

### STEP 3 — VALIDATE ICD CODES + GET TREATMENTS
After collecting reports:
1. Extract all symptoms and conditions mentioned by the specialists.
2. Call `run_clinical_coding` with the full symptom list.
3. This returns validated ICD-11 codes (WHO API) and FDA treatment suggestions.

### STEP 4 — SYNTHESIZE FINAL REPORT
Produce a structured report with all of the following sections:

**PRELIMINARY DIAGNOSTIC ASSESSMENT**
- Most likely condition(s) supported by ≥2 specialists
- Confidence level: Low / Moderate / High
- Any contradictions between specialist reports

**ICD-11 CODES**
- Validated codes from run_clinical_coding output
- Format: [CODE] Condition name

**STRUCTURED EMR ENTRY**
- Patient ID, date, presenting complaint
- Physical/imaging findings
- Assessment and plan

**SUGGESTED TREATMENTS** (for clinician review only)
- FDA-labeled first-line options from run_clinical_coding output
- Include disclaimer: "For clinician review — not a prescription"

**PATIENT SUMMARY** (plain language)
- Jargon-free explanation a patient can understand
- What to watch for
- When to seek urgent care

### STEP 5 — SUBMIT DIAGNOSIS
Call `submit_diagnosis` with the ICD code list and clinical summary.

---

## RESPONSE STYLE
- Be precise and clinical
- Flag contradictions prominently
- Always note risk flags from patient history
- Never state definitive diagnoses — use "consistent with", "suggestive of", "warrants evaluation for"
""",
    sub_agents=[diagnostic_crew],
    tools=[submit_diagnosis_tool, clinical_coding_tool],
    before_agent_callback=setup_patient_context,
)