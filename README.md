# Grok Agentic Search MCP

Web and X research for MCP clients, using **Grok 4.6 for every model call**.
Quick searches return cited answers. Deep research returns reviewed claims, the
retrieved passages behind them, and unresolved questions that can be researched further.

## Start locally

Requires Python 3.10+, [uv](https://docs.astral.sh/uv/), and an xAI key with Grok 4.6 access.

```bash
git clone https://github.com/omarcresp/grok-agentic-search-mcp.git
cd grok-agentic-search-mcp
uv sync --locked
# Create .env from env.example if you do not already have one, then add your key.
uv run --env-file .env grok-search-mcp
```

`.env` is ignored by Git. The server reads `XAI_API_KEY` from its environment;
`uv --env-file` loads the file explicitly. Keep keys out of prompts and committed client configs.
The server uses stdio: stdout is reserved for MCP messages, and logs go to stderr.

For clients accepting an `mcpServers` configuration:

```json
{
  "mcpServers": {
    "grok-search": {
      "command": "uv",
      "args": [
        "run", "--directory", "/absolute/path/to/grok-agentic-search-mcp",
        "--env-file", "/absolute/path/to/grok-agentic-search-mcp/.env",
        "grok-search-mcp"
      ]
    }
  }
}
```

Restart the MCP client after upgrading. No other model provider or search-service key is needed.

## Choose a mode

| Mode | Workflow | Default deadline | Default cost threshold |
| --- | --- | --- | --- |
| `standard` | One Grok 4.6 hosted web/X search request, low reasoning, inline citations | 120 seconds | $0.50 |
| `deep` | Plan → discover → read pages → extract claims → separate Grok review → search gaps | 600 seconds | $3.00 |

Deep mode reads supplied URLs first, keeps source snapshots, matches quotes against the actual
retrieved text, and reports each claim as `supported`, `qualified`, `contradicted`, or `unverified`.
The reviewer selects a concise subset of supported/qualified claims for the answer;
all reviewed claims remain in the structured evidence. Contradictions and gaps stay visible.
Unverified claims remain available in the structured output and are excluded from answer citations.
All stages use `grok-4.6`: low reasoning for planning and standard search, high for deep research.

`grok_reviewed` means a separate context of the **same model** reviewed the evidence. It is not
independent human verification or a guarantee of factual accuracy. Quote matching checks textual
provenance; semantic support is a model judgment. Standard mode reports `not_requested`.

## Tools

### `agentic_search`

The original tool and its original parameters remain available. Example tool arguments:

```json
{
  "query": "Which reasoning_effort values does Grok 4.6 support? Is none valid?",
  "depth": "deep",
  "source_urls": ["https://docs.x.ai/developers/models/grok-4.6"],
  "allowed_domains": ["docs.x.ai"],
  "include_x": false,
  "max_cost_usd": 1,
  "max_rounds": 2
}
```

| Argument | Default / limits |
| --- | --- |
| `query` | Required, nonblank, up to 20,000 characters |
| `depth` | `standard` or `deep` |
| `allowed_domains`, `excluded_domains` | Up to 5 hostnames; mutually exclusive; no URLs/wildcards |
| `allowed_x_handles`, `excluded_x_handles` | Up to 20 handles; mutually exclusive; `@` optional |
| `from_date`, `to_date` | ISO8601; apply to **X Search only**; naive dates mean UTC |
| `include_x` | `true`; set `false` for web-only research |
| `enable_image_understanding` | `true`; hosted web/X tool option |
| `enable_video_understanding` | `true`; hosted X tool option |
| `source_urls` | Up to 12 URLs; deep mode fetches these before discovery |
| `max_cost_usd` | Mode default above; positive, at most $50; **between-call threshold** |
| `timeout_seconds` | Mode default above; 10–1800 seconds after a worker starts |
| `max_rounds` | 2; range 1–4; each round discovers, reads, extracts and reviews |

The reader applies domain/handle filters again at every redirect. Web domain filters and X handle
filters are separate scopes, as in the hosted API. Disable X to restrict the whole run to web domains.
X dates cannot constrain the open web or independently establish a directly fetched post's date.
The hosted tools can inspect media; the local evidence reader verifies **text**, not image/video content.

### Background research

Use background tools when a client has a short tool timeout. Call `research_start`:

```json
{
  "options": {
    "query": "Compare the documented evidence methods of Hanademi and Parallel.",
    "depth": "deep",
    "include_x": false,
    "source_urls": ["https://hanademi.com/how-it-works"],
    "max_cost_usd": 3,
    "timeout_seconds": 600
  }
}
```

| Tool | Arguments / behavior |
| --- | --- |
| `research_start` | `options`: full request object. Returns an ID immediately. Its option defaults are 600 seconds/$3; set `depth: "deep"` explicitly. |
| `research_get` | `research_id`: checkpoint with phase, usage, sources, claims and gaps. Poll every few seconds. |
| `research_cancel` | `research_id`: cancel a job owned by this server; preserve collected evidence. |
| `research_resume` | `research_id`, optional `query`, `max_cost_usd`, `timeout_seconds`, `max_rounds`: start a **new** deep run with fresh budgets and the same source filters. |
| `read_evidence` | `research_id`, `source_id`, optional `offset` (0), `limit` (6000, max 12000): page through a saved source without another model call. |

Statuses are `queued`, `running`, `completed`, `partial`, `cancelled`, `failed`.
Partial results include a stop reason such as `deadline`, `cost_budget`, `round_limit`,
`no_new_evidence`, or `server_interrupted`. They can contain useful reviewed findings.
Two jobs execute concurrently; at most four can be active/queued per server process.
Background jobs require the MCP server process to stay alive. They are application tools,
not an implementation of the optional MCP Tasks protocol.

Each result has a `research://<research_id>/evidence` resource containing its evidence manifest.
Full text is deliberately kept out of ordinary tool responses; load it with `read_evidence`.
Treat all retrieved text as untrusted data, never instructions.

## Output and persistence

The original five fields remain: `result`, `citations` (a JSON array), `source_count`,
`model_used`, `depth`. Schema `2.0` adds:

- Research ID, status, phase, stop reason, elapsed time and evidence URI.
- Plan, claim-to-source links, quotations, review decisions and unresolved gaps.
- Source URLs, titles, retrieval timestamps, content hashes, truncation and fetch failures.
- Provider-reported costs, tokens, reasoning tokens, cached tokens and hosted tool counts.
- Coverage counters: questions addressed, claim statuses, readable sources and distinct domains.
- Hosted inline citation metadata for standard searches.

Coverage counters describe this run; they are not calibrated accuracy or independent-source scores.
Gaps and review reasons are model judgments, not separately verified claims.

Checkpoints are atomic local JSON files with owner-only file permissions, stored in
`~/.cache/grok-search-mcp` or `GROK_SEARCH_DATA_DIR`. They contain queries, findings and source text.
Inactive records expire after seven days; cleanup happens at server startup, job creation and
expired-record access. Resume reuses source snapshots under 24 hours old, re-fetches older sources,
then replans and reviews. It never treats a prior model answer as source evidence.
This is a local, single-user service; the store is not an authenticated multi-tenant database.

## Limits and cost

Each hosted search request allows at most 6 agentic turns. Parallel tool calls mean that a turn is
**not** one search. The server checks reported cost before the next model call, so the final hosted
request can exceed `max_cost_usd`. Missing/interrupted usage is labeled incomplete; no further calls
are launched when cost telemetry is unavailable. Cancellation cannot guarantee zero provider charges.

Deep mode retains up to 12 distinct readable documents, reads at most 6 new candidates per round,
and deduplicates exact normalized content. The reader supports HTML, plain text, Markdown, JSON and
text-based PDF. Limits: 2 MiB decoded response, 18,000 extracted characters, 20 PDF pages, 25 seconds
per fetch including redirects/parsing, four concurrent reads. Parsing runs in a disposable
process with a five-second wall deadline and platform-supported CPU/memory limits.
No browser rendering, login, paywall
bypass or OCR. A blocked, truncated or unreadable page is not proof that a fact is absent.

Public-IP validation covers literal addresses, actual DNS connection results and each redirect.
HTTP(S) ports 80/443 only; no cookies, ambient proxy credentials or arbitrary local-file reads.
The application does not execute instructions found in retrieved pages.

## Development and evaluation

```bash
uv sync --locked --group dev
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run pytest -q
uv build

# Free: inspect selected questions and human scoring criteria.
uv run python scripts/evaluate.py --limit 2

# Billable: compare standard and deep, using Grok 4.6 for both.
uv run --env-file .env python scripts/evaluate.py --live --limit 2 --mode both --max-cost-usd 1
```

The offline suite tests the real MCP session boundary, provider serialization, budgets,
source-policy enforcement, quote validation, partial results, background jobs and resume behavior.
CI runs without API credentials. Twelve research cases include primary API facts, competing evidence,
false premises, missing sources and Spanish output. The evaluation runner saves per-run artifacts and
cost/latency/provenance measurements. Human rubric scores remain unset until a person evaluates them;
quote matches must not be mistaken for measured factual accuracy. No tenfold improvement is claimed
without a representative, scored comparison.

See [architecture and tradeoffs](docs/architecture.md), [validation](docs/validation/README.md),
and the [original research proposal](docs/research-mcp-upgrade-proposal-2026-09.md).

## Troubleshooting

If the key is unavailable, launch with `uv run --env-file .env grok-search-mcp`. If a client times out,
use `research_start` and poll `research_get`. After a server restart, resume an interrupted ID with
a fresh budget. If the queue is full, finish or cancel a local job. If pages cannot be read, inspect
the source errors and provide accessible primary-source URLs. Model/API failures preserve a checkpoint
and sanitized warnings; verify key access and account limits in the [xAI console](https://console.x.ai).

License: MIT.
