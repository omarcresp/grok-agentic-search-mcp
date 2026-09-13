"""Local research jobs, with bounded concurrency and restart-safe evidence reuse."""

import asyncio
import os
from contextlib import suppress
from uuid import uuid4

from .models import JobInfo, RunRecord, SearchOptions, SearchResult
from .research import ResearchRunner, public_result, reusable_sources
from .store import ResearchStore, owner_alive


class ResearchJobs:
    def __init__(self, store: ResearchStore | None = None, *, runner_factory=ResearchRunner):
        self.store = store or ResearchStore()
        self.runner_factory = runner_factory
        self.tasks: dict[str, asyncio.Task] = {}
        self.slots = asyncio.Semaphore(2)
        self.store.prune()

    def create(self, options: SearchOptions, *, parent: RunRecord | None = None) -> RunRecord:
        if not os.getenv("XAI_API_KEY", "").strip():
            raise ValueError("Set XAI_API_KEY in the server environment before starting research")
        if len(self.tasks) >= 4:
            raise ValueError("Research queue is full (4 jobs); wait or cancel an existing job")
        self.store.prune()
        research_id = str(uuid4())
        output = SearchResult(
            depth=options.depth,
            research_id=research_id,
            evidence_uri=f"research://{research_id}/evidence",
        )
        if parent and options.depth == "deep":
            output.sources = reusable_sources(parent, options)
        record = RunRecord(options=options, output=output, owner_pid=os.getpid())
        self.store.save(record)
        return record

    async def execute(self, record: RunRecord, progress=None) -> SearchResult:
        try:
            async with self.slots:
                return await self.runner_factory(record, self.store, progress=progress).run()
        except asyncio.CancelledError:
            if record.output.status in ("queued", "running"):
                record.output.status, record.output.phase = "cancelled", "finished"
                record.output.stop_reason = "cancelled"
                self.store.save(record)
            raise

    def launch(self, record: RunRecord, progress=None) -> asyncio.Task:
        task = asyncio.create_task(self.execute(record, progress))
        research_id = record.output.research_id
        self.tasks[research_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(research_id, None))
        return task

    async def search(self, options: SearchOptions, progress=None) -> SearchResult:
        record = self.create(options)
        return public_result(await self.launch(record, progress))

    def start(self, options: SearchOptions, *, parent: RunRecord | None = None) -> JobInfo:
        record = self.create(options, parent=parent)
        self.launch(record)
        return self.info(record.output)

    @staticmethod
    def info(output: SearchResult) -> JobInfo:
        return JobInfo(
            **output.model_dump(include={"research_id", "status", "phase", "evidence_uri"})
        )

    def get_record(self, research_id: str) -> RunRecord:
        record = self.store.load(research_id)
        if record.output.status in ("queued", "running") and research_id not in self.tasks:
            if not owner_alive(record) or record.owner_pid == os.getpid():
                record.output.status, record.output.phase = "partial", "finished"
                record.output.stop_reason = "server_interrupted"
                record.output.usage.cost_complete = False
                record.output.warnings.append(
                    "The owning server stopped; resume with a new budget."
                )
                self.store.save(record)
        return record

    def get(self, research_id: str) -> SearchResult:
        return public_result(self.get_record(research_id).output)

    async def cancel(self, research_id: str) -> SearchResult:
        record = self.get_record(research_id)
        task = self.tasks.get(research_id)
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            record = self.store.load(research_id)
            # A task cancelled before its first instruction cannot checkpoint itself.
            if record.output.status == "queued":
                record.output.status, record.output.phase = "cancelled", "finished"
                record.output.stop_reason = "cancelled"
                self.store.save(record)
        elif record.output.status in ("queued", "running"):
            raise ValueError("This job belongs to another running server; cancel it there")
        return public_result(record.output)

    def resume(
        self,
        research_id: str,
        *,
        query: str | None = None,
        max_cost_usd: float = 3,
        timeout_seconds: float = 600,
        max_rounds: int = 2,
    ) -> JobInfo:
        parent = self.get_record(research_id)
        if parent.output.status in ("queued", "running"):
            raise ValueError("Research is still active; wait or cancel it before resuming")
        values = parent.options.model_dump()
        values.update(
            query=parent.options.query if query is None else query,
            depth="deep",
            parent_research_id=research_id,
            max_cost_usd=max_cost_usd,
            timeout_seconds=timeout_seconds,
            max_rounds=max_rounds,
        )
        values["source_urls"] = list(
            dict.fromkeys(
                parent.options.source_urls
                + [s.requested_url for s in parent.output.sources if s.status == "read"]
            )
        )[:12]
        return self.start(SearchOptions.model_validate(values), parent=parent)

    def evidence(
        self, research_id: str, source_id: str, offset: int = 0, limit: int = 6000
    ) -> dict:
        if offset < 0 or not 1 <= limit <= 12000:
            raise ValueError("offset must be nonnegative and limit must be between 1 and 12000")
        record = self.get_record(research_id)
        source = next((s for s in record.output.sources if s.id == source_id), None)
        if source is None:
            raise ValueError("Source not found in this research run")
        end = min(offset + limit, len(source.text))
        return {
            **source.model_dump(exclude={"text"}),
            "text": source.text[offset:end],
            "offset": offset,
            "next_offset": end if end < len(source.text) else None,
            "total_characters": len(source.text),
            "untrusted_source_content": True,
        }

    async def close(self) -> None:
        for research_id in list(self.tasks):
            await self.cancel(research_id)
