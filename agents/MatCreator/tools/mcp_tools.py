"""Toolset configuration for the MatCreator execution agent.

Builds ``TOOLSETS`` — a list of ADK tool objects (sub-agent tools, MCP
toolsets) that are injected into the execution agent at startup.  MCP
server endpoints are probed via TCP before inclusion so that unavailable
servers are skipped gracefully.
"""

# Tools configuration 
import socket
import logging
from urllib.parse import urlparse
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import SseServerParams


def _is_sse_server_active(url: str, timeout: float = 2.0) -> bool:
    """Probe host:port via TCP; return True if the server is reachable."""
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 80
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        logging.warning(f"MCP server at {url} is not reachable — skipping toolset.")
        return False


## All tool sets
MCP_TOOLSETS = []

# Database toolset
_url = "http://localhost:50001/sse"
if _is_sse_server_active(_url):
    MCP_TOOLSETS.append(
        McpToolset(
            connection_params=SseServerParams(
                url=_url,
                sse_read_timeout=3600,
            )
        )
    )

# DPA toolset
_url = "http://localhost:50002/sse"
if _is_sse_server_active(_url):
    MCP_TOOLSETS.append(
        McpToolset(
            connection_params=SseServerParams(
                url=_url,
                sse_read_timeout=3600,
            )
        )
    )

# STRUCTURE toolset
_url = "http://localhost:50004/sse"
if _is_sse_server_active(_url):
    MCP_TOOLSETS.append(
        McpToolset(
            connection_params=SseServerParams(
                url=_url,
                sse_read_timeout=3600,
            )
        )
    )

# ABACUS toolset
_url = "http://localhost:50003/sse"
if _is_sse_server_active(_url):
    MCP_TOOLSETS.append(
        McpToolset(
            connection_params=SseServerParams(
                url=_url,
                sse_read_timeout=3600,
            )
        )
    )

# VASP toolset
_url = "http://localhost:50005/sse"
if _is_sse_server_active(_url):
    MCP_TOOLSETS.append(
        McpToolset(
            connection_params=SseServerParams(
                url=_url,
                sse_read_timeout=7200,
            ),
            tool_filter=[
                "vasp_relaxation_tool",
                "vasp_scf_tool",
                "vasp_scf_results_tool",
                "vasp_nscf_kpath_tool",
                "vasp_nscf_uniform_tool",
            ]
        )
    )

# MatterGen toolset
_url = "http://localhost:50006/sse"
if _is_sse_server_active(_url):
    MCP_TOOLSETS.append(
        McpToolset(
            connection_params=SseServerParams(
                url=_url,
                sse_read_timeout=7200,
            )
        )
    )