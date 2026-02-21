"""
Tests for the Clinical Coder MCP server tools.

Strategy
--------
The MCP server lives in `mcp-server/main.py` (directory name has a hyphen, so
it is not a normal importable package). We use importlib to load it by path,
mocking all heavy external dependencies *before* the module-level code runs:

  - fastmcp.FastMCP          → passthrough @tool() decorator so functions stay callable
  - google.genai.Client      → mock Gemini client; per-test responses are configured
  - simple_icd_11            → mock ICD library; per-test return values are configured
  - pydantic.Field           → passthrough so Annotated[..., Field(...)] stays valid

Tests are grouped by tool and cover:
  * happy-path JSON structure (all expected keys present, correct values)
  * edge cases (empty input, unknown condition, bad Gemini JSON)
"""

import sys
import json
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path to the MCP server source file
# ---------------------------------------------------------------------------
MCP_SERVER_PATH = Path(__file__).parent.parent / "mcp-server" / "main.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gemini_response(payload: dict) -> MagicMock:
    """Return a mock Gemini response whose .text is serialized JSON."""
    mock_resp = MagicMock()
    mock_resp.text = json.dumps(payload)
    return mock_resp


def _bad_gemini_response(text: str = "not valid json") -> MagicMock:
    """Return a mock Gemini response with unparseable text."""
    mock_resp = MagicMock()
    mock_resp.text = text
    return mock_resp


# ---------------------------------------------------------------------------
# Module-scoped fixture: load mcp_main once with mocked deps
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def mcp_tools():
    """
    Load mcp-server/main.py with external dependencies mocked.

    Returns the loaded module. Test-scoped helpers are attached as attributes:
      module._mock_icd         – simple_icd_11 mock
      module._mock_genai_client – genai.Client() instance mock
    """
    # --- ICD-11 library mock ---
    mock_icd = MagicMock()
    mock_icd.search.return_value = ["CA00"]
    mock_icd.get_description.return_value = "Certain infectious or parasitic diseases"

    # --- FastMCP mock: @mcp.tool() must be a passthrough decorator ---
    mock_mcp_instance = MagicMock()
    mock_mcp_instance.tool.return_value = lambda f: f   # identity decorator
    mock_fastmcp = MagicMock()
    mock_fastmcp.FastMCP.return_value = mock_mcp_instance

    # --- Gemini client mock ---
    mock_genai_client = MagicMock()
    mock_genai = MagicMock()
    mock_genai.Client.return_value = mock_genai_client
    mock_genai_types = MagicMock()

    # --- google top-level namespace ---
    mock_google = MagicMock()
    mock_google.genai = mock_genai

    # --- pydantic: Field must be callable and return something benign ---
    mock_pydantic = MagicMock()
    mock_pydantic.Field.side_effect = lambda **kw: None   # Field(...) → None

    fake_modules = {
        "simple_icd_11":       mock_icd,
        "fastmcp":             mock_fastmcp,
        "google":              mock_google,
        "google.genai":        mock_genai,
        "google.genai.types":  mock_genai_types,
        "pydantic":            mock_pydantic,
        "anyio":               MagicMock(),
    }

    with patch.dict(sys.modules, fake_modules):
        spec = importlib.util.spec_from_file_location("mcp_main", str(MCP_SERVER_PATH))
        module = importlib.util.module_from_spec(spec)
        sys.modules["mcp_main"] = module
        spec.loader.exec_module(module)

    # Attach mock handles so individual tests can reconfigure them
    module._mock_icd = mock_icd
    module._mock_genai_client = mock_genai_client
    return module


# ===========================================================================
# Tests: analyze_clinical_notes
# ===========================================================================

class TestAnalyzeClinicalNotes:

    def test_returns_all_required_keys(self, mcp_tools):
        mcp_tools._mock_genai_client.models.generate_content.return_value = _gemini_response({
            "chief_complaint": "chest pain",
            "symptoms": ["chest pain", "shortness of breath"],
            "vitals": {"bp": "140/90", "hr": "95"},
            "mentioned_medications": ["aspirin"],
            "confidence": 0.88,
        })

        result = mcp_tools.analyze_clinical_notes(
            transcript="Patient reports severe chest pain radiating to the left arm."
        )

        assert "chief_complaint" in result
        assert "symptoms" in result
        assert "vitals" in result
        assert "mentioned_medications" in result
        assert "confidence" in result

    def test_chief_complaint_value(self, mcp_tools):
        mcp_tools._mock_genai_client.models.generate_content.return_value = _gemini_response({
            "chief_complaint": "chest pain",
            "symptoms": ["chest pain"],
            "vitals": {},
            "mentioned_medications": [],
            "confidence": 0.9,
        })

        result = mcp_tools.analyze_clinical_notes(
            transcript="Patient presents with chest pain."
        )

        assert result["chief_complaint"] == "chest pain"
        assert isinstance(result["symptoms"], list)
        assert "chest pain" in result["symptoms"]

    def test_uses_clinical_notes_when_transcript_empty(self, mcp_tools):
        mcp_tools._mock_genai_client.models.generate_content.return_value = _gemini_response({
            "chief_complaint": "headache",
            "symptoms": ["headache", "nausea"],
            "vitals": {},
            "mentioned_medications": [],
            "confidence": 0.75,
        })

        result = mcp_tools.analyze_clinical_notes(
            transcript="",
            clinical_notes="Patient c/o headache x3 days with associated nausea."
        )

        assert result["chief_complaint"] == "headache"
        assert "headache" in result["symptoms"]

    def test_defaults_filled_on_bad_json(self, mcp_tools):
        mcp_tools._mock_genai_client.models.generate_content.return_value = (
            _bad_gemini_response("not json at all")
        )

        result = mcp_tools.analyze_clinical_notes(transcript="some text")

        # parse_json_response returns {"error": ...}; setdefault fills the rest
        assert "symptoms" in result
        assert "vitals" in result
        assert "mentioned_medications" in result
        assert isinstance(result["symptoms"], list)
        assert isinstance(result["vitals"], dict)


