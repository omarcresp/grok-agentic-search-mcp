import asyncio
import json
from datetime import datetime, timedelta, timezone
from functools import partial

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from test_research import Backend, Reader, script

from grok_search_mcp import server
from grok_search_mcp.jobs import ResearchJobs
from grok_search_mcp.models import SearchOptions
from grok_search_mcp.provider import Completion
from grok_search_mcp.research import ResearchRunner, reusable_sources


def jobs_with_fixtures(store, source):
    return ResearchJobs(
        store,
        runner_factory=partial(
            ResearchRunner,
            backend_factory=lambda o, u: Backend(o, u, script()),
            reader_factory=lambda _: Reader(source),
        ),
    )


async def test_background_persist_resume_and_evidence(store, source):
    jobs = jobs_with_fixtures(store, source)
    job = jobs.start(
        SearchOptions(
            query="Which limits apply?",
            depth="deep",
            max_cost_usd=0.2,
            timeout_seconds=60,
            max_rounds=1,
            allowed_domains=["example.com"],
            include_x=False,
        )
    )
    await jobs.tasks[job.research_id]
    result = jobs.get(job.research_id)
    assert result.status == "completed"
    page = jobs.evidence(job.research_id, source.id, limit=20)
    assert page["text"] == source.text[:20] and page["next_offset"] == 20
    assert jobs.evidence(job.research_id, source.id, offset=20)["next_offset"] is None
    resumed = jobs.resume(job.research_id)
    saved = store.load(resumed.research_id)
    assert resumed.research_id != job.research_id
    assert saved.options.parent_research_id == job.research_id
    assert saved.options.max_cost_usd == 3 and saved.options.timeout_seconds == 600
    assert saved.options.max_rounds == 2
    assert saved.options.allowed_domains == [] and saved.options.include_x
    assert saved.output.sources[0].text == source.text and saved.output.usage.model_calls == 0
    await jobs.tasks[resumed.research_id]
    assert jobs.get(job.research_id).status == "completed"
    await jobs.close()


async def test_cancel_queued_and_running_and_queue_bound(store, source):
    entered = asyncio.Event()

    class WaitingRunner(ResearchRunner):
        async def execute(self):
            await self.phase("waiting")
            entered.set()
            await asyncio.Event().wait()

    jobs = ResearchJobs(store, runner_factory=WaitingRunner)
    active = jobs.start(SearchOptions(query="q"))
    await entered.wait()
    assert jobs.get(active.research_id).phase == "waiting"
    queued = [jobs.start(SearchOptions(query="q")) for _ in range(3)]
    with pytest.raises(ValueError, match="queue is full"):
        jobs.start(SearchOptions(query="q"))
    with pytest.raises(ValueError, match="still active"):
        jobs.resume(active.research_id)
    assert (await jobs.cancel(queued[-1].research_id)).status == "cancelled"
    assert (await jobs.cancel(active.research_id)).status == "cancelled"
    await jobs.close()
    assert not jobs.tasks


def test_restart_marks_interruption_and_snapshot_freshness(store, record, source):
    record.output.status = "running"
    record.owner_pid = 0
    record.output.sources = [source]
    store.save(record)
    jobs = ResearchJobs(store)
    result = jobs.get(record.output.research_id)
    assert result.status == "partial" and result.stop_reason == "server_interrupted"
    assert not result.usage.cost_complete
    assert reusable_sources(record, record.options)
    source.retrieved_at = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    assert not reusable_sources(record, record.options)


def test_store_path_permissions_and_retention(store, record):
    with pytest.raises(ValueError, match="Invalid research ID"):
        store.load("../../.env")
    store.save(record)
    path = store.path(record.output.research_id)
    assert path.stat().st_mode & 0o777 == 0o600
    assert not list(store.directory.glob("*.tmp"))
    data = json.loads(path.read_text())
    data["updated_at"] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    data["output"]["status"] = "completed"
    path.write_text(json.dumps(data))
    store.prune()
    assert not path.exists()


