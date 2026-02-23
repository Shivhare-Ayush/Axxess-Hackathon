"""
mcp_tools.py — MCP toolset loader with graceful fallback.

If ICD_MCP_SERVER_URL is not set, returns None instead of crashing.
Agents that call get_clinical_mcp_toolset() must handle None gracefully.
"""

import os
import logging

logger = logging.getLogger(__name__)


def get_clinical_mcp_toolset():
    """
    Load the MCP toolset from the remote clinical coder server.

    Returns None if ICD_MCP_SERVER_URL is not set — callers should
    fall back to local clinical_coding_tool in that case.
    """
    url = os.environ.get("ICD_MCP_SERVER_URL", "").strip()

    if not url:
        logger.warning(
            "[MCP Tools] ICD_MCP_SERVER_URL not set — skipping MCP, "
            "using local clinical_coding_tool instead."
        )
        return None

    try:
        from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, SseServerParams

        logger.info(f"[MCP Tools] Connecting to: {url}")
        return MCPToolset(
            connection_params=SseServerParams(url=f"{url}/mcp")
        )
    except Exception as e:
        logger.error(f"[MCP Tools] Failed to connect to MCP server: {e}")
        return None