# ===========================================================================
# Tests: analyze_radiology
# ===========================================================================

class TestAnalyzeRadiology:

    def test_returns_all_required_keys(self, mcp_tools):
        mcp_tools._mock_genai_client.models.generate_content.return_value = _gemini_response({
            "image_type": "X-ray",
            "findings": ["cardiomegaly", "pulmonary edema"],
            "anatomical_region": "chest",
            "severity": "moderate",
            "confidence": 0.82,
        })

        result = mcp_tools.analyze_radiology("gs://test-bucket/patient-xray.jpg")

        assert "image_type" in result
        assert "findings" in result
        assert "anatomical_region" in result
        assert "severity" in result
        assert "confidence" in result

    def test_findings_content(self, mcp_tools):
        mcp_tools._mock_genai_client.models.generate_content.return_value = _gemini_response({
            "image_type": "X-ray",
            "findings": ["cardiomegaly", "pulmonary edema"],
            "anatomical_region": "chest",
            "severity": "moderate",
            "confidence": 0.82,
        })

        result = mcp_tools.analyze_radiology("gs://test-bucket/patient-xray.jpg")

        assert result["image_type"] == "X-ray"
        assert isinstance(result["findings"], list)
        assert "cardiomegaly" in result["findings"]
        assert result["severity"] == "moderate"

    def test_no_findings_returns_empty_list(self, mcp_tools):
        mcp_tools._mock_genai_client.models.generate_content.return_value = _gemini_response({
            "image_type": "MRI",
            "findings": [],
            "anatomical_region": "brain",
            "severity": "none",
            "confidence": 0.95,
        })

        result = mcp_tools.analyze_radiology("gs://bucket/brain-mri.jpg")

        assert result["findings"] == []
        assert result["severity"] == "none"

    def test_defaults_filled_on_bad_json(self, mcp_tools):
        mcp_tools._mock_genai_client.models.generate_content.return_value = (
            _bad_gemini_response("```bad json```")
        )

        result = mcp_tools.analyze_radiology("gs://bucket/blurry.jpg")

        assert "findings" in result
        assert "image_type" in result
        assert result["image_type"] == "unknown"
        assert isinstance(result["findings"], list)


# ===========================================================================
# Tests: extract_patient_entities
# ===========================================================================

