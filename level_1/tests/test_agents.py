"""
Tests for specialist agent configurations.

Strategy
--------
Verifies each ADK Agent object has the correct:
  - name, model, description
  - instruction content (state template vars, MCP tool call names, report headings)
  - tools list (correct count; confirms MCP toolset and/or FunctionTool are attached)

Import approach
---------------
Agent modules call get_clinical_mcp_toolset() and genai.Client() at module-level
(import time), so two patches must be active before any agent module is imported:

  1. MCPToolset class → mock, so no real Cloud Run connection is attempted
  2. google.genai.Client → mock, so no credential check happens in speech_tools.py

The env var ICD_MCP_SERVER_URL must also be set before mcp_tools.py is imported;
os.environ.setdefault() is used so a real value (if present) is left intact.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Set required env vars BEFORE any agent module is imported.
# mcp_tools.py reads ICD_MCP_SERVER_URL at module-level; it must be non-empty
# or get_clinical_mcp_toolset() raises ValueError.
# ---------------------------------------------------------------------------
os.environ.setdefault("ICD_MCP_SERVER_URL", "http://mock-clinical-coder")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")

# ---------------------------------------------------------------------------
# Patch network-dependent classes for the duration of the import phase.
# MCPToolset is patched so Agent(..., tools=[get_clinical_mcp_toolset()]) works
# without a live server.  genai.Client is patched so speech_tools.py doesn't
# need Application Default Credentials at import time.
# ---------------------------------------------------------------------------
_mock_toolset = MagicMock(name="MockMCPToolset")
_mcp_cls_patch = patch(
    "google.adk.tools.mcp_tool.mcp_toolset.MCPToolset",
    return_value=_mock_toolset,
)
_genai_patch = patch("google.genai.Client", return_value=MagicMock())

_mcp_cls_patch.start()
_genai_patch.start()

# Also reset the singleton cache so each test module gets a clean import
import agent.tools.mcp_tools as _mcp_tools_mod  # noqa: E402
_mcp_tools_mod._clinical_mcp_toolset = None

from agent.agents.radiology_analyst import radiology_analyst  # noqa: E402
from agent.agents.records_analyst import records_analyst      # noqa: E402
from agent.agents.clinical_scribe import clinical_scribe      # noqa: E402

_mcp_cls_patch.stop()
_genai_patch.stop()


# ===========================================================================
# RadiologyAnalyst
# ===========================================================================

class TestRadiologyAnalyst:

    def test_name(self):
        assert radiology_analyst.name == "RadiologyAnalyst"

    def test_model(self):
        assert radiology_analyst.model == "gemini-2.5-flash"

    def test_description_is_nonempty(self):
        assert isinstance(radiology_analyst.description, str)
        assert len(radiology_analyst.description) > 0

    def test_has_exactly_one_tool(self):
        # Should have the single clinical MCP toolset; no local FunctionTools
        assert len(radiology_analyst.tools) == 1

    def test_instruction_has_image_url_template_var(self):
        assert "{image_url}" in radiology_analyst.instruction

    def test_instruction_calls_analyze_radiology(self):
        assert "analyze_radiology" in radiology_analyst.instruction

    def test_instruction_has_report_heading(self):
        assert "RADIOLOGY ANALYSIS" in radiology_analyst.instruction

    def test_instruction_documents_findings_key(self):
        assert "findings" in radiology_analyst.instruction

    def test_instruction_documents_severity_key(self):
        assert "severity" in radiology_analyst.instruction

    def test_instruction_documents_confidence_key(self):
        assert "confidence" in radiology_analyst.instruction

    def test_agent_does_not_synthesize(self):
        # Instruction must remind the agent to stay in its lane
        instr = radiology_analyst.instruction.lower()
        assert "do not make a final diagnosis" in instr


# ===========================================================================
# RecordsAnalyst
# ===========================================================================

class TestRecordsAnalyst:

    def test_name(self):
        assert records_analyst.name == "RecordsAnalyst"

    def test_model(self):
        assert records_analyst.model == "gemini-2.5-flash"

    def test_description_is_nonempty(self):
        assert isinstance(records_analyst.description, str)
        assert len(records_analyst.description) > 0

    def test_has_exactly_one_tool(self):
        # Should have the single clinical MCP toolset; no local FunctionTools
        assert len(records_analyst.tools) == 1

    def test_instruction_has_patient_id_template_var(self):
        assert "{patient_id}" in records_analyst.instruction

    def test_instruction_has_clinical_notes_template_var(self):
        assert "{clinical_notes}" in records_analyst.instruction

    def test_instruction_calls_extract_patient_entities(self):
        assert "extract_patient_entities" in records_analyst.instruction

    def test_instruction_has_report_heading(self):
        assert "RECORDS ANALYSIS" in records_analyst.instruction

    def test_instruction_surfaces_subject_id(self):
        assert "subject_id" in records_analyst.instruction

    def test_instruction_surfaces_risk_flags(self):
        assert "risk_flag" in records_analyst.instruction.lower()

    def test_instruction_surfaces_allergies(self):
        assert "allerg" in records_analyst.instruction.lower()

    def test_agent_does_not_synthesize(self):
        instr = records_analyst.instruction.lower()
        assert "do not make a final diagnosis" in instr


# ===========================================================================
# ClinicalScribe (updated workflow: now uses analyze_clinical_notes for NER)
# ===========================================================================

class TestClinicalScribe:

    def test_name(self):
        assert clinical_scribe.name == "ClinicalScribe"

    def test_model(self):
        assert clinical_scribe.model == "gemini-2.5-flash"

    def test_has_two_tools(self):
        # transcribe_audio_tool (local FunctionTool) + clinical MCP toolset
        assert len(clinical_scribe.tools) == 2

    def test_instruction_has_audio_url_template_var(self):
        assert "{audio_url}" in clinical_scribe.instruction

    def test_instruction_has_clinical_notes_template_var(self):
        assert "{clinical_notes}" in clinical_scribe.instruction

    def test_instruction_calls_transcribe_audio(self):
        assert "transcribe_audio" in clinical_scribe.instruction

    def test_instruction_calls_analyze_clinical_notes(self):
        # NER step added in Phase B update
        assert "analyze_clinical_notes" in clinical_scribe.instruction

    def test_instruction_calls_map_icd_codes(self):
        assert "map_icd_codes" in clinical_scribe.instruction

    def test_instruction_has_report_heading(self):
        assert "CLINICAL SCRIBE ANALYSIS" in clinical_scribe.instruction
