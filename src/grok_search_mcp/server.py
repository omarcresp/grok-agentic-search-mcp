"""Agentic Search MCP Server.

Exposes agentic search capabilities (web + social media) via MCP.
Single tool with depth parameter following 2026 context engineering best practices.

Implementation: xAI Grok (swappable)
"""

import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Literal

from mcp.server.fastmcp import FastMCP
from xai_sdk import Client
from xai_sdk.chat import user
from xai_sdk.tools import web_search, x_search

MODEL = "grok-4.3"
DEPTH_CONFIG = {
    "standard": {
        "reasoning_effort": "none",
        "timeout": 120,
    },
    "deep": {
        "reasoning_effort": "high",
        "timeout": 600,
    },
}

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


def _validate_filter_pair(
    allowed: list[str] | None,
    excluded: list[str] | None,
    *,
    name: str,
    limit: int,
) -> None:
    """Validate xAI server-side search include/exclude filters."""
    if allowed and excluded:
        raise ValueError(f"allowed_{name} cannot be used with excluded_{name}")
    if allowed and len(allowed) > limit:
        raise ValueError(f"allowed_{name} supports at most {limit} entries")
    if excluded and len(excluded) > limit:
        raise ValueError(f"excluded_{name} supports at most {limit} entries")


def _parse_iso_date(value: str | None, *, name: str) -> datetime | None:
    """Parse an ISO8601 date for xAI SDK X Search filters."""
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO8601 date, for example 2026-05-25") from exc


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "openWorldHint": True,
    }
)
def agentic_search(
    query: str,
    depth: Literal["standard", "deep"] = "standard",
    allowed_domains: list[str] | None = None,
    excluded_domains: list[str] | None = None,
    allowed_x_handles: list[str] | None = None,
    excluded_x_handles: list[str] | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    enable_image_understanding: bool = True,
    enable_video_understanding: bool = True,
) -> dict:
    """Perform a deep, reasoned search across the web and social media.

    Iteratively analyzes results and makes follow-up queries to find
    comprehensive, up-to-date information with citations.

    Args:
        query: The search query or question to research.
        depth: Search depth - "standard" (fast, default) or "deep" (thorough reasoning).
               Use "deep" for complex multi-faceted research, academic questions,
               or when standard results are insufficient.
        allowed_domains: Only search these web domains (max 5). Cannot be combined
                         with excluded_domains.
        excluded_domains: Exclude these web domains (max 5). Cannot be combined
                          with allowed_domains.
        allowed_x_handles: Only consider posts from these X handles (max 20).
                           Cannot be combined with excluded_x_handles.
        excluded_x_handles: Exclude posts from these X handles (max 20). Cannot be
                            combined with allowed_x_handles.
        from_date: Start date for X Search results in ISO8601 format, e.g. 2026-05-25.
        to_date: End date for X Search results in ISO8601 format, e.g. 2026-05-25.
        enable_image_understanding: Analyze images found during Web Search and X Search.
        enable_video_understanding: Analyze videos found during X Search.

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
    _validate_filter_pair(
        allowed_domains,
        excluded_domains,
        name="domains",
        limit=5,
    )
    _validate_filter_pair(
        allowed_x_handles,
        excluded_x_handles,
        name="x_handles",
        limit=20,
    )

    config = DEPTH_CONFIG[depth]
    reasoning_effort = config["reasoning_effort"]
    timeout = config["timeout"]
    parsed_from_date = _parse_iso_date(from_date, name="from_date")
    parsed_to_date = _parse_iso_date(to_date, name="to_date")

    logger.info(f"Starting {depth} search for: {query[:100]}...")

    try:
        client = _get_client(timeout=timeout)

        create_kwargs = {
            "model": MODEL,
            "reasoning_effort": reasoning_effort,
            "tools": [
                web_search(
                    allowed_domains=allowed_domains,
                    excluded_domains=excluded_domains,
                    enable_image_understanding=enable_image_understanding,
                ),
                x_search(
                    from_date=parsed_from_date,
                    to_date=parsed_to_date,
                    allowed_x_handles=allowed_x_handles,
                    excluded_x_handles=excluded_x_handles,
                    enable_image_understanding=enable_image_understanding,
                    enable_video_understanding=enable_video_understanding,
                ),
            ],
            "include": ["inline_citations"],
        }

        chat = client.chat.create(**create_kwargs)
        chat.append(user(query))
        response = chat.sample()

        result = _format_result(response, MODEL, depth)

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
