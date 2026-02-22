"""
Tools for the Clinical Diagnostic Assistant agents.

This package contains:
- MCP tool connection to the clinical-coder Cloud Run MCP server
  (analyze_clinical_notes, analyze_radiology, extract_patient_entities, map_icd_codes)
- Speech transcription tool (Gemini native audio, local FunctionTool)
- Diagnosis submission tool (uses ToolContext for state access)

MCP pattern: Custom MCP — your own FastMCP server on Cloud Run (clinical-coder)
Plus ToolContext for accessing shared state in tools.
"""

from agent.tools.mcp_tools import get_clinical_mcp_toolset
from agent.tools.speech_tools import transcribe_audio_tool
from agent.tools.diagnosis_tools import submit_diagnosis_tool

__all__ = [
    "get_clinical_mcp_toolset",
    "transcribe_audio_tool",
    "submit_diagnosis_tool",
]
