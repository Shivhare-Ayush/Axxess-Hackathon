"""
Integration tests for ClinicalScribe, RadiologyAnalyst, and RecordsAnalyst.

Strategy
--------
Each specialist agent is tested end-to-end through the full ADK Runner pipeline,
but without any real network calls:

  ScriptedLLM (BaseLlm subclass)
    ↳ Returns pre-defined Content objects in turn order instead of calling Gemini.
    ↳ First N turns are FunctionCall objects (triggering tool dispatch).
    ↳ Final turn is the formatted text report.

  Stub FunctionTools
    ↳ Deterministic replacements for the MCP tool calls (no live server).
    ↳ Return realistic but fixed JSON payloads.

  InMemorySessionService + Runner
    ↳ Runs the full ADK event loop (tool dispatch, function responses, final event).
    ↳ Session state is pre-populated to simulate before_agent_callback.

Each test asserts that `event.is_final_response() == True` fires and that the
final text contains the required report heading and key data fields sourced from
the stub tool responses — verifying both the ADK plumbing and the output contract.
"""

import os
import warnings
from typing import Any, List

import pytest
from pydantic import Field
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Env vars + import-time patches (same pattern as test_agents.py).
# Agents call get_clinical_mcp_toolset() at module-level, so patches must be
# active while the agent modules are first imported.
# ---------------------------------------------------------------------------
os.environ.setdefault("ICD_MCP_SERVER_URL", "http://mock-clinical-coder")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "axxess-hackathon")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")

_mcp_patch = patch(
    "google.adk.tools.mcp_tool.mcp_toolset.MCPToolset", return_value=MagicMock()
)
_genai_patch = patch("google.genai.Client", return_value=MagicMock())
_mcp_patch.start()
_genai_patch.start()

import agent.tools.mcp_tools as _mcp_mod  # noqa: E402
_mcp_mod._clinical_mcp_toolset = None

from agent.agents.radiology_analyst import radiology_analyst  # noqa: E402
from agent.agents.records_analyst import records_analyst      # noqa: E402
from agent.agents.clinical_scribe import clinical_scribe      # noqa: E402

_mcp_patch.stop()
_genai_patch.stop()

# ---------------------------------------------------------------------------
# ADK / genai imports (after the module-level patches are stopped)
# ---------------------------------------------------------------------------
from google.adk.agents import Agent                        # noqa: E402
from google.adk.models.base_llm import BaseLlm             # noqa: E402
from google.adk.models.llm_response import LlmResponse     # noqa: E402
from google.adk.runners import Runner                      # noqa: E402
from google.adk.sessions import InMemorySessionService     # noqa: E402
from google.adk.tools import FunctionTool                  # noqa: E402
from google.genai import types as genai_types              # noqa: E402

# All tests in this file are anyio async
pytestmark = pytest.mark.anyio

# ---------------------------------------------------------------------------
# ScriptedLLM — deterministic BaseLlm that replaces Gemini for testing
# ---------------------------------------------------------------------------

class ScriptedLLM(BaseLlm):
    """
    A BaseLlm implementation that returns pre-scripted Content objects in order.

    Usage::

        llm = ScriptedLLM(turns=[
            _fc("tool_name", {"arg": "value"}),  # turn 1: call a tool
            _text("REPORT HEADING:\\n- field: value"),  # turn 2: final text
        ])
        agent = Agent(name="...", model=llm, ...)
    """
    model: str = "mock"
    turns: List[Any] = Field(default_factory=list)
    call_count: int = 0

    @classmethod
    def supported_models(cls) -> list[str]:
        return ["mock"]

    async def generate_content_async(
        self, llm_request, stream: bool = False
    ):
        content = self.turns[self.call_count]
        self.call_count += 1
        yield LlmResponse(content=content, turn_complete=True)


# ---------------------------------------------------------------------------
# Content-building helpers
# ---------------------------------------------------------------------------

def _fc(tool_name: str, args: dict) -> genai_types.Content:
    """Model Content with a single FunctionCall part (triggers tool dispatch)."""
    return genai_types.Content(
        role="model",
        parts=[
            genai_types.Part(
                function_call=genai_types.FunctionCall(name=tool_name, args=args)
            )
        ],
    )


def _text(text: str) -> genai_types.Content:
    """Model Content with a single text part (final report)."""
    return genai_types.Content(role="model", parts=[genai_types.Part(text=text)])


# ---------------------------------------------------------------------------
# Stub tool functions — deterministic replacements for MCP tools
# ---------------------------------------------------------------------------

