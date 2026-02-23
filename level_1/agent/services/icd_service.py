"""
ICD-11 WHO API Service
Converts symptoms/conditions → official ICD-11 codes

Setup:
  export ICD_CLIENT_ID="your_client_id"
  export ICD_CLIENT_SECRET="your_client_secret"

WHO API Docs: https://icdaccessmanagement.who.int
"""

import os
import time
import logging
import requests
from urllib.parse import quote

logger = logging.getLogger(__name__)

TOKEN_URL = "https://icdaccessmanagement.who.int/connect/token"
SEARCH_URL = "https://id.who.int/icd/release/11/2024-01/mms/search"
ENTITY_URL = "https://id.who.int/icd/release/11/2024-01/mms"


class ICDService:
    def __init__(self):
        self.client_id = os.environ.get("ICD_CLIENT_ID", "")
        self.client_secret = os.environ.get("ICD_CLIENT_SECRET", "")
        self._token = None
        self._token_expiry = 0

        if not self.client_id or not self.client_secret:
            logger.warning(
                "[ICDService] ICD_CLIENT_ID or ICD_CLIENT_SECRET not set. "
                "ICD validation will be disabled."
            )

    @property
    def is_configured(self):
        return bool(self.client_id and self.client_secret)

    def _get_token(self) -> str:
        """Fetch or reuse OAuth2 bearer token from WHO."""
        if self._token and time.time() < self._token_expiry:
            return self._token

        if not self.is_configured:
            raise ValueError(
                "ICD_CLIENT_ID and ICD_CLIENT_SECRET must be set as environment variables.\n"
                "Run: export ICD_CLIENT_ID=... && export ICD_CLIENT_SECRET=..."
            )

        logger.info("[ICDService] Fetching new token from WHO...")
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "icdapi_access",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )

        if resp.status_code != 200:
            logger.error(f"[ICDService] Token fetch failed: {resp.status_code} {resp.text}")
            resp.raise_for_status()

        data = resp.json()
        self._token = data["access_token"]
        # Expire 60s early to be safe
        self._token_expiry = time.time() + data.get("expires_in", 3600) - 60
        logger.info("[ICDService] Token fetched successfully.")
        return self._token

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Accept": "application/json",
            "Accept-Language": "en",
            "API-Version": "v2",
        }

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        """
        Search ICD-11 for a symptom or condition.

        Returns list of:
          {
            "code": "5A11",
            "title": "Type 2 diabetes mellitus",
            "url": "https://id.who.int/..."
          }
        """
        if not query or not query.strip():
            return []

        if not self.is_configured:
            logger.warning("[ICDService] Skipping ICD search — credentials not configured.")
            return []

        try:
            resp = requests.get(
                SEARCH_URL,
                headers=self._auth_headers(),
                params={
                    "q": query,
                    "includeKeywordResult": "false",
                    "useFlexisearch": "true",
                    "flatResults": "true",
                    "highlightingEnabled": "false",
                    "medicalCodingMode": "false",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for entity in data.get("destinationEntities", [])[:max_results]:
                code = entity.get("theCode") or entity.get("code", "")
                title = entity.get("title", "")
                # strip HTML tags if present
                import re
                title = re.sub(r"<[^>]+>", "", title)
                if code and title:
                    results.append({
                        "code": code,
                        "title": title,
                        "url": entity.get("id", ""),
                    })

            logger.info(f"[ICDService] '{query}' → {len(results)} results")
            return results

        except requests.HTTPError as e:
            logger.error(f"[ICDService] HTTP error searching '{query}': {e}")
            return []
        except Exception as e:
            logger.error(f"[ICDService] Unexpected error: {e}")
            return []

    def map_symptoms_to_codes(self, symptoms: list[str]) -> list[dict]:
        """
        Take a list of symptoms/conditions and return ICD-11 codes.

        Returns list of:
          {
            "symptom": "chest pain",
            "icd_code": "MD81",
            "icd_title": "Chest pain",
            "confidence": "high"
          }
        """
        results = []
        for symptom in symptoms:
            hits = self.search(symptom, max_results=1)
            if hits:
                results.append({
                    "symptom": symptom,
                    "icd_code": hits[0]["code"],
                    "icd_title": hits[0]["title"],
                    "confidence": "high",
                })
            else:
                results.append({
                    "symptom": symptom,
                    "icd_code": "NOT_FOUND",
                    "icd_title": "No ICD-11 match found",
                    "confidence": "none",
                })
        return results


# ─────────────────────────────────────────────────────────────
# Standalone test
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json, sys
    logging.basicConfig(level=logging.INFO)

    svc = ICDService()
    test_symptoms = ["chest pain", "shortness of breath", "Type 2 diabetes"]

    print("\n=== ICD-11 LOOKUP TEST ===")
    for sym in test_symptoms:
        results = svc.search(sym, max_results=2)
        print(f"\n'{sym}':")
        print(json.dumps(results, indent=2))

    print("\n=== BULK SYMPTOM MAPPING ===")
    mapped = svc.map_symptoms_to_codes(test_symptoms)
    print(json.dumps(mapped, indent=2))