import asyncio
import json

import pytest

from grok_search_mcp.models import Claim, ClaimCheck, Evidence, Review
from grok_search_mcp.provider import BudgetExceeded, Completion
from grok_search_mcp.research import (
    ResearchRunner,
    apply_review,
    public_result,
    select_answer_claims,
)

QUESTION = "Which limits apply?"
QUOTE = "The standard tier permits ten requests per minute."


def script(gaps=None):
    evidence = [{"source_id": "s1", "quote": QUOTE}]
    return [
        {"objective": QUESTION, "questions": [QUESTION], "search_queries": ["tier limits"]},
        {"urls": ["https://example.com/docs"]},
        {
            "claims": [{"statement": QUOTE, "question": QUESTION, "evidence": evidence}],
            "gaps": gaps or [],
        },
        {
            "checks": [
                {
                    "claim_id": "c1",
                    "status": "supported",
                    "statement": QUOTE,
                    "evidence": evidence,
                    "reason": "The official source states this limit.",
                }
            ],
            "gaps": gaps or [],
        },
    ]


class Backend:
    def __init__(self, options, usage, responses):
        self.usage = usage
        self.responses = iter(responses)
        self.payloads = []
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.closed = True

    async def complete(self, instructions, payload, **kwargs):
        self.payloads.append((instructions, json.loads(payload), kwargs))
        self.usage.model_calls += 1
        item = next(self.responses)
        if isinstance(item, BaseException):
            raise item
        self.usage.reported_cost_usd += 0.01
        return Completion(content=json.dumps(item)) if not isinstance(item, Completion) else item


class Reader:
    def __init__(self, source):
        self.source = source
        self.urls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def read(self, url):
        self.urls.append(url)
        return self.source.model_copy(deep=True)


def runner(record, store, source, responses):
    backend = Backend(record.options, record.output.usage, responses)
    reader = Reader(source)
    run = ResearchRunner(
        record, store, backend_factory=lambda *_: backend, reader_factory=lambda *_: reader
    )
    return run, backend, reader


async def test_deep_end_to_end_saved_quotes_and_no_source_text_in_tool(record, store, source):
    record.options.query += f" Read {source.url}."
    run, backend, reader = runner(record, store, source, script())
    output = await run.run()
    assert output.status == "completed" and output.verification == "grok_reviewed"
    assert output.citations == [source.url] and output.claims[0].evidence[0].quote == QUOTE
    assert output.quality.questions_addressed == output.quality.questions_total == 1
    assert output.usage.model_calls == 4 and output.usage.reported_cost_usd == 0.04
    assert backend.closed and reader.urls == [source.url]
    assert all(p[2]["shape"] for p in backend.payloads)
    assert len([p for p in backend.payloads if p[2].get("search")]) == 1
    assert store.load(output.research_id).output.sources[0].text == source.text
    compact = public_result(output)
    assert compact.sources[0].text == "" and output.sources[0].text
    assert QUOTE in compact.result and source.url in compact.result


async def test_gaps_trigger_targeted_second_round(record, store, source):
    responses = script(["What about premium limits?"]) + script()[1:]
    run, backend, _ = runner(record, store, source, responses)
    output = await run.run()
    assert output.status == "completed" and output.rounds_completed == 2
    assert backend.payloads[4][1]["gaps"] == ["What about premium limits?"]


async def test_reviewer_can_resolve_preliminary_gaps(record, store, source):
    responses = script()
    responses[2]["gaps"] = ["Which standard limit applies?"]
    run, backend, _ = runner(record, store, source, responses)
    output = await run.run()
    assert output.status == "completed" and not output.gaps
    assert backend.payloads[3][1]["draft_gaps"] == ["Which standard limit applies?"]


async def test_missing_plan_question_prevents_false_completion(record, store, source):
    responses = script()
    responses[0]["questions"].append("What are the retry rules?")
    record.options.max_rounds = 1
    run, _, _ = runner(record, store, source, responses)
    output = await run.run()
    assert output.status == "partial" and "What are the retry rules?" in output.gaps
    assert output.quality.questions_total == 2 and output.quality.questions_addressed == 1


