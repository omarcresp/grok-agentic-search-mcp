"""Grok Agentic Search MCP Server.

Exposes Grok's agentic search capabilities (web + X) to AI agents via MCP.
"""

from grok_search_mcp.server import agentic_search, main, mcp

__all__ = ["agentic_search", "main", "mcp"]
