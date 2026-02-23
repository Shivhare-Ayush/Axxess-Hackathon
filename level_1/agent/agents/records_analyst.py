"""
Records Analyst Agent

Extracts structured entities from patient EMR history to surface
risks, allergies, and chronic conditions relevant to the current encounter.

Uses MCP server if available, otherwise uses clinical_coding_tool locally.
"""

import logging
from google.adk.agents import Agent

logger = logging.getLogger(__name__)

# ── Tools: MCP if available, else local clinical_coding_tool ──
try:
    from agent.tools.mcp_tools import get_clinical_mcp_toolset
    _mcp = get_clinical_mcp_toolset()
    _tools = [_mcp] if _mcp is not None else []
    if _mcp:
        logger.info("[RecordsAnalyst] MCP toolset loaded.")
    else:
        logger.warning("[RecordsAnalyst] No MCP toolset — running without record tools.")
except Exception as e:
    _tools = []
    logger.warning(f"[RecordsAnalyst] MCP import failed: {e}")


records_analyst = Agent(
    name="RecordsAnalyst",
    model="gemini-2.5-flash",
    description="Extracts structured EMR entities to surface patient risks, allergies, and conditions.",
    instruction="""You are a Records Analyst specialist reviewing patient history.

## YOUR INPUT DATA
- Patient ID: {patient_id}
- Clinical notes: {clinical_notes}

## YOUR WORKFLOW

### STEP 1 — EXTRACT ENTITIES
If extract_patient_entities tool is available, call it with:
- patient_context: {clinical_notes}
- subject_id: {patient_id}

If the tool is NOT available, extract entities directly from the clinical notes text using your own analysis.

### STEP 2 — REPORT
Always report in this exact format:

RECORDS ANALYSIS:
- Subject ID: [patient ID or "unknown"]
- Historical conditions: [list or "None on record"]
- Allergies / intolerances: [list or "None on record"]
- Current medications: [list or "None on record"]
- Risk flags: [list or "None identified"]
- Confidence: [0-100]%

## RULES
- Do NOT make a final diagnosis
- Do NOT wait for other specialists
- Complete your report even if no tool is available — use the clinical notes directly
""",
    tools=_tools,
)