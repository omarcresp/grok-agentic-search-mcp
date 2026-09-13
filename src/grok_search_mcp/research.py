"""A bounded research loop over source evidence, with separate Grok review contexts."""

import asyncio
import json
import logging
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import grpc
from pydantic import ValidationError

from . import prompts
from .models import Claim, Discovery, Draft, Quality, ResearchPlan, Review, RunRecord, SearchResult
from .provider import BudgetExceeded, GrokBackend, SearchNotPerformed
from .reader import SourcePolicy, SourceReader, canonical_url, normalize_text, urls_in_query
from .store import ResearchStore

logger = logging.getLogger(__name__)
Progress = Callable[[str], Awaitable[None]]
MAX_SOURCES = 12


def valid_evidence(evidence, sources):
    """Retain only actual quotations from retrieved documents, never generated citations."""
    by_id = {s.id: s for s in sources if s.status == "read"}
    return [
        e
        for e in evidence
        if e.source_id in by_id
        and normalize_text(e.quote) in normalize_text(by_id[e.source_id].text)
    ]


def unanswered_questions(output: SearchResult) -> list[str]:
    addressed = {
        normalize_text(c.question)
        for c in output.claims
        if c.status in ("supported", "qualified", "contradicted")
    }
    return (
        [q for q in output.plan.questions if normalize_text(q) not in addressed]
        if output.plan
        else []
    )


def refresh_findings(output: SearchResult) -> None:
    by_id = {s.id: s for s in output.sources}
    counts = Counter(c.status for c in output.claims)
    output.quality = Quality(
        questions_total=len(output.plan.questions) if output.plan else 0,
        questions_addressed=len(output.plan.questions) - len(unanswered_questions(output))
        if output.plan
        else 0,
        supported_claims=counts["supported"],
        qualified_claims=counts["qualified"],
        contradicted_claims=counts["contradicted"],
        unverified_claims=counts["unverified"],
        sources_read=sum(s.status == "read" for s in output.sources),
        sources_failed=sum(s.status == "failed" for s in output.sources),
        distinct_domains=len(
            {urlsplit(s.url).hostname for s in output.sources if s.status == "read"}
        ),
    )
    if output.depth == "deep":
        output.citations = list(
            dict.fromkeys(
                by_id[e.source_id].url
                for c in output.claims
                if c.status != "unverified"
                for e in c.evidence
                if e.source_id in by_id
            )
        )
        output.result = render_answer(output)
    output.source_count = len(output.citations)


def apply_review(claims: list[Claim], review: Review, sources) -> list[Claim]:
    counts = Counter(check.claim_id for check in review.checks)
    checks = {check.claim_id: check for check in review.checks}
    result = []
    for claim in claims:
        checked = claim.model_copy(deep=True)
        check = checks.get(claim.id)
        if not check or counts[claim.id] != 1:
            checked.status = "unverified"
            checked.reason = "Reviewer omitted this claim or returned duplicate judgments."
        else:
            evidence = valid_evidence(check.evidence, sources)
            # Losing even one referenced passage can invalidate a multi-source judgment.
            if check.status != "unverified" and (
                not evidence or len(evidence) != len(check.evidence)
            ):
                checked.status = "unverified"
                checked.reason = "Reviewer evidence could not be matched to retrieved text."
            else:
                checked.status = check.status
                checked.reason = check.reason
                checked.evidence = evidence
                if check.status in ("supported", "qualified"):
                    checked.statement = check.statement
        result.append(checked)
    return result


