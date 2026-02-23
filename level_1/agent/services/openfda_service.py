"""
openFDA Drug Lookup Service
Maps ICD codes / conditions → treatment suggestions

Uses: https://api.fda.gov/drug/label.json
No API key required for basic use (rate limited to 240 req/min).
Optional: set OPENFDA_API_KEY for higher limits.

Docs: https://open.fda.gov/apis/drug/label/
"""

import os
import logging
import requests
from urllib.parse import quote

logger = logging.getLogger(__name__)

OPENFDA_BASE = "https://api.fda.gov/drug/label.json"


class OpenFDAService:
    def __init__(self):
        self.api_key = os.environ.get("OPENFDA_API_KEY", "")
        # Common condition → drug class mappings for fallback
        self._condition_aliases = {
            "type 2 diabetes": ["metformin", "insulin", "diabetes"],
            "hypertension": ["amlodipine", "lisinopril", "blood pressure"],
            "chest pain": ["nitroglycerin", "aspirin", "angina"],
            "infection": ["amoxicillin", "antibiotic"],
            "depression": ["sertraline", "fluoxetine", "antidepressant"],
            "asthma": ["albuterol", "inhaler", "corticosteroid"],
            "pain": ["ibuprofen", "acetaminophen", "analgesic"],
        }

    def _build_url(self, query: str, limit: int = 5) -> str:
        params = f"search={quote(query)}&limit={limit}"
        if self.api_key:
            params += f"&api_key={self.api_key}"
        return f"{OPENFDA_BASE}?{params}"

    def lookup_treatments(self, condition: str, icd_code: str = "", max_results: int = 5) -> dict:
        """
        Look up FDA-approved drugs/treatments for a condition.

        Returns:
          {
            "condition": "Type 2 diabetes",
            "icd_code": "5A11",
            "treatments": [
              {
                "drug_name": "METFORMIN HYDROCHLORIDE",
                "purpose": "Antidiabetic",
                "indications": "...",
                "warnings": "...",
                "dosage_forms": "..."
              }
            ],
            "source": "openFDA"
          }
        """
        search_term = condition.lower()

        # Try searching by indication
        treatments = self._search_by_indication(search_term, max_results)

        if not treatments:
            # Fallback: search by known alias
            for alias_key, alias_terms in self._condition_aliases.items():
                if alias_key in search_term or any(t in search_term for t in alias_terms):
                    treatments = self._search_by_indication(alias_terms[0], max_results)
                    break

        return {
            "condition": condition,
            "icd_code": icd_code,
            "treatments": treatments,
            "source": "openFDA",
            "disclaimer": (
                "These are FDA-labeled drug indications for informational purposes only. "
                "Treatment decisions must be made by a licensed clinician."
            ),
        }

    def _search_by_indication(self, term: str, limit: int) -> list[dict]:
        """Query FDA drug labels by indication text."""
        query = f'indications_and_usage:"{term}"'
        url = self._build_url(query, limit)

        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code == 404:
                # No results found
                return []
            resp.raise_for_status()
            data = resp.json()

            results = []
            for result in data.get("results", []):
                openfda = result.get("openfda", {})
                brand_names = openfda.get("brand_name", [])
                generic_names = openfda.get("generic_name", [])
                substance_names = openfda.get("substance_name", [])

                drug_name = (
                    brand_names[0] if brand_names else
                    generic_names[0] if generic_names else
                    substance_names[0] if substance_names else
                    "Unknown"
                )

                indications_raw = result.get("indications_and_usage", [""])
                indications = indications_raw[0][:500] if indications_raw else ""

                warnings_raw = result.get("warnings", [""])
                warnings = warnings_raw[0][:300] if warnings_raw else ""

                dosage_raw = result.get("dosage_and_administration", [""])
                dosage = dosage_raw[0][:300] if dosage_raw else ""

                purpose_raw = result.get("purpose", [""])
                purpose = purpose_raw[0][:200] if purpose_raw else ""

                results.append({
                    "drug_name": drug_name,
                    "purpose": purpose,
                    "indications": indications,
                    "warnings": warnings,
                    "dosage_info": dosage,
                    "route": openfda.get("route", []),
                })

            logger.info(f"[OpenFDA] '{term}' → {len(results)} results")
            return results

        except requests.HTTPError as e:
            logger.error(f"[OpenFDA] HTTP error for '{term}': {e}")
            return []
        except Exception as e:
            logger.error(f"[OpenFDA] Unexpected error: {e}")
            return []

    def bulk_lookup(self, icd_results: list[dict]) -> list[dict]:
        """
        Given a list of ICD mappings, look up treatments for each.

        Input: [{"symptom": "...", "icd_code": "...", "icd_title": "..."}]
        Returns: [{"condition": ..., "icd_code": ..., "treatments": [...]}]
        """
        treatment_results = []
        for item in icd_results:
            condition = item.get("icd_title") or item.get("symptom", "")
            icd_code = item.get("icd_code", "")
            if condition and icd_code != "NOT_FOUND":
                result = self.lookup_treatments(condition, icd_code)
                treatment_results.append(result)
        return treatment_results


# ─────────────────────────────────────────────────────────────
# Standalone test
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO)

    svc = OpenFDAService()
    conditions = [
        ("Type 2 diabetes mellitus", "5A11"),
        ("Hypertension", "BA00"),
    ]

    for condition, icd_code in conditions:
        print(f"\n=== {condition} ({icd_code}) ===")
        result = svc.lookup_treatments(condition, icd_code, max_results=3)
        # Print summary
        print(f"Found {len(result['treatments'])} treatments")
        for t in result["treatments"]:
            print(f"  - {t['drug_name']}: {t['purpose'][:80]}")