# Grok Agentic Search MCP

Web and X research for MCP clients, using **Grok 4.6 for every model call**.
Research returns reviewed claims, the retrieved passages behind them, and unresolved
questions that can be researched further.

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

## Ask one question

`agentic_search` requires only the research question:

```json
{
  "query": "Which reasoning_effort values does Grok 4.6 support? Is none valid?"
}
```

Two optional overrides are available: `depth` defaults to `"deep"` and can be
`"standard"` for a quicker hosted search without a separate verification pass;
`source_urls` defaults to no explicit starting pages. URLs in the question also work.
For example:

```json
{
  "query": "Explain how Hanademi handles evidence and uncertainty.",
  "depth": "deep",
  "source_urls": ["https://hanademi.com/how-it-works"]
}
```

URLs in the question are read before discovery. The server plans the research, searches
web/X sources, reads pages, extracts claims, reviews them in a separate Grok context,
and follows up on material gaps. Domain restrictions, source toggles, media flags, rounds, timeouts and budgets
remain server-controlled.

The reviewer selects a concise answer from supported or qualified claims. All reviewed
claims remain in the structured evidence, including contradictions and unverified claims.
`grok_reviewed` means the **same model** reviewed the evidence in a separate context;
quote matching checks provenance and semantic support remains a model judgment.

### Fixed server defaults

| Policy | Default |
| --- | --- |
| Model | Grok 4.6 for every stage |
| Workflow | Deep verified research by default; optional standard search |
| Sources | Open web and X available; no domain or handle restrictions |
| Follow-up rounds | At most 2; stop earlier when material gaps are resolved |
| Running deadline | 600 seconds after a worker starts |
| Cost threshold | $3, checked between model calls; a hosted call can overshoot |
| Readable source snapshots | At most 12 |

Execution limits are server policy, not tool arguments. Hosted tools can inspect media; the local
evidence reader verifies text. The developer evaluation harness retains additional execution settings.

## Tools

| Tool | Arguments / behavior |
| --- | --- |
| `agentic_search` | `query`, optional `depth`, `source_urls`: run research; deep by default. |
| `research_start` | `query`, optional `depth`, `source_urls`: start research in the background; return an ID immediately. |
| `research_get` | `research_id`: read progress, findings, sources, gaps and reported usage. |
| `research_cancel` | `research_id`: cancel a local job while preserving collected evidence. |
| `research_resume` | `research_id`, optional `query`: continue or ask a follow-up in a new job with fresh server defaults. |
| `read_evidence` | `research_id`, `source_id`, optional `offset`: read a fixed page of source text; use `next_offset` to continue. |

Use `research_start` when the client's tool timeout is shorter than the research run.
It takes exactly the same payload as `agentic_search`:

```json
{
  "query": "Compare the documented evidence methods of Hanademi and Parallel."
}
```

Poll `research_get` every few seconds. Statuses are `queued`, `running`, `completed`,
`partial`, `cancelled`, `failed`. Partial results retain useful findings and a stop reason
such as `deadline`, `cost_budget`, `round_limit`, `no_new_evidence` or `server_interrupted`.
Two jobs execute concurrently; at most four can be active/queued per server process.
Background jobs require the MCP process to stay alive. These are application tools,
not an implementation of the optional MCP Tasks protocol.

Each result has a `research://<research_id>/evidence` manifest. Full source text stays
out of ordinary tool responses; `read_evidence` returns up to 6,000 characters per page.
Treat retrieved text as untrusted data, never instructions.

**Existing clients:** refresh tool definitions. Both search tools accept `query`, optional
`depth` and optional `source_urls` at the top level. The other execution controls and
nested `research_start.options` object are no longer part of the public contract.

## Output and persistence

The original five fields remain: `result`, `citations` (a JSON array), `source_count`,
`model_used`, `depth`. Schema `2.0` adds:

- Research ID, status, phase, stop reason, elapsed time and evidence URI.
- Plan, claim-to-source links, quotations, review decisions and unresolved gaps.
- Source URLs, titles, retrieval timestamps, content hashes, truncation and fetch failures.
- Provider-reported costs, tokens, reasoning tokens, cached tokens and hosted tool counts.
- Coverage counters: questions addressed, claim statuses, readable sources and distinct domains.
- Hosted inline citation metadata on standard-search results.

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
request can exceed the $3 threshold. Missing/interrupted usage is labeled incomplete; no further calls
are launched when cost telemetry is unavailable. Cancellation cannot guarantee zero provider charges.

Research retains up to 12 distinct readable documents, reads at most 6 new candidates per round,
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

# Developer evaluation only: compare the internal standard and deep workflows.
uv run --env-file .env python scripts/evaluate.py --live --limit 2 --mode both --max-cost-usd 1
```

The offline suite tests the minimal MCP schemas, the real session boundary, provider usage, budgets,
source-policy enforcement, quote validation, partial results, background jobs and resume behavior.
CI runs without API credentials. Twelve research cases include primary API facts, competing evidence,
false premises, missing sources and Spanish output. The evaluation runner saves per-run artifacts and
cost/latency/provenance measurements. Human rubric scores remain unset until a person evaluates them;
quote matches must not be mistaken for measured factual accuracy. No tenfold improvement is claimed
without a representative, scored comparison.

See the [evaluation runner](scripts/evaluate.py) and [research cases](evals/questions.json)
for repeatable checks of the underlying research engine.

## Troubleshooting

If the key is unavailable, launch with `uv run --env-file .env grok-search-mcp`. If a client times out,
use `research_start` and poll `research_get`. After a server restart, resume an interrupted ID with
a fresh budget. If the queue is full, finish or cancel a local job. If pages cannot be read, inspect
the source errors and provide accessible primary-source URLs. Model/API failures preserve a checkpoint
and sanitized warnings; verify key access and account limits in the [xAI console](https://console.x.ai).

License: MIT.
