# Grok Agentic Search MCP

**Deep, reasoned web search for AI agents** — iteratively analyzes results, searches social media, and returns comprehensive answers with citations.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

---

## Why Use This?

Most search tools return links. This MCP server returns *answers* — synthesized from multiple sources with inline citations. It iteratively refines queries, analyzes images and videos found during search, and pulls from both web and social media.

**Perfect for:**
- Research tasks requiring current information
- Questions needing multiple source synthesis
- Social media sentiment analysis
- Complex queries that benefit from reasoning

---

## Prerequisites

**[uv](https://docs.astral.sh/uv/)** is required to run this server.

```bash
# Install uv (if you don't have it)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**xAI API Key** — Get one at [console.x.ai](https://console.x.ai)

---

## Quick Start

**1. Clone the repository**

```bash
git clone https://github.com/yourusername/grok-agentic-search-mcp.git
cd grok-agentic-search-mcp
uv sync
```

**2. Add to your AI client** (see configurations below)

**3. Set your API key** in the config and restart your client

---

## Client Configuration

<details open>
<summary><strong>Claude Code</strong></summary>

Add to `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "grok-search": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/grok-agentic-search-mcp", "grok-search-mcp"],
      "env": {
        "XAI_API_KEY": "your-api-key"
      }
    }
  }
}
```

Or via CLI:

```bash
claude mcp add grok-search -- uv run --directory /path/to/grok-agentic-search-mcp grok-search-mcp
```

</details>

<details>
<summary><strong>Claude Desktop</strong></summary>

Add to your config file:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "grok-search": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/grok-agentic-search-mcp", "grok-search-mcp"],
      "env": {
        "XAI_API_KEY": "your-api-key"
      }
    }
  }
}
```

**Restart Claude Desktop completely** after saving.

</details>

<details>
<summary><strong>Cursor</strong></summary>

Add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "grok-search": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/grok-agentic-search-mcp", "grok-search-mcp"],
      "env": {
        "XAI_API_KEY": "your-api-key"
      }
    }
  }
}
```

Restart Cursor after saving.

</details>

<details>
<summary><strong>OpenCode</strong></summary>

Add to your `opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "grok-search": {
      "type": "local",
      "command": ["uv", "run", "--directory", "/absolute/path/to/grok-agentic-search-mcp", "grok-search-mcp"],
      "enabled": true,
      "environment": {
        "XAI_API_KEY": "your-api-key"
      }
    }
  }
}
```

</details>

> **Note**: Replace `/absolute/path/to/grok-agentic-search-mcp` with the actual path where you cloned this repo.

---

## Usage

### `agentic_search`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | *required* | The search query or question |
| `depth` | `"standard"` \| `"deep"` | `"standard"` | Search thoroughness |

### Depth Modes

| Mode | Use Case | Timeout |
|------|----------|---------|
| `standard` | Quick lookups, recent news, simple questions | ~2 min |
| `deep` | Complex research, multi-faceted analysis, academic questions | ~10 min |

### Example Queries

**Standard depth** — fast, everyday use:
```
"Latest developments in AI regulation"
"What's the mass tech layoffs happening right now?"
"Community sentiment on Bun vs Node.js"
```

**Deep depth** — thorough research:
```
{"query": "Compare major AI agent frameworks for production use", "depth": "deep"}
{"query": "Security implications of MCP protocol across implementations", "depth": "deep"}
{"query": "Evolution of transformer architectures and future directions", "depth": "deep"}
```

### Response Format

```json
{
  "result": "Synthesized answer with [inline citations](https://source.com)...",
  "citations": ["https://source1.com", "https://source2.com"],
  "source_count": 12,
  "depth": "standard"
}
```

---

## Development

```bash
# Run the server directly
uv run grok-search-mcp

# Test with MCP Inspector
npx @modelcontextprotocol/inspector uv run grok-search-mcp
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Server not appearing | Completely restart your client after config changes |
| API errors | Verify your key at [console.x.ai](https://console.x.ai) |
| uv not found | Run the install script in Prerequisites |
| Timeout on deep searches | Deep mode can take up to 10 minutes — this is expected |

**Logs location** (Claude Desktop):
- macOS: `~/Library/Logs/Claude/mcp*.log`
- Windows: `%APPDATA%\Claude\logs\`

---

## License

MIT
