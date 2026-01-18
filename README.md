# Agentic Search MCP Server

An MCP server that provides agentic search capabilities to AI agents. Performs deep, reasoned searches across the web and social media with iterative refinement.

## Features

- **Agentic search**: Iteratively analyzes results and makes follow-up queries
- **Web + social media**: Searches both the web and social posts
- **Image & video understanding**: Analyzes visual content found during search
- **Inline citations**: Returns source URLs embedded in results
- **Depth control**: Standard (fast) or deep (thorough reasoning) modes

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- xAI API key (get one at [console.x.ai](https://console.x.ai))

> **Note**: Currently uses xAI Grok as the underlying model. Implementation is swappable.

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

Perform a deep, reasoned search across the web and social media.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | required | The search query or question to research |
| `depth` | `"standard"` \| `"deep"` | `"standard"` | Search depth. Use `"deep"` for complex research |

**Depth modes:**
- `standard`: Fast search (~2 min timeout)
- `deep`: Thorough research with extended reasoning (~10 min timeout)

**Output:**
```json
{
  "result": "Synthesized answer with inline citations",
  "citations": ["https://source1.com", "https://source2.com"],
  "source_count": 5,
  "depth": "standard"
}
```

## Examples

**Standard depth (fast, everyday use):**
```json
{"query": "Latest news on AI regulation"}
{"query": "Community sentiment on Rust vs Go for CLI tools"}
{"query": "Recent mass layoffs in tech industry"}
```

**Deep depth (complex analysis):**
```json
{"query": "Compare transformer architectures evolution and future directions", "depth": "deep"}
{"query": "Security implications of MCP servers across implementations", "depth": "deep"}
{"query": "Analyze tradeoffs of major AI agent frameworks for production", "depth": "deep"}
```

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