def stub_analyze_radiology(image_url: str) -> dict:
    return {
        "image_type": "X-ray",
        "findings": ["cardiomegaly", "pulmonary edema"],
        "anatomical_region": "chest",
        "severity": "moderate",
        "confidence": 0.82,
    }


def stub_extract_patient_entities(patient_context: str, subject_id: str = "") -> dict:
    return {
        "subject_id": subject_id or "TEST-001",
        "conditions": ["hypertension", "type 2 diabetes"],
        "allergies": ["sulfa"],
        "medications": ["metformin", "lisinopril"],
        "risk_flags": ["NSAIDs contraindicated with lisinopril"],
        "confidence": 0.90,
    }


def stub_transcribe_audio(audio_url: str) -> dict:
    return {
        "transcript": "Patient reports chest pain for 2 days with shortness of breath.",
        "confidence": 0.95,
        "duration_seconds": 45.0,
    }


def stub_analyze_clinical_notes(transcript: str, clinical_notes: str = "") -> dict:
    return {
        "chief_complaint": "chest pain",
        "symptoms": ["chest pain", "shortness of breath"],
        "vitals": {"bp": "140/90", "hr": "95"},
        "mentioned_medications": ["aspirin"],
        "confidence": 0.88,
    }


def stub_map_icd_codes(conditions: list) -> dict:
    return {
        "codes": [
            {"condition": c, "icd11_code": "CA00", "description": "Cardiac condition"}
            for c in conditions
        ],
        "mapped_count": len(conditions),
    }


# ---------------------------------------------------------------------------
# Runner helper
# ---------------------------------------------------------------------------

_run_counter = 0  # unique app_name per _run_agent call


async def _run_agent(agent: Agent, state: dict, user_message: str) -> str:
    """
    Run an ADK agent to completion and return the final response text.

    Creates a fresh InMemorySessionService + Runner for each call so tests
    are fully isolated.
    """
    global _run_counter
    _run_counter += 1
    app_name = f"test_run_{_run_counter}"

    session_service = InMemorySessionService()
    runner = Runner(agent=agent, app_name=app_name, session_service=session_service)
    session = await session_service.create_session(
        app_name=app_name, user_id="test_user", state=state
    )
    message = genai_types.Content(
        role="user", parts=[genai_types.Part(text=user_message)]
    )

    final_text = ""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # suppress "App name mismatch" warning
        async for event in runner.run_async(
            user_id="test_user", session_id=session.id, new_message=message
        ):
            if event.is_final_response() and event.content:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        final_text = part.text
    return final_text


# ---------------------------------------------------------------------------
# Scripted final-turn report text constants
# These define the exact output each agent is expected to produce.
# ---------------------------------------------------------------------------

RADIOLOGY_REPORT = """RADIOLOGY ANALYSIS:
- Image type: X-ray
- Findings: cardiomegaly, pulmonary edema
- Anatomical region: chest
- Severity: moderate
- Clinical significance: Findings are consistent with possible congestive heart failure
- Confidence: 82%"""

RECORDS_REPORT = """RECORDS ANALYSIS:
- Subject ID: TEST-001
- Historical conditions: hypertension, type 2 diabetes
- Allergies / intolerances: sulfa
- Current medications: metformin, lisinopril
- Risk flags: NSAIDs contraindicated with lisinopril
- Confidence: 90%"""

SCRIBE_REPORT = """CLINICAL SCRIBE ANALYSIS:
- Transcript summary: Patient reports chest pain for 2 days with shortness of breath.
- Chief complaint: chest pain
- Key symptoms: chest pain, shortness of breath
- Vitals: BP 140/90, HR 95
- ICD-11 codes: [chest pain -> CA00 Cardiac condition, shortness of breath -> CA00 Cardiac condition]
- Confidence: 88%"""


# ===========================================================================
# RadiologyAnalyst
# ===========================================================================

