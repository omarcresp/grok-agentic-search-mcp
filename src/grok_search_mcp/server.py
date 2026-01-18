"""Agentic Search MCP Server.

Exposes agentic search capabilities (web + social media) via MCP.
Single tool with depth parameter following 2026 context engineering best practices.

Implementation: xAI Grok (swappable)
"""

import logging
import os
from dataclasses import dataclass, asdict
from typing import Literal

from mcp.server.fastmcp import FastMCP
from xai_sdk import Client
from xai_sdk.chat import user
from xai_sdk.tools import web_search, x_search

# Configure logging to stderr (required for MCP - stdout is JSON-RPC)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("agentic-search-mcp")

mcp = FastMCP("Agentic Search")


# Structured output types
@dataclass
class SearchResult:
    """Structured search result with metadata."""

    result: str
    citations: list[str]
    source_count: int
    model_used: str
    depth: str


def _get_client(timeout: int = 120) -> Client:
    """Get xAI client with API key from environment."""
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        logger.error("XAI_API_KEY environment variable not set")
        raise ValueError("XAI_API_KEY environment variable not set")
    client = Client(api_key=api_key)
    client.timeout = timeout
    return client


def _format_result(response, model: str, depth: str) -> dict:
    """Format response into structured output."""
    citations = response.citations or []
    result = SearchResult(
        result=response.content or "",
        citations=citations,
        source_count=len(citations),
        model_used=model,
        depth=depth,
    )
    return asdict(result)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "openWorldHint": True,
    }
)
def agentic_search(
    query: str,
    depth: Literal["standard", "deep"] = "standard",
) -> dict:
    """Perform a deep, reasoned search across the web and social media.

    Iteratively analyzes results and makes follow-up queries to find
    comprehensive, up-to-date information with citations.

    Args:
        query: The search query or question to research.
        depth: Search depth - "standard" (fast, default) or "deep" (thorough reasoning).
               Use "deep" for complex multi-faceted research, academic questions,
               or when standard results are insufficient.

    Returns:
        Structured dict with result, citations, source_count, model_used, depth.

    Examples:
        - query="Latest news on AI regulation", depth="standard"
          → Fast lookup of recent news articles and social posts
        - query="Community sentiment on Rust vs Go for CLI tools", depth="standard"
          → Quick sentiment analysis from social discussions
        - query="Compare transformer architectures evolution and future directions", depth="deep"
          → Thorough multi-source academic research with reasoning
    """
    if depth == "deep":
        model = "grok-4-1-fast-reasoning"
        reasoning_effort = "high"
        timeout = 600
    else:
        model = "grok-4-1-fast-non-reasoning"
        reasoning_effort = None
        timeout = 120

    logger.info(f"Starting {depth} search for: {query[:100]}...")

    try:
        client = _get_client(timeout=timeout)

        create_kwargs = {
            "model": model,
            "tools": [
                web_search(enable_image_understanding=True),
                x_search(
                    enable_image_understanding=True,
                    enable_video_understanding=True,
                ),
            ],
            "include": ["inline_citations"],
        }
        if reasoning_effort:
            create_kwargs["reasoning_effort"] = reasoning_effort

        chat = client.chat.create(**create_kwargs)
        chat.append(user(query))
        response = chat.sample()

        result = _format_result(response, model, depth)

        # Log reasoning token usage if available
        if (
            depth == "deep"
            and hasattr(response, "usage")
            and hasattr(response.usage, "reasoning_tokens")
        ):
            logger.info(
                f"Search completed ({depth}). Citations: {result['source_count']}, "
                f"Reasoning tokens: {response.usage.reasoning_tokens}"
            )
        else:
            logger.info(f"Search completed ({depth}). Found {result['source_count']} citations")

        return result

    except Exception as e:
        logger.exception(f"Error during {depth} search: {e}")
        raise RuntimeError(f"Search failed: {e}") from e


def main():
    """Run the MCP server."""
    logger.info("Starting Agentic Search MCP server")
    mcp.run()


if __name__ == "__main__":
    main()
