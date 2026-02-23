"""
icd_tools.py — ADK-compatible ICD lookup tool

Replaces the old Tool-based implementation.
ADK uses FunctionTool, not Tool.
"""

import os
import logging

logger = logging.getLogger(__name__)

try:
    from agent.services.icd_service import ICDService
except ImportError:
    from services.icd_service import ICDService

_icd = ICDService()


def icd_lookup(query: str) -> list[dict]:
    """
    Search ICD-11 for a medical condition or symptom.

    Args:
        query: symptom or condition string (e.g. "chest pain")

    Returns:
        List of matching ICD-11 codes with titles.
    """
    return _icd.search(query, max_results=5)


# ADK FunctionTool wrapper
try:
    from google.adk.tools import FunctionTool
    icd_lookup_tool = FunctionTool(func=icd_lookup)
    logger.info("[icd_tools] FunctionTool registered.")
except ImportError:
    icd_lookup_tool = icd_lookup
    logger.warning("[icd_tools] google.adk not found — using raw function.")