@pytest.mark.parametrize("failure", [BudgetExceeded("cost_budget"), TimeoutError()])
async def test_partial_results_preserve_reviewed_claims(record, store, source, failure):
    run, _, _ = runner(record, store, source, script(["A remaining question?"]) + [failure])
    output = await run.run()
    assert output.status == "partial" and output.claims[0].status == "supported"
    assert output.citations == [source.url]
    assert store.load(output.research_id).output.status == "partial"


async def test_schema_failure_retains_usage_and_evidence(record, store, source):
    run, _, _ = runner(record, store, source, script()[:2] + [{"claims": "bad"}])
    output = await run.run()
    assert output.status == "failed" and output.usage.model_calls == 3
    assert output.usage.reported_cost_usd == 0.03 and output.sources[0].text
    assert output.citations == []


async def test_cancel_persists_sources(record, store, source):
    run, backend, _ = runner(record, store, source, script()[:2] + [asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        await run.run()
    saved = store.load(record.output.research_id)
    assert saved.output.status == "cancelled" and saved.output.sources[0].text
    assert backend.closed


def test_fabricated_and_wrong_source_quotes_cannot_be_supported(source):
    claim = Claim(id="c1", statement=QUOTE, question=QUESTION)
    for evidence in (
        [Evidence(source_id="s1", quote="Fabricated statement not present in any source.")],
        [Evidence(source_id="missing", quote=QUOTE)],
        [],
    ):
        review = Review(
            checks=[
                ClaimCheck(
                    claim_id="c1",
                    status="supported",
                    statement=QUOTE,
                    evidence=evidence,
                    reason="Looks fine.",
                )
            ],
            gaps=[],
        )
        checked = apply_review([claim], review, [source])[0]
        assert checked.status == "unverified"


def test_omitted_duplicate_reviews_fail_closed_and_conflicts_preserved(source):
    claim = Claim(id="c1", statement="Unlimited requests are allowed.", question=QUESTION)
    check = ClaimCheck(
        claim_id="c1",
        status="contradicted",
        statement=claim.statement,
        evidence=[Evidence(source_id="s1", quote=QUOTE)],
        reason="Explicit rate limit.",
    )
    for checks in ([], [check, check]):
        assert (
            apply_review([claim], Review(checks=checks, gaps=[]), [source])[0].status
            == "unverified"
        )
    checked = apply_review([claim], Review(checks=[check], gaps=[]), [source])[0]
    assert checked.status == "contradicted" and checked.statement == claim.statement


async def test_standard_retains_inline_citations_and_marks_no_verification(record, store, source):
    record.options.depth = record.output.depth = "standard"
    reply = Completion(content="Answer", citations=[source.url], inline_citations=[{"id": "1"}])
    run, _, reader = runner(record, store, source, [reply])
    output = await run.run()
    assert output.status == "completed" and output.verification == "not_requested"
    assert output.inline_citations == [{"id": "1"}] and not reader.urls


async def test_no_readable_sources_never_claims_completion(record, store, source):
    source.status, source.text = "failed", ""
    record.options.max_rounds = 1
    run, _, _ = runner(record, store, source, script()[:2])
    output = await run.run()
    assert output.status == "partial" and not output.claims and output.gaps == [QUESTION]


def test_concise_answer_selection_preserves_coverage_and_excludes_unverified(record, source):
    claims = [
        Claim(id="c1", statement="First fact", question="q1", status="supported"),
        Claim(id="c2", statement="Repeated first fact", question="q1", status="supported"),
        Claim(id="c3", statement="Different fact", question="q2", status="qualified"),
        Claim(id="c4", statement="Fabrication", question="q3", status="unverified"),
    ]
    selected = select_answer_claims(claims, ["unknown", "c4", "c1", "c1"])
    assert selected == ["c1", "c3"]
    record.output.claims, record.output.answer_claim_ids = claims, selected
    rendered = public_result(record.output).result
    assert "First fact" in rendered and "Different fact" in rendered
    assert "Repeated first fact" not in rendered and "Fabrication" not in rendered