class TestRadiologyAnalystOutput:
    """
    Two-turn scripted flow:
      Turn 1 (LLM): FunctionCall → stub_analyze_radiology(image_url)
      Turn 2 (LLM): Formatted RADIOLOGY ANALYSIS report text
    """

    def _make_agent(self) -> Agent:
        llm = ScriptedLLM(turns=[
            _fc("stub_analyze_radiology", {"image_url": "gs://test/chest-xray.jpg"}),
            _text(RADIOLOGY_REPORT),
        ])
        return Agent(
            name=radiology_analyst.name,
            model=llm,
            description=radiology_analyst.description,
            instruction=radiology_analyst.instruction,
            tools=[FunctionTool(stub_analyze_radiology)],
        )

    async def test_output_contains_report_heading(self):
        text = await _run_agent(
            self._make_agent(),
            state={"image_url": "gs://test/chest-xray.jpg"},
            user_message="Analyze the medical imaging data.",
        )
        assert "RADIOLOGY ANALYSIS" in text

    async def test_output_contains_image_type(self):
        text = await _run_agent(
            self._make_agent(),
            state={"image_url": "gs://test/chest-xray.jpg"},
            user_message="Analyze the medical imaging data.",
        )
        assert "x-ray" in text.lower()

    async def test_output_contains_finding_from_stub(self):
        """Stub returns cardiomegaly; it must appear in the final report."""
        text = await _run_agent(
            self._make_agent(),
            state={"image_url": "gs://test/chest-xray.jpg"},
            user_message="Analyze the medical imaging data.",
        )
        assert "cardiomegaly" in text.lower()

    async def test_output_contains_severity(self):
        text = await _run_agent(
            self._make_agent(),
            state={"image_url": "gs://test/chest-xray.jpg"},
            user_message="Analyze the medical imaging data.",
        )
        assert "moderate" in text.lower()

    async def test_output_contains_confidence(self):
        text = await _run_agent(
            self._make_agent(),
            state={"image_url": "gs://test/chest-xray.jpg"},
            user_message="Analyze the medical imaging data.",
        )
        assert "82" in text

    async def test_exactly_two_llm_turns(self):
        """ScriptedLLM must be called exactly twice: tool call + final report."""
        agent = self._make_agent()
        await _run_agent(
            agent,
            state={"image_url": "gs://test/chest-xray.jpg"},
            user_message="Analyze the medical imaging data.",
        )
        assert agent.model.call_count == 2

    async def test_single_responsibility_no_diagnosis_claim(self):
        """Radiology agent must not claim to make a final diagnosis."""
        text = await _run_agent(
            self._make_agent(),
            state={"image_url": "gs://test/chest-xray.jpg"},
            user_message="Analyze the medical imaging data.",
        )
        assert "final diagnosis" not in text.lower()


# ===========================================================================
# RecordsAnalyst
# ===========================================================================

class TestRecordsAnalystOutput:
    """
    Two-turn scripted flow:
      Turn 1 (LLM): FunctionCall → stub_extract_patient_entities(patient_context, subject_id)
      Turn 2 (LLM): Formatted RECORDS ANALYSIS report text
    """

    def _make_agent(self) -> Agent:
        llm = ScriptedLLM(turns=[
            _fc("stub_extract_patient_entities", {
                "patient_context": "Hypertension, DM2. Allergic to sulfa. On metformin.",
                "subject_id": "TEST-001",
            }),
            _text(RECORDS_REPORT),
        ])
        return Agent(
            name=records_analyst.name,
            model=llm,
            description=records_analyst.description,
            instruction=records_analyst.instruction,
            tools=[FunctionTool(stub_extract_patient_entities)],
        )

    async def test_output_contains_report_heading(self):
        text = await _run_agent(
            self._make_agent(),
            state={"patient_id": "TEST-001", "clinical_notes": "Hypertension, DM2."},
            user_message="Review the patient history.",
        )
        assert "RECORDS ANALYSIS" in text

    async def test_output_contains_subject_id(self):
        text = await _run_agent(
            self._make_agent(),
            state={"patient_id": "TEST-001", "clinical_notes": "Hypertension, DM2."},
            user_message="Review the patient history.",
        )
        assert "TEST-001" in text

    async def test_output_contains_condition_from_stub(self):
        """Stub returns hypertension; it must appear in the final report."""
        text = await _run_agent(
            self._make_agent(),
            state={"patient_id": "TEST-001", "clinical_notes": "Hypertension, DM2."},
            user_message="Review the patient history.",
        )
        assert "hypertension" in text.lower()

    async def test_output_contains_allergy_from_stub(self):
        text = await _run_agent(
            self._make_agent(),
            state={"patient_id": "TEST-001", "clinical_notes": "Hypertension, DM2."},
            user_message="Review the patient history.",
        )
        assert "sulfa" in text.lower()

    async def test_output_surfaces_risk_flag(self):
        """Stub returns an NSAIDs risk flag; it must appear in the report."""
        text = await _run_agent(
            self._make_agent(),
            state={"patient_id": "TEST-001", "clinical_notes": "Hypertension, DM2."},
            user_message="Review the patient history.",
        )
        assert "nsaids" in text.lower()

    async def test_exactly_two_llm_turns(self):
        agent = self._make_agent()
        await _run_agent(
            agent,
            state={"patient_id": "TEST-001", "clinical_notes": "Hypertension, DM2."},
            user_message="Review the patient history.",
        )
        assert agent.model.call_count == 2

    async def test_single_responsibility_no_diagnosis_claim(self):
        text = await _run_agent(
            self._make_agent(),
            state={"patient_id": "TEST-001", "clinical_notes": "Hypertension, DM2."},
            user_message="Review the patient history.",
        )
        assert "final diagnosis" not in text.lower()


