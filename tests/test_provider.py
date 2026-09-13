import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from xai_sdk.proto import chat_pb2

from grok_search_mcp import provider
from grok_search_mcp.models import Discovery, SearchOptions, Usage


def response(cost=0.02):
    proto = chat_pb2.GetChatCompletionResponse(citations=["https://example.com/a"] * 2)
    return SimpleNamespace(
        content="A cited answer",
        citations=proto.citations,
        inline_citations=[chat_pb2.InlineCitation(id="ref", start_index=1, end_index=3)],
        usage=SimpleNamespace(
            prompt_tokens=10, completion_tokens=5, reasoning_tokens=2, cached_prompt_text_tokens=4
        ),
        cost_usd=cost,
        server_side_tool_usage={"SERVER_SIDE_TOOL_WEB_SEARCH": 2},
        finish_reason="REASON_STOP",
    )


def client_for(monkeypatch, reply):
    chat = SimpleNamespace(sample=AsyncMock(return_value=reply))
    client = SimpleNamespace(
        chat=SimpleNamespace(create=Mock(return_value=chat)), close=AsyncMock()
    )
    constructor = Mock(return_value=client)
    monkeypatch.setattr(provider, "AsyncClient", constructor)
    return client, constructor


async def test_real_protobuf_citations_timeout_and_grok_only(monkeypatch):
    reply = response()
    with pytest.raises(TypeError):
        json.dumps(reply.citations)  # Original implementation's reproduced failure.
    client, constructor = client_for(monkeypatch, reply)
    usage = Usage()
    async with provider.GrokBackend(
        SearchOptions(
            query="q", timeout_seconds=123, allowed_domains=["example.com"], include_x=False
        ),
        usage,
    ) as backend:
        result = await backend.complete(
            "instructions", "question", search=True, effort="low", shape=Discovery
        )
    assert constructor.call_args.kwargs == {"api_key": "offline-test-key", "timeout": 123}
    args = client.chat.create.call_args.kwargs
    assert args["model"] == "grok-4.6" and args["reasoning_effort"] == "low"
    assert args["response_format"] is Discovery and args["max_turns"] == 6
    assert args["tool_choice"] == "required" and args["store_messages"] is False
    assert len(args["tools"]) == 1
    assert list(args["tools"][0].web_search.allowed_domains) == ["example.com"]
    assert result.citations == ["https://example.com/a"]
    assert json.loads(json.dumps(result.inline_citations))[0]["start_index"] == 1
    assert usage.reported_cost_usd == 0.02 and usage.model_calls == 1
    assert usage.server_side_tool_usage["SERVER_SIDE_TOOL_WEB_SEARCH"] == 2
    client.close.assert_awaited_once()


@pytest.mark.parametrize("cost,reason", [(0.2, "cost_budget"), (None, "cost_unavailable")])
async def test_budget_stops_new_calls_including_unknown_cost(monkeypatch, cost, reason):
    client, _ = client_for(monkeypatch, response(cost))
    usage = Usage()
    async with provider.GrokBackend(SearchOptions(query="q", max_cost_usd=0.1), usage) as backend:
        await backend.complete("i", "q")
        with pytest.raises(provider.BudgetExceeded, match=reason):
            await backend.complete("i", "q")
    assert client.chat.create.call_count == 1


async def test_cancellation_marks_cost_unknown_and_closes_client(monkeypatch):
    client, _ = client_for(monkeypatch, response())
    client.chat.create.return_value.sample.side_effect = asyncio.CancelledError
    usage = Usage()
    with pytest.raises(asyncio.CancelledError):
        async with provider.GrokBackend(SearchOptions(query="q"), usage) as backend:
            await backend.complete("i", "q")
    assert usage.model_calls == 1 and not usage.cost_complete
    client.close.assert_awaited_once()


async def test_x_filters_forwarded(monkeypatch):
    client, _ = client_for(monkeypatch, response())
    options = SearchOptions(
        query="q",
        allowed_x_handles=["@xAI"],
        from_date="2026-09-01",
        to_date="2026-09-12",
        enable_video_understanding=False,
    )
    async with provider.GrokBackend(options, Usage()) as backend:
        await backend.complete("i", "q", search=True)
    tool = client.chat.create.call_args.kwargs["tools"][1].x_search
    assert list(tool.allowed_x_handles) == ["xai"]
    assert not tool.enable_video_understanding
    assert tool.from_date.ToDatetime().year == 2026


async def test_search_cannot_silently_answer_from_memory(monkeypatch):
    reply = response()
    reply.server_side_tool_usage = {}
    client_for(monkeypatch, reply)
    usage = Usage()
    async with provider.GrokBackend(SearchOptions(query="q"), usage) as backend:
        with pytest.raises(provider.SearchNotPerformed):
            await backend.complete("i", "q", search=True)
    assert usage.reported_cost_usd == 0.02