class TestExtractPatientEntities:

    def test_subject_id_explicit_param_takes_precedence(self, mcp_tools):
        """Explicit subject_id arg must override whatever Gemini returns."""
        mcp_tools._mock_genai_client.models.generate_content.return_value = _gemini_response({
            "subject_id": "WRONG_ID",   # Gemini might extract the wrong ID
            "conditions": ["hypertension"],
            "allergies": ["penicillin"],
            "medications": ["lisinopril"],
            "risk_flags": [],
            "confidence": 0.91,
        })

        result = mcp_tools.extract_patient_entities(
            patient_context="Patient 99999. HTN. Allergic to penicillin.",
            subject_id="99999"
        )

        assert result["subject_id"] == "99999"

    def test_returns_all_required_keys(self, mcp_tools):
        mcp_tools._mock_genai_client.models.generate_content.return_value = _gemini_response({
            "subject_id": "12345",
            "conditions": ["type 2 diabetes", "hypertension"],
            "allergies": ["sulfa"],
            "medications": ["metformin", "amlodipine"],
            "risk_flags": ["drug interaction: metformin + contrast dye"],
            "confidence": 0.87,
        })

        result = mcp_tools.extract_patient_entities(
            patient_context="Patient ID 12345. DM2, HTN. Allergy: sulfa. Meds: metformin, amlodipine.",
            subject_id="12345"
        )

        assert "subject_id" in result
        assert "conditions" in result
        assert "allergies" in result
        assert "medications" in result
        assert "risk_flags" in result
        assert "confidence" in result

    def test_conditions_and_allergies_are_lists(self, mcp_tools):
        mcp_tools._mock_genai_client.models.generate_content.return_value = _gemini_response({
            "subject_id": "12345",
            "conditions": ["type 2 diabetes", "hypertension"],
            "allergies": ["sulfa"],
            "medications": ["metformin", "amlodipine"],
            "risk_flags": [],
            "confidence": 0.87,
        })

        result = mcp_tools.extract_patient_entities(
            patient_context="Patient ID 12345. DM2, HTN.",
            subject_id="12345"
        )

        assert isinstance(result["conditions"], list)
        assert isinstance(result["allergies"], list)
        assert isinstance(result["medications"], list)
        assert isinstance(result["risk_flags"], list)
        assert "hypertension" in result["conditions"]
        assert "sulfa" in result["allergies"]

    def test_no_subject_id_param_defaults_to_empty_string(self, mcp_tools):
        """When subject_id is not passed, output subject_id defaults to ''."""
        mcp_tools._mock_genai_client.models.generate_content.return_value = _gemini_response({
            "conditions": [],
            "allergies": [],
            "medications": [],
            "risk_flags": [],
            "confidence": 0.5,
        })

        result = mcp_tools.extract_patient_entities(
            patient_context="Unknown patient, no history available."
        )

        assert "subject_id" in result
        assert result["subject_id"] == ""

    def test_risk_flags_surfaced(self, mcp_tools):
        mcp_tools._mock_genai_client.models.generate_content.return_value = _gemini_response({
            "subject_id": "77777",
            "conditions": ["CKD stage 3"],
            "allergies": [],
            "medications": ["NSAIDs"],
            "risk_flags": ["NSAIDs contraindicated in CKD"],
            "confidence": 0.93,
        })

        result = mcp_tools.extract_patient_entities(
            patient_context="CKD stage 3, taking NSAIDs.",
            subject_id="77777"
        )

        assert len(result["risk_flags"]) > 0
        assert any("NSAIDs" in flag for flag in result["risk_flags"])


# ===========================================================================
# Tests: map_icd_codes
# ===========================================================================

class TestMapIcdCodes:

    def test_known_condition_returns_code(self, mcp_tools):
        mcp_tools._mock_icd.search.return_value = ["CA00"]
        mcp_tools._mock_icd.get_description.return_value = "Certain infectious or parasitic diseases"
        mcp_tools._mock_icd.search.side_effect = None
        mcp_tools._mock_icd.get_description.side_effect = None

        result = mcp_tools.map_icd_codes(["pneumonia"])

        assert "codes" in result
        assert "mapped_count" in result
        assert result["mapped_count"] == 1
        assert result["codes"][0]["condition"] == "pneumonia"
        assert result["codes"][0]["icd11_code"] == "CA00"
        assert result["codes"][0]["description"] == "Certain infectious or parasitic diseases"

    def test_unknown_condition_code_is_none(self, mcp_tools):
        mcp_tools._mock_icd.search.return_value = []
        mcp_tools._mock_icd.search.side_effect = None

        result = mcp_tools.map_icd_codes(["xyzzy_nonexistent_disease"])

        assert result["codes"][0]["icd11_code"] is None
        assert result["mapped_count"] == 0

    def test_multiple_conditions_all_mapped(self, mcp_tools):
        mcp_tools._mock_icd.search.return_value = ["CA00"]
        mcp_tools._mock_icd.get_description.return_value = "Some disease"
        mcp_tools._mock_icd.search.side_effect = None
        mcp_tools._mock_icd.get_description.side_effect = None

        result = mcp_tools.map_icd_codes(["pneumonia", "hypertension"])

        assert len(result["codes"]) == 2
        assert result["mapped_count"] == 2
        assert all("condition" in c for c in result["codes"])
        assert all("icd11_code" in c for c in result["codes"])
        assert all("description" in c for c in result["codes"])

    def test_empty_list_returns_zero(self, mcp_tools):
        result = mcp_tools.map_icd_codes([])

        assert result["codes"] == []
        assert result["mapped_count"] == 0

    def test_partial_match_reflected_in_mapped_count(self, mcp_tools):
        """One condition maps, one doesn't → mapped_count == 1."""
        def search_side_effect(condition):
            return ["CA00"] if condition == "pneumonia" else []

        mcp_tools._mock_icd.search.side_effect = search_side_effect
        mcp_tools._mock_icd.get_description.return_value = "Infectious disease"
        mcp_tools._mock_icd.get_description.side_effect = None

        result = mcp_tools.map_icd_codes(["pneumonia", "xyzzy_nonexistent"])

        assert result["mapped_count"] == 1
        codes_by_condition = {c["condition"]: c for c in result["codes"]}
        assert codes_by_condition["pneumonia"]["icd11_code"] == "CA00"
        assert codes_by_condition["xyzzy_nonexistent"]["icd11_code"] is None

        # Reset side_effect for subsequent tests
        mcp_tools._mock_icd.search.side_effect = None
