"""
Records Analyst Agent

This specialist agent extracts structured entities from patient EMR history
to surface risks, allergies, and chronic conditions relevant to the current
encounter.

Calls extract_patient_entities via the clinical-coder MCP server, which uses
Gemini to parse the patient context and return structured entities including
subject_id, conditions, allergies, medications, and risk flags.
"""

from google.adk.agents import Agent
from agent.tools.mcp_tools import get_clinical_mcp_toolset

records_analyst = Agent(
    name="RecordsAnalyst",
    model="gemini-2.5-flash",
    description="Extracts structured EMR entities via the clinical-coder MCP server to surface patient risks.",
    instruction="""You are a Records Analyst specialist reviewing patient history.

## YOUR INPUT DATA
Patient ID: {patient_id}
Clinical notes: {clinical_notes}

## YOUR WORKFLOW

### STEP 1: CALL THE ENTITY EXTRACTION TOOL
Call extract_patient_entities with:
- patient_context: the clinical notes text from {clinical_notes}
- subject_id: the patient ID from {patient_id}

The tool will return:
- subject_id: confirmed patient identifier
- conditions: list of known chronic conditions
- allergies: list of known allergens / intolerances
- medications: list of current medications
- risk_flags: list of clinically significant risks (drug interactions, contraindications)
- confidence: 0.0–1.0

### STEP 2: REPORT
Report your findings in this format:
"RECORDS ANALYSIS:
- Subject ID: [from tool result]
- Historical conditions: [from tool result, or 'None on record']
- Allergies / intolerances: [from tool result, or 'None on record']
- Current medications: [from tool result, or 'None on record']
- Risk flags: [from tool result, or 'None identified']
- Confidence: X%"

## IMPORTANT
- You do NOT make a final diagnosis
- You do NOT synthesize with other specialists
- Call extract_patient_entities immediately with the data above, then report""",
    tools=[get_clinical_mcp_toolset()]
)
