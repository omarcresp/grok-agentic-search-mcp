# Grok Agentic Search MCP Server

An MCP server that exposes Grok's agentic search capabilities to AI agents like Claude. Uses `grok-4-1-fast` to perform deep, reasoned searches across the web and X (Twitter).

## Features

- **Agentic search**: Grok iteratively analyzes results and makes follow-up queries to find comprehensive information
- **Web + X search**: Searches both the web and X posts
- **Image & video understanding**: Analyzes visual content found during search
- **Citations**: Returns source URLs for all information

## Requirements

- [uv](https://docs.astral.sh/uv/)
- xAI API key (get one at [x.ai](https://x.ai))

## Usage with Claude Code

Add to your Claude Code MCP settings (`~/.claude/claude_desktop_config.json` or project `.claude/settings.local.json`):

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

Replace `/path/to/grok-agentic-search-mcp` with the actual path to this repo.

## Usage with Claude Desktop

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

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
```
Search results synthesized by Grok...

---
Citations:
- https://example.com/source1
- https://x.com/user/status/123
```

## Example Queries

- "What are the best practices for using React Server Components in 2026?"
- "What is the community consensus on Rust vs Go for CLI tools?"
- "Latest updates on the Model Context Protocol"

## License

MIT
