"""
ClinicalScribe Agent

Handles:
  - Audio transcription (via speech tool)
  - Clinical notes / transcript → structured symptom extraction
  - ICD-11 code mapping via WHO API (NOT simple_icd_11)

Output format:
  CLINICAL SCRIBE ANALYSIS:
  - Transcript summary: ...
  - Chief complaint: ...
  - Key symptoms: [list]
  - Vitals: ...
  - ICD-11 codes: [{"condition": ..., "icd_code": ..., "icd_title": ...}]
  - Confidence: ...%
"""

import os
import logging

from google.adk.agents import Agent

logger = logging.getLogger(__name__)

# ── Speech tool (audio → transcript) ─────────────────────────
try:
    from agent.tools.speech_tools import transcribe_audio_tool
    _speech_tools = [transcribe_audio_tool]
    logger.info("[ClinicalScribe] Speech tool loaded.")
except ImportError:
    _speech_tools = []
    logger.warning("[ClinicalScribe] Speech tool not available.")

# ── ICD tool — use NEW clinical_coding_tool, NOT simple_icd_11 ─
try:
    from agent.tools.clinical_coding_tool import clinical_coding_tool
    _icd_tools = [clinical_coding_tool]
    logger.info("[ClinicalScribe] clinical_coding_tool (WHO ICD-11 + openFDA) loaded.")
except ImportError:
    _icd_tools = []
    logger.warning(
        "[ClinicalScribe] clinical_coding_tool not available. "
        "ICD codes will not be mapped."
    )

_all_tools = _speech_tools + _icd_tools


clinical_scribe = Agent(
    name="ClinicalScribe",
    model="gemini-2.5-flash",
    description=(
        "Extracts structured clinical data from patient-clinician transcripts "
        "and doctor notes. Maps symptoms to ICD-11 codes using WHO API."
    ),
    instruction="""You are a clinical documentation specialist.

Your job is to extract structured medical data from whatever input is provided:
audio transcripts, typed notes, or dictated summaries.

## INPUT SOURCES (use whichever are available)
- Audio transcript: {audio_url}
- Clinical notes: {clinical_notes}

If audio_url is a valid URL (starts with gs:// or https://), call transcribe_audio first.
Otherwise, work directly from clinical_notes text.

## YOUR TASK

### Step 1 — Extract Clinical Data
From the input, identify:
- Chief complaint (primary reason for visit)
- Key symptoms (list every symptom mentioned)
- Duration (how long symptoms have been present)
- Vitals (BP, HR, temp, SpO2, RR — if mentioned)
- Relevant history mentioned in conversation

### Step 2 — Map Symptoms to ICD-11 Codes
Call `run_clinical_coding` with the complete list of extracted symptoms.

Example call:
  run_clinical_coding(symptoms=["sore throat", "swollen lymph nodes", "fever"])

This returns validated WHO ICD-11 codes AND FDA treatment suggestions.
Include the ICD codes in your report.

### Step 3 — Report
Output in this exact format:

CLINICAL SCRIBE ANALYSIS:
- Transcript summary: [1-2 sentence summary]
- Chief complaint: [main complaint]
- Key symptoms: [comma-separated list]
- Duration: [if mentioned, else "Not reported"]
- Vitals: [if mentioned, else "Not recorded"]
- ICD-11 codes: [list from run_clinical_coding output, format: CODE — Condition]
- Suggested treatments: [brief list from run_clinical_coding output]
- Confidence: [0-100]%

## IMPORTANT
- Never use simple_icd_11 or any other ICD library — always use run_clinical_coding
- Be thorough with symptom extraction — the more symptoms, the better the ICD mapping
- If the patient describes COVID-like symptoms (fever, cough, fatigue, loss of taste/smell),
  include "COVID-19" as a candidate condition in your symptom list
- Always extract every distinct symptom as a separate item in the list
""",
    tools=_all_tools,
)