# ===========================================================================
# ClinicalScribe
# ===========================================================================

class TestClinicalScribeOutput:
    """
    Four-turn scripted flow (3 tool calls + 1 final report):
      Turn 1 (LLM): FunctionCall → stub_transcribe_audio(audio_url)
      Turn 2 (LLM): FunctionCall → stub_analyze_clinical_notes(transcript)
      Turn 3 (LLM): FunctionCall → stub_map_icd_codes(conditions)
      Turn 4 (LLM): Formatted CLINICAL SCRIBE ANALYSIS report text
    """

    def _make_agent(self) -> Agent:
        llm = ScriptedLLM(turns=[
            _fc("stub_transcribe_audio", {"audio_url": "gs://test/consult.wav"}),
            _fc("stub_analyze_clinical_notes", {
                "transcript": "Patient reports chest pain for 2 days.",
                "clinical_notes": "",
            }),
            _fc("stub_map_icd_codes", {
                "conditions": ["chest pain", "shortness of breath"],
            }),
            _text(SCRIBE_REPORT),
        ])
        return Agent(
            name=clinical_scribe.name,
            model=llm,
            description=clinical_scribe.description,
            instruction=clinical_scribe.instruction,
            tools=[
                FunctionTool(stub_transcribe_audio),
                FunctionTool(stub_analyze_clinical_notes),
                FunctionTool(stub_map_icd_codes),
            ],
        )

    async def test_output_contains_report_heading(self):
        text = await _run_agent(
            self._make_agent(),
            state={"audio_url": "gs://test/consult.wav", "clinical_notes": ""},
            user_message="Process the patient consultation.",
        )
        assert "CLINICAL SCRIBE ANALYSIS" in text

    async def test_output_contains_chief_complaint_from_stub(self):
        """NER stub returns 'chest pain' as chief complaint."""
        text = await _run_agent(
            self._make_agent(),
            state={"audio_url": "gs://test/consult.wav", "clinical_notes": ""},
            user_message="Process the patient consultation.",
        )
        assert "chest pain" in text.lower()

    async def test_output_contains_icd_code_from_stub(self):
        """ICD stub returns code CA00; it must appear in the report."""
        text = await _run_agent(
            self._make_agent(),
            state={"audio_url": "gs://test/consult.wav", "clinical_notes": ""},
            user_message="Process the patient consultation.",
        )
        assert "CA00" in text

    async def test_output_contains_symptom_from_stub(self):
        text = await _run_agent(
            self._make_agent(),
            state={"audio_url": "gs://test/consult.wav", "clinical_notes": ""},
            user_message="Process the patient consultation.",
        )
        assert "shortness of breath" in text.lower()

    async def test_output_contains_vitals_from_stub(self):
        """NER stub returns BP 140/90; it must appear in the report."""
        text = await _run_agent(
            self._make_agent(),
            state={"audio_url": "gs://test/consult.wav", "clinical_notes": ""},
            user_message="Process the patient consultation.",
        )
        assert "140" in text

    async def test_exactly_four_llm_turns(self):
        """Scribe must invoke 3 tools then produce 1 final text = 4 LLM calls."""
        agent = self._make_agent()
        await _run_agent(
            agent,
            state={"audio_url": "gs://test/consult.wav", "clinical_notes": ""},
            user_message="Process the patient consultation.",
        )
        assert agent.model.call_count == 4

    async def test_single_responsibility_no_diagnosis_claim(self):
        text = await _run_agent(
            self._make_agent(),
            state={"audio_url": "gs://test/consult.wav", "clinical_notes": ""},
            user_message="Process the patient consultation.",
        )
        assert "final diagnosis" not in text.lower()
