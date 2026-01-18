# Grok Agentic Search MCP Server

An MCP server that exposes Grok's agentic search capabilities to AI agents like Claude. Uses `grok-4-1-fast` to perform deep, reasoned searches across the web and X (Twitter).

## Features

- **Agentic search**: Grok iteratively analyzes results and makes follow-up queries to find comprehensive information
- **Web + X search**: Searches both the web and X posts
- **Image & video understanding**: Analyzes visual content found during search
- **Inline citations**: Returns source URLs embedded in results with full citation list

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- xAI API key (get one at [console.x.ai](https://console.x.ai))

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/grok-agentic-search-mcp.git
cd grok-agentic-search-mcp

# Install dependencies with uv
uv sync
```

## Usage with Claude Code

Add to your project's `.mcp.json` file in the project root:

```json
{
  "mcpServers": {
    "grok-search": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/grok-agentic-search-mcp",
        "grok-search-mcp"
      ],
      "env": {
        "XAI_API_KEY": "your_xai_api_key"
      }
    }
  }
}
```

Or add via CLI:

```bash
claude mcp add grok-search --scope project -- uv run --directory /path/to/grok-agentic-search-mcp grok-search-mcp
```

Replace `/path/to/grok-agentic-search-mcp` with the actual path to this repo.

## Usage with Claude Desktop

Add to your Claude Desktop config:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "grok-search": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/grok-agentic-search-mcp",
        "grok-search-mcp"
      ],
      "env": {
        "XAI_API_KEY": "your_xai_api_key"
      }
    }
  }
}
```

After saving, **quit and restart** Claude Desktop completely (not just close the window).

## Tool

### `agentic_search`

Perform a deep, reasoned search using Grok's agentic capabilities.

**Input:**
```json
{
  "query": "string - The search query or question to research"
}
```

**Output:**
Search results synthesized by Grok with inline citation links and a full citations list at the end.

## Example Queries

- "What are the latest developments in MCP (Model Context Protocol)?"
- "What is the community sentiment on X about Rust vs Go for CLI tools?"
- "Recent news about xAI and Grok models"

## Development

```bash
# Run the server locally for testing
uv run grok-search-mcp

# Test with MCP Inspector
npx @modelcontextprotocol/inspector uv run grok-search-mcp
```

## Troubleshooting

- **Server not appearing**: Ensure you completely restart Claude Desktop/Code after config changes
- **API errors**: Verify your `XAI_API_KEY` is valid at [console.x.ai](https://console.x.ai)
- **Logs**: Check `~/Library/Logs/Claude/mcp*.log` (macOS) for Desktop issues

## License

MIT
