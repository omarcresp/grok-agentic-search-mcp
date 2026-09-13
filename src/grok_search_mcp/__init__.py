"""Grok Agentic Search MCP Server.

Exposes Grok's agentic search capabilities (web + X) to AI agents via MCP.
"""

__all__ = ["agentic_search", "main", "mcp"]


def __getattr__(name):
    """Preserve public exports without initializing the server on every submodule import."""
    if name in __all__:
        from importlib import import_module

        return getattr(import_module("grok_search_mcp.server"), name)
    raise AttributeError(name)
