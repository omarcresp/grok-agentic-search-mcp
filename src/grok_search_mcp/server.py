"""Grok Agentic Search MCP Server.

Exposes Grok's agentic search capabilities (web + X) via MCP.
"""

import os

from mcp.server.fastmcp import FastMCP
from xai_sdk import Client
from xai_sdk.chat import user
from xai_sdk.tools import web_search, x_search

mcp = FastMCP("Grok Agentic Search")


@mcp.tool()
def agentic_search(query: str) -> str:
    """Perform a deep, reasoned search using Grok's agentic capabilities.

    Searches both the web and X (Twitter) using Grok's grok-4-1-fast model,
    which iteratively analyzes results and makes follow-up queries to find
    comprehensive information.

    Args:
        query: The search query or question to research.

    Returns:
        Search results with citations.
    """
    api_key = os.getenv("XAI_API_KEY")
    if not api_key:
        return "Error: XAI_API_KEY environment variable not set"

    client = Client(api_key=api_key)
    chat = client.chat.create(
        model="grok-4-1-fast",
        tools=[
            web_search(enable_image_understanding=True),
            x_search(
                enable_image_understanding=True,
                enable_video_understanding=True,
            ),
        ],
    )

    chat.append(user(query))
    response = chat.sample()

    # Format output: result + citations
    result = response.content or ""

    if response.citations:
        citations = "\n".join(f"- {url}" for url in response.citations)
        result += f"\n\n---\nCitations:\n{citations}"

    return result


def main():
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
