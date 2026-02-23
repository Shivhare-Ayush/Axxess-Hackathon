"""
Clinical Coding Tool — ADK-compatible tool for ICD-11 + openFDA pipeline

This replaces/supplements the MCP-based ICD tools.
Works entirely locally without needing MCP server deployment.

Usage in agent:
  from agent.tools.clinical_coding_tool import clinical_coding_tool
  tools=[clinical_coding_tool, ...]
"""

import os
import sys
import logging
import json

logger = logging.getLogger(__name__)

# ─── Import services (adjust path if needed) ─────────────────
# When running inside ADK, PYTHONPATH includes level_1/
# So these imports resolve from level_1/agent/services/
try:
    from agent.services.icd_service import ICDService
    from agent.services.openfda_service import OpenFDAService
except ImportError:
    # Fallback if running standalone
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from services.icd_service import ICDService
    from services.openfda_service import OpenFDAService

_icd = ICDService()
_fda = OpenFDAService()


# ─────────────────────────────────────────────────────────────
# ADK Tool Function
# ─────────────────────────────────────────────────────────────

def run_clinical_coding(symptoms: list[str]) -> dict:
    """
    Given a list of symptoms/conditions, return:
      1. ICD-11 codes for each
      2. FDA treatment suggestions per condition

    This is the core clinical pipeline tool.

    Args:
        symptoms: list of symptom or condition strings
                  e.g. ["chest pain", "shortness of breath", "fever"]

    Returns:
        {
          "icd_mappings": [...],
          "treatment_plan": [...],
          "summary": "plain-text clinical summary"
        }
    """
    if not symptoms:
        return {
            "icd_mappings": [],
            "treatment_plan": [],
            "summary": "No symptoms provided.",
        }

    # Step 1: Map symptoms → ICD-11
    logger.info(f"[ClinicalCoding] Mapping {len(symptoms)} symptoms to ICD-11...")
    icd_mappings = _icd.map_symptoms_to_codes(symptoms)

    # Step 2: Map ICD codes → treatments via openFDA
    logger.info("[ClinicalCoding] Looking up treatments via openFDA...")
    treatment_plan = _fda.bulk_lookup(icd_mappings)

    # Step 3: Build plain-text summary
    summary_lines = ["=== AI-ASSISTED PRELIMINARY CLINICAL ASSESSMENT ===\n"]

    summary_lines.append("SYMPTOM → ICD-11 MAPPING:")
    for m in icd_mappings:
        code = m["icd_code"]
        title = m["icd_title"]
        sym = m["symptom"]
        summary_lines.append(f"  • {sym} → [{code}] {title}")

    summary_lines.append("\nTREATMENT SUGGESTIONS (FDA-labeled, for clinician review):")
    for t in treatment_plan:
        cond = t["condition"]
        icd = t["icd_code"]
        drugs = t.get("treatments", [])
        if drugs:
            drug_names = ", ".join(d["drug_name"] for d in drugs[:3])
            summary_lines.append(f"  • {cond} ({icd}): {drug_names}")
        else:
            summary_lines.append(f"  • {cond} ({icd}): No standard treatments found in FDA database.")

    summary_lines.append(
        "\n⚠️ DISCLAIMER: This is AI-assisted decision support only. "
        "All clinical decisions require licensed clinician review."
    )

    return {
        "icd_mappings": icd_mappings,
        "treatment_plan": treatment_plan,
        "summary": "\n".join(summary_lines),
    }


# ─────────────────────────────────────────────────────────────
# ADK FunctionTool wrapper
# ─────────────────────────────────────────────────────────────
try:
    from google.adk.tools import FunctionTool

    clinical_coding_tool = FunctionTool(func=run_clinical_coding)
    logger.info("[ClinicalCoding] ADK FunctionTool registered.")

except ImportError:
    # Not running inside ADK — tool is still usable directly
    clinical_coding_tool = run_clinical_coding
    logger.warning("[ClinicalCoding] google.adk not found — using raw function.")


# ─────────────────────────────────────────────────────────────
# Standalone test
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    test_symptoms = ["chest pain", "shortness of breath", "fever", "type 2 diabetes"]
    result = run_clinical_coding(test_symptoms)

    print("\n=== RESULT ===")
    print(result["summary"])

    print("\n=== RAW ICD MAPPINGS ===")
    print(json.dumps(result["icd_mappings"], indent=2))