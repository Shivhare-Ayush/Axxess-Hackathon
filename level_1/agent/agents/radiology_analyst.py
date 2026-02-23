"""
RadiologyAnalyst Agent

Analyzes medical images (X-ray, MRI, CT, dermatological) for anomalies.
Uses MCP server if available, otherwise operates without image tools
and relies on Gemini's built-in vision capabilities.
"""

import logging
from google.adk.agents import Agent

logger = logging.getLogger(__name__)

# ── MCP toolset (optional) ────────────────────────────────────
try:
    from agent.tools.mcp_tools import get_clinical_mcp_toolset
    _mcp = get_clinical_mcp_toolset()
    _tools = [_mcp] if _mcp is not None else []
    if _mcp:
        logger.info("[RadiologyAnalyst] MCP toolset loaded.")
    else:
        logger.warning("[RadiologyAnalyst] No MCP toolset — running without image tools.")
except Exception as e:
    _tools = []
    logger.warning(f"[RadiologyAnalyst] MCP import failed: {e}")


radiology_analyst = Agent(
    name="RadiologyAnalyst",
    model="gemini-2.5-flash",
    description=(
        "Analyzes medical images (X-ray, MRI, CT, dermatological photos) "
        "for anomalies, findings, and severity assessment."
    ),
    instruction="""You are a Radiology AI Analyst specializing in medical image interpretation.

## INPUT
- Image URL: {image_url}

## YOUR TASK

If image_url is a valid gs:// or https:// URL:
  - Use the analyze_radiology MCP tool if available
  - Otherwise describe what you would look for given the clinical context

If image_url is "Not provided" or unavailable:
  - State clearly that no imaging was provided
  - Note what imaging would be recommended given available symptoms
  - Do NOT ask the user for an image URL — just proceed

## OUTPUT FORMAT

RADIOLOGY ANALYSIS:
- Image type: [X-ray / MRI / CT / dermatological / not provided]
- Anatomical region: [region or N/A]
- Findings: [list findings or "No image available"]
- Severity: [none / mild / moderate / severe / N/A]
- Recommendations: [suggested imaging if none provided]
- Confidence: [0-100]%

Always complete your report even without an image.
""",
    tools=_tools,
)