def render_answer(output: SearchResult) -> str:
    by_id = {s.id: s for s in output.sources}
    lines = []
    claims_by_id = {c.id: c for c in output.claims}
    selected = [claims_by_id[cid] for cid in output.answer_claim_ids if cid in claims_by_id]
    for claim in selected or output.claims:
        if claim.status not in ("supported", "qualified"):
            continue
        refs = list(dict.fromkeys(e.source_id for e in claim.evidence))
        links = " ".join(f"[{sid}](<{by_id[sid].url}>)" for sid in refs)
        qualifier = " (qualified)" if claim.status == "qualified" else ""
        lines.append(f"- {claim.statement}{qualifier} {links}")
    if not lines:
        lines = ["No claims could be established from the retrieved evidence."]
    conflicts = [c for c in output.claims if c.status == "contradicted"]
    if conflicts:
        lines += ["", "Conflicting evidence:"]
        for c in conflicts:
            refs = " ".join(f"[{e.source_id}](<{by_id[e.source_id].url}>)" for e in c.evidence)
            lines.append(f"- Evidence contradicts the claim “{c.statement}”. {refs}")
    if output.gaps:
        lines += ["", "Unresolved questions:", *[f"- {gap}" for gap in output.gaps]]
    if output.status == "partial":
        lines += [
            "",
            f"Research is partial ({output.stop_reason}); evidence is available to resume.",
        ]
    return "\n".join(lines)


def select_answer_claims(claims: list[Claim], requested: list[str]) -> list[str]:
    """Select existing reviewed text, while retaining coverage of addressed questions."""
    supported = {c.id: c for c in claims if c.status in ("supported", "qualified")}
    selected = list(dict.fromkeys(cid for cid in requested if cid in supported))
    if not selected:
        return list(supported)
    addressed = {normalize_text(supported[cid].question) for cid in selected}
    for cid, claim in supported.items():
        if normalize_text(claim.question) not in addressed:
            selected.append(cid)
            addressed.add(normalize_text(claim.question))
    return selected