async def test_actual_mcp_schema_tools_resource_and_serialization(monkeypatch, store, source):
    monkeypatch.setattr(server, "_jobs", jobs_with_fixtures(store, source))
    async with create_connected_server_and_client_session(server.mcp) as session:
        definitions = {t.name: t for t in (await session.list_tools()).tools}
        assert len(definitions) == 6
        expected_inputs = {
            "agentic_search": {"query", "depth", "source_urls"},
            "research_start": {"query", "depth", "source_urls"},
            "research_get": {"research_id"},
            "research_cancel": {"research_id"},
            "research_resume": {"research_id", "query"},
            "read_evidence": {"research_id", "source_id", "offset"},
        }
        for name, expected in expected_inputs.items():
            assert set(definitions[name].inputSchema["properties"]) == expected
        for name in ("agentic_search", "research_start"):
            schema = definitions[name].inputSchema
            assert schema["required"] == ["query"]
            assert schema["properties"]["depth"]["default"] == "deep"
            assert schema["properties"]["source_urls"]["default"] is None
        assert (
            definitions["agentic_search"].outputSchema["properties"]["citations"]["type"] == "array"
        )
        result = await session.call_tool("agentic_search", {"query": "Which limits apply?"})
        assert not result.isError
        data = result.structuredContent
        assert data["status"] == "completed" and isinstance(data["citations"], list)
        options = store.load(data["research_id"]).options
        assert options.depth == "deep" and options.include_x
        assert options.max_rounds == 2 and options.max_cost_usd == 3
        assert options.timeout_seconds == 600
        assert options.allowed_domains == options.excluded_domains == []
        assert data["sources"][0]["text"] == ""
        assert json.loads(result.content[0].text)["citations"] == [source.url]
        manifest = await session.read_resource(data["evidence_uri"])
        assert json.loads(manifest.contents[0].text)["claims"][0]["status"] == "supported"
        evidence = await session.call_tool(
            "read_evidence", {"research_id": data["research_id"], "source_id": source.id}
        )
        assert evidence.structuredContent["text"] == source.text
        invalid = await session.call_tool("agentic_search", {"query": " "})
        assert invalid.isError


async def test_mcp_background_get_cancel_and_resume(monkeypatch, store, source):
    jobs = jobs_with_fixtures(store, source)
    monkeypatch.setattr(server, "_jobs", jobs)
    async with create_connected_server_and_client_session(server.mcp) as session:
        launched = await session.call_tool("research_start", {"query": "Which limits apply?"})
        research_id = launched.structuredContent["research_id"]
        assert store.load(research_id).options.depth == "deep"
        task = jobs.tasks.get(research_id)
        if task:
            await task
        fetched = await session.call_tool("research_get", {"research_id": research_id})
        assert fetched.structuredContent["status"] == "completed"
        resumed = await session.call_tool("research_resume", {"research_id": research_id})
        assert resumed.structuredContent["research_id"] != research_id
        cancelled = await session.call_tool(
            "research_cancel", {"research_id": resumed.structuredContent["research_id"]}
        )
        assert cancelled.structuredContent["status"] in ("completed", "cancelled")


async def test_mcp_shutdown_cancels_active_background_job(monkeypatch, store):
    entered = asyncio.Event()

    class WaitingRunner(ResearchRunner):
        async def execute(self):
            await self.phase("waiting")
            entered.set()
            await asyncio.Event().wait()

    jobs = ResearchJobs(store, runner_factory=WaitingRunner)
    monkeypatch.setattr(server, "_jobs", jobs)
    async with create_connected_server_and_client_session(server.mcp) as session:
        launched = await session.call_tool("research_start", {"query": "q"})
        research_id = launched.structuredContent["research_id"]
        await entered.wait()
    assert store.load(research_id).output.status == "cancelled"


async def test_search_tools_accept_depth_and_source_overrides(monkeypatch, store, source):
    jobs = ResearchJobs(
        store,
        runner_factory=partial(
            ResearchRunner, backend_factory=lambda o, u: Backend(o, u, [Completion("Quick answer")])
        ),
    )
    monkeypatch.setattr(server, "_jobs", jobs)
    async with create_connected_server_and_client_session(server.mcp) as session:
        for name in ("agentic_search", "research_start"):
            result = await session.call_tool(
                name,
                {"query": "Which limits apply?", "depth": "standard", "source_urls": [source.url]},
            )
            assert not result.isError
            research_id = result.structuredContent["research_id"]
            if task := jobs.tasks.get(research_id):
                await task
            record = store.load(research_id)
            assert record.options.depth == "standard"
            assert record.options.source_urls == [source.url]
            assert record.output.verification == "not_requested"
            assert record.options.max_rounds == 2 and record.options.max_cost_usd == 3
