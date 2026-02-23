#!/usr/bin/env python3
"""
MedVisor — ICD-11 + openFDA Integration Test
Run from level_1/ directory:

  source set_env.sh
  python test_clinical_pipeline.py

This verifies:
  1. ICD-11 WHO API token fetch
  2. ICD-11 symptom search
  3. openFDA drug lookup
  4. Full pipeline (symptoms → ICD → treatments)
"""

import os
import sys
import json
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("test")

# ── Path setup ──────────────────────────────────────────────
# Add agent/ to path so we can import services
script_dir = os.path.dirname(os.path.abspath(__file__))
agent_dir = os.path.join(script_dir, "agent")
sys.path.insert(0, agent_dir)

from services.icd_service import ICDService
from services.openfda_service import OpenFDAService

PASS = "✅"
FAIL = "❌"
WARN = "⚠️"


def check_env():
    print("\n──────────────────────────────────────")
    print("1. ENVIRONMENT VARIABLES")
    print("──────────────────────────────────────")
    cid = os.environ.get("ICD_CLIENT_ID", "")
    csec = os.environ.get("ICD_CLIENT_SECRET", "")
    if cid:
        print(f"{PASS} ICD_CLIENT_ID set ({cid[:8]}...)")
    else:
        print(f"{FAIL} ICD_CLIENT_ID NOT SET — run: export ICD_CLIENT_ID=your_id")
    if csec:
        print(f"{PASS} ICD_CLIENT_SECRET set")
    else:
        print(f"{FAIL} ICD_CLIENT_SECRET NOT SET — run: export ICD_CLIENT_SECRET=your_secret")
    return bool(cid and csec)


def test_icd_token():
    print("\n──────────────────────────────────────")
    print("2. ICD-11 TOKEN FETCH")
    print("──────────────────────────────────────")
    svc = ICDService()
    try:
        token = svc._get_token()
        print(f"{PASS} Token fetched: {token[:40]}...")
        return svc
    except Exception as e:
        print(f"{FAIL} Token fetch failed: {e}")
        return None


def test_icd_search(svc):
    print("\n──────────────────────────────────────")
    print("3. ICD-11 SEARCH")
    print("──────────────────────────────────────")
    test_terms = ["chest pain", "Type 2 diabetes", "hypertension"]
    for term in test_terms:
        results = svc.search(term, max_results=2)
        if results:
            top = results[0]
            print(f"{PASS} '{term}' → [{top['code']}] {top['title']}")
        else:
            print(f"{WARN} '{term}' → no results")


def test_icd_bulk_map(svc):
    print("\n──────────────────────────────────────")
    print("4. BULK SYMPTOM → ICD MAPPING")
    print("──────────────────────────────────────")
    symptoms = ["chest pain", "shortness of breath", "fever", "type 2 diabetes"]
    mappings = svc.map_symptoms_to_codes(symptoms)
    for m in mappings:
        code = m["icd_code"]
        title = m["icd_title"]
        sym = m["symptom"]
        icon = PASS if code != "NOT_FOUND" else WARN
        print(f"{icon} {sym} → [{code}] {title}")
    return mappings


def test_openfda(mappings):
    print("\n──────────────────────────────────────")
    print("5. openFDA TREATMENT LOOKUP")
    print("──────────────────────────────────────")
    fda = OpenFDAService()
    found = [m for m in mappings if m["icd_code"] != "NOT_FOUND"][:2]  # test first 2 only
    if not found:
        print(f"{WARN} No valid ICD codes to look up treatments for.")
        return

    for m in found:
        condition = m["icd_title"]
        icd_code = m["icd_code"]
        result = fda.lookup_treatments(condition, icd_code, max_results=3)
        treatments = result.get("treatments", [])
        if treatments:
            names = [t["drug_name"] for t in treatments[:3]]
            print(f"{PASS} {condition} ({icd_code}) → {', '.join(names)}")
        else:
            print(f"{WARN} {condition} ({icd_code}) → no FDA treatments found (try different search term)")


def test_full_pipeline():
    print("\n──────────────────────────────────────")
    print("6. FULL PIPELINE DEMO")
    print("──────────────────────────────────────")
    # Simulate what your agent will do
    from tools.clinical_coding_tool import run_clinical_coding
    symptoms = ["chest pain", "shortness of breath", "type 2 diabetes"]
    result = run_clinical_coding(symptoms)
    print(result["summary"])


if __name__ == "__main__":
    print("\n🩺 MedVisor — Clinical Pipeline Test")
    print("=" * 50)

    has_env = check_env()
    if not has_env:
        print(f"\n{FAIL} Cannot continue without ICD credentials.")
        print("Run:\n  export ICD_CLIENT_ID=your_client_id")
        print("  export ICD_CLIENT_SECRET=your_client_secret")
        sys.exit(1)

    svc = test_icd_token()
    if not svc:
        print(f"\n{FAIL} ICD token failed — check credentials.")
        sys.exit(1)

    test_icd_search(svc)
    mappings = test_icd_bulk_map(svc)
    test_openfda(mappings)

    print("\n──────────────────────────────────────")
    print("7. FULL PIPELINE (requires ADK imports)")
    print("──────────────────────────────────────")
    try:
        test_full_pipeline()
    except ImportError as e:
        print(f"{WARN} Skipping full pipeline test (ADK not in path): {e}")

    print("\n✅ Tests complete.")