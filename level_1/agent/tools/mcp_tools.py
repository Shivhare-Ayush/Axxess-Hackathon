"""
MCP Tool Connections

This module provides the connection to the custom clinical-coder MCP server
deployed on Cloud Run.

Connection Pattern: StreamableHTTP
- Uses StreamableHTTPConnectionParams for HTTP-based MCP communication
- The MCP endpoint is at: {ICD_MCP_SERVER_URL}/mcp
- This is the CUSTOM MCP pattern

The MCP server exposes all four clinical tools via a single toolset:
- analyze_clinical_notes:   NER on consultation transcript / notes
- analyze_radiology:        Gemini Vision on medical imaging
- extract_patient_entities: EMR entity extraction (subject_id, conditions, …)
- map_icd_codes:            ICD-11 code lookup via simple-icd-11
"""

import os
import logging

from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams

logger = logging.getLogger(__name__)

ICD_MCP_SERVER_URL = os.environ.get("ICD_MCP_SERVER_URL")

_clinical_mcp_toolset = None


def get_clinical_mcp_toolset():
    """
    Get the MCPToolset connected to the clinical-coder server.

    The returned toolset exposes all tools on the server. Each specialist
    agent is directed by its instruction to call only the relevant tool.
    """
    global _clinical_mcp_toolset

    if _clinical_mcp_toolset is not None:
        return _clinical_mcp_toolset

    if not ICD_MCP_SERVER_URL:
        raise ValueError(
            "ICD_MCP_SERVER_URL not set. Please run:\n"
            "  export ICD_MCP_SERVER_URL='https://clinical-coder-xxx.a.run.app'"
        )

    mcp_endpoint = f"{ICD_MCP_SERVER_URL}/mcp"
    logger.info(f"[MCP Tools] Connecting to: {mcp_endpoint}")

    _clinical_mcp_toolset = MCPToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=mcp_endpoint,
            timeout=120,
        )
    )

    return _clinical_mcp_toolset