class ResearchRunner:
    def __init__(
        self,
        record: RunRecord,
        store: ResearchStore,
        *,
        progress: Progress | None = None,
        backend_factory=GrokBackend,
        reader_factory=SourceReader,
    ):
        self.record, self.store = record, store
        self.options, self.output = record.options, record.output
        self.progress = progress
        self.backend_factory, self.reader_factory = backend_factory, reader_factory
        self.started = time.monotonic()
        self.policy = SourcePolicy(self.options)
        self.attempted = {s.requested_url for s in self.output.sources}

    async def phase(self, name: str) -> None:
        self.output.phase = name
        self.output.elapsed_seconds = round(time.monotonic() - self.started, 2)
        refresh_findings(self.output)
        self.store.save(self.record)
        if self.progress:
            await self.progress(name)

    async def run(self) -> SearchResult:
        self.output.status = "running"
        try:
            await asyncio.wait_for(self.execute(), timeout=self.options.timeout_seconds)
        except BudgetExceeded as exc:
            self.output.status, self.output.stop_reason = "partial", str(exc)
        except asyncio.TimeoutError:
            self.output.status, self.output.stop_reason = "partial", "deadline"
        except asyncio.CancelledError:
            self.output.status, self.output.stop_reason = "cancelled", "cancelled"
            self.finish()
            raise
        except Exception as exc:
            self.output.status = "partial" if self.output.claims else "failed"
            self.output.stop_reason = "provider_or_research_error"
            if isinstance(exc, SearchNotPerformed):
                self.output.stop_reason = "search_not_confirmed"
            elif isinstance(exc, ValidationError):
                self.output.stop_reason = "invalid_model_output"
            elif isinstance(exc, grpc.RpcError):
                self.output.stop_reason = {
                    grpc.StatusCode.UNAUTHENTICATED: "provider_authentication",
                    grpc.StatusCode.PERMISSION_DENIED: "provider_access_denied",
                    grpc.StatusCode.RESOURCE_EXHAUSTED: "provider_rate_limited",
                    grpc.StatusCode.DEADLINE_EXCEEDED: "deadline",
                    grpc.StatusCode.UNAVAILABLE: "provider_unavailable",
                }.get(exc.code(), "provider_error")
            # Never persist API keys, provider request headers, or raw exception payloads.
            self.output.warnings.append(f"Research stage failed: {type(exc).__name__}")
            logger.warning(
                "Research %s failed at %s (%s)",
                self.output.research_id,
                self.output.phase,
                type(exc).__name__,
            )
        self.finish()
        return self.output

    def finish(self) -> None:
        self.output.phase = "finished"
        self.output.elapsed_seconds = round(time.monotonic() - self.started, 2)
        if self.options.depth == "deep" and self.output.plan:
            self.output.gaps = list(
                dict.fromkeys(self.output.gaps + unanswered_questions(self.output))
            )
        refresh_findings(self.output)
        if not self.output.result:
            self.output.result = f"Search did not finish ({self.output.stop_reason})."
        self.output.source_count = len(self.output.citations)
        if not self.output.usage.cost_complete:
            self.output.warnings.append(
                "Reported cost is incomplete; interrupted or unreported calls may be billed."
            )
        if self.output.usage.reported_cost_usd > self.options.max_cost_usd:
            self.output.warnings.append(
                "The last hosted call exceeded the between-call cost threshold."
            )
        self.output.warnings = list(dict.fromkeys(self.output.warnings))
        self.store.save(self.record)

    async def typed(self, backend, instructions, payload, shape, **kwargs):
        response = await backend.complete(
            instructions, json.dumps(payload, ensure_ascii=False), shape=shape, **kwargs
        )
        # Usage is recorded by the backend before schema parsing can fail.
        if "LENGTH" in response.finish_reason or "MAX" in response.finish_reason:
            self.output.warnings.append("A model response reached its output limit.")
        return shape.model_validate_json(response.content)

    async def read_urls(self, reader, candidates: list[str], limit: int) -> int:
        if limit <= 0:
            return 0
        urls = []
        for candidate in candidates:
            try:
                url = canonical_url(candidate)
                if url in self.attempted or not self.policy.allows(url):
                    continue
            except (ValueError, UnicodeError):
                self.output.warnings.append(
                    "A candidate URL was rejected as invalid or non-public."
                )
                continue
            self.attempted.add(url)
            urls.append(url)
            if len(urls) >= limit:
                break
        if not urls:
            return 0
        sources = await asyncio.gather(*(reader.read(url) for url in urls))
        existing_hashes = {s.content_hash for s in self.output.sources if s.status == "read"}
        existing_ids = {s.id for s in self.output.sources}
        added = 0
        for source in sources:
            if source.id in existing_ids:
                continue
            existing_ids.add(source.id)
            if source.status == "read" and source.content_hash in existing_hashes:
                self.output.warnings.append(f"Duplicate source content excluded: {source.url}")
                continue
            if source.status == "read":
                existing_hashes.add(source.content_hash)
                added += 1
            else:
                self.output.warnings.append(
                    f"Could not read {source.requested_url}: {source.error}"
                )
            self.output.sources.append(source)
        return added

    def documents(self):
        return [
            s.model_dump(include={"id", "url", "title", "retrieved_at", "text", "truncated"})
            for s in self.output.sources
            if s.status == "read"
        ]

    async def execute(self) -> None:
        o = self.options
        request = {
            "question": o.query,
            "current_utc_date": datetime.now(timezone.utc).date().isoformat(),
            "source_urls": o.source_urls,
            "x_from_date": str(o.from_date),
            "x_to_date": str(o.to_date),
            "prompt_version": prompts.VERSION,
        }
        async with self.backend_factory(o, self.output.usage) as backend:
            if o.depth == "standard":
                await self.phase("searching")
                response = await backend.complete(
                    prompts.STANDARD,
                    json.dumps(request),
                    search=True,
                    effort="low",
                    max_tokens=4000,
                )
                self.output.result = response.content
                self.output.citations = response.citations
                self.output.inline_citations = response.inline_citations
                self.output.verification = "not_requested"
                self.output.status = "completed" if response.content else "partial"
                self.output.stop_reason = (
                    "standard_search" if response.content else "empty_response"
                )
                if any(reason in response.finish_reason.upper() for reason in ("LENGTH", "MAX")):
                    self.output.status, self.output.stop_reason = "partial", "output_limit"
                return
            async with self.reader_factory(self.policy) as reader:
                await self.phase("reading_supplied_sources")
                seeds = list(dict.fromkeys(o.source_urls + urls_in_query(o.query)))[:MAX_SOURCES]
                await self.read_urls(reader, seeds, MAX_SOURCES)
                await self.phase("planning")
                self.output.plan = await self.typed(
                    backend, prompts.PLAN, request, ResearchPlan, effort="low", max_tokens=2000
                )
                stagnant = 0
                for round_index in range(o.max_rounds):
                    await self.phase(f"searching_round_{round_index + 1}")
                    discovery = await self.typed(
                        backend,
                        prompts.DISCOVER,
                        {
                            **request,
                            "plan": self.output.plan.model_dump(),
                            "gaps": self.output.gaps,
                            "already_read": [
                                s.url for s in self.output.sources if s.status == "read"
                            ],
                        },
                        Discovery,
                        search=True,
                        effort="high",
                        max_tokens=3000,
                    )
                    await self.phase(f"reading_round_{round_index + 1}")
                    remaining = MAX_SOURCES - sum(s.status == "read" for s in self.output.sources)
                    added = (
                        await self.read_urls(reader, discovery.urls, min(6, remaining))
                        if remaining > 0
                        else 0
                    )
                    if not self.documents():
                        self.output.gaps = list(self.output.plan.questions)
                        stagnant += 1
                        continue
                    await self.phase(f"extracting_round_{round_index + 1}")
                    draft = await self.typed(
                        backend,
                        prompts.EXTRACT,
                        {
                            **request,
                            "plan": self.output.plan.model_dump(),
                            "documents": self.documents(),
                        },
                        Draft,
                        effort="high",
                        max_tokens=6500,
                    )
                    proposed = []
                    for index, c in enumerate(draft.claims):
                        evidence = valid_evidence(c.evidence, self.output.sources)
                        proposed.append(
                            Claim(
                                id=f"c{index + 1}",
                                statement=c.statement,
                                question=c.question,
                                evidence=evidence,
                            )
                        )
                    # Preserve last reviewed results until the next review succeeds.
                    if not self.output.claims:
                        self.output.claims = proposed
                    await self.phase(f"verifying_round_{round_index + 1}")
                    review = await self.typed(
                        backend,
                        prompts.VERIFY,
                        {
                            **request,
                            "plan": self.output.plan.model_dump(),
                            "claims": [c.model_dump() for c in proposed],
                            "draft_gaps": draft.gaps,
                            "documents": self.documents(),
                        },
                        Review,
                        effort="high",
                        max_tokens=7000,
                    )
                    self.output.claims = apply_review(proposed, review, self.output.sources)
                    self.output.answer_claim_ids = select_answer_claims(
                        self.output.claims, review.answer_claim_ids
                    )
                    self.output.verification = "grok_reviewed"
                    unsupported = [
                        c.question for c in self.output.claims if c.status == "unverified"
                    ]
                    missing = unanswered_questions(self.output)
                    self.output.gaps = list(dict.fromkeys(missing + review.gaps + unsupported))[:18]
                    self.output.rounds_completed += 1
                    await self.phase(f"reviewed_round_{round_index + 1}")
                    if self.output.claims and not self.output.gaps:
                        self.output.status, self.output.stop_reason = (
                            "completed",
                            "coverage_satisfied",
                        )
                        return
                    stagnant = stagnant + 1 if not added else 0
                    if stagnant >= 2:
                        self.output.stop_reason = "no_new_evidence"
                        break
                    if sum(s.status == "read" for s in self.output.sources) >= MAX_SOURCES:
                        self.output.stop_reason = "source_limit"
                        break
                self.output.status = "partial"
                self.output.stop_reason = self.output.stop_reason or "round_limit"


def reusable_sources(parent: RunRecord, options) -> list:
    """Reuse recent source snapshots, never prior model answers as evidence."""
    policy = SourcePolicy(options)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    return [
        s.model_copy(deep=True)
        for s in parent.output.sources
        if s.status == "read"
        and datetime.fromisoformat(s.retrieved_at) >= cutoff
        and policy.allows(s.url)
    ][:MAX_SOURCES]


def public_result(output: SearchResult) -> SearchResult:
    result = SearchResult.model_validate(
        output.model_dump(exclude={"sources": {"__all__": {"text"}}})
    )
    refresh_findings(result)
    return result
