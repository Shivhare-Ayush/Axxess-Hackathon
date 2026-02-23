"""
Patched MCP server ICD mapper.

The original used `simple_icd_11.search()` which doesn't exist.
This version calls the WHO ICD-11 REST API instead.

Place this at: level_1/mcp-server/icd_mapper.py
(or wherever your MCP server's ICD mapping code lives)
"""

import os
import time
import logging
import requests

logger = logging.getLogger(__name__)

TOKEN_URL = "https://icdaccessmanagement.who.int/connect/token"
SEARCH_URL = "https://id.who.int/icd/release/11/2024-01/mms/search"

# Module-level token cache
_token = None
_token_expiry = 0


def _get_token() -> str:
    global _token, _token_expiry
    if _token and time.time() < _token_expiry:
        return _token

    client_id = os.environ.get("ICD_CLIENT_ID", "")
    client_secret = os.environ.get("ICD_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        raise ValueError(
            "ICD_CLIENT_ID and ICD_CLIENT_SECRET must be set.\n"
            "Run: source set_env.sh"
        )

    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "icdapi_access",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    _token = data["access_token"]
    _token_expiry = time.time() + data.get("expires_in", 3600) - 60
    return _token


def search_icd(condition: str) -> dict:
    """
    Search ICD-11 for a single condition/symptom.
    Returns: {"code": "...", "title": "...", "error": None}
    """
    if not condition or not condition.strip():
        return {"code": None, "title": None, "error": "Empty query"}

    try:
        token = _get_token()
        resp = requests.get(
            SEARCH_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Accept-Language": "en",
                "API-Version": "v2",
            },
            params={
                "q": condition,
                "useFlexisearch": "true",
                "flatResults": "true",
                "highlightingEnabled": "false",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        entities = data.get("destinationEntities", [])
        if not entities:
            return {"code": None, "title": None, "error": "No match found"}

        import re
        top = entities[0]
        code = top.get("theCode") or top.get("code", "")
        title = re.sub(r"<[^>]+>", "", top.get("title", ""))
        return {"code": code, "title": title, "error": None}

    except Exception as e:
        logger.error(f"[icd_mapper] Error for '{condition}': {e}")
        return {"code": None, "title": None, "error": str(e)}


def map_conditions_to_icd(conditions: list[str]) -> list[dict]:
    """
    Map a list of conditions to ICD-11 codes.

    Returns:
      [{"condition": ..., "icd11_code": ..., "description": ...}]
    """
    results = []
    for condition in conditions:
        result = search_icd(condition)
        results.append({
            "condition": condition,
            "icd11_code": result["code"],
            "description": result["title"] or result.get("error", "Unknown"),
        })
    return results