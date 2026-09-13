"""The only model provider: xAI's native asynchronous SDK, always Grok 4.6."""

import asyncio
import os
from collections import Counter
from dataclasses import dataclass, field

from google.protobuf.json_format import MessageToDict
from pydantic import BaseModel
from xai_sdk import AsyncClient
from xai_sdk.chat import system, user
from xai_sdk.tools import web_search, x_search

from .models import MODEL, SearchOptions, Usage


@dataclass
class Completion:
    content: str
    citations: list[str] = field(default_factory=list)
    inline_citations: list[dict] = field(default_factory=list)
    finish_reason: str = ""


class BudgetExceeded(Exception):
    pass


class SearchNotPerformed(Exception):
    pass


def get_client(timeout: float) -> AsyncClient:
    key = os.getenv("XAI_API_KEY")
    if not key:
        raise ValueError("Set XAI_API_KEY before starting research")
    return AsyncClient(api_key=key, timeout=timeout)


def record_usage(usage: Usage, response) -> None:
    details = response.usage
    usage.prompt_tokens += details.prompt_tokens
    usage.completion_tokens += details.completion_tokens
    usage.reasoning_tokens += details.reasoning_tokens
    usage.cached_prompt_tokens += details.cached_prompt_text_tokens
    cost = response.cost_usd
    if cost is None:
        usage.cost_complete = False
    else:
        usage.reported_cost_usd += cost
    counts = Counter(usage.server_side_tool_usage)
    counts.update(response.server_side_tool_usage)
    usage.server_side_tool_usage = dict(counts)


class GrokBackend:
    def __init__(self, options: SearchOptions, usage: Usage):
        self.options = options
        self.usage = usage
        self.client = None

    async def __aenter__(self):
        self.client = get_client(self.options.timeout_seconds)
        return self

    async def __aexit__(self, *_):
        if self.client is not None:
            await self.client.close()

    async def complete(
        self,
        instructions: str,
        payload: str,
        *,
        shape: type[BaseModel] | None = None,
        search: bool = False,
        effort: str = "high",
        max_tokens: int = 5000,
    ) -> Completion:
        if self.usage.reported_cost_usd >= self.options.max_cost_usd:
            raise BudgetExceeded("cost_budget")
        if not self.usage.cost_complete:
            raise BudgetExceeded("cost_unavailable")
        tools = []
        if search:
            o = self.options
            tools.append(
                web_search(
                    allowed_domains=o.allowed_domains or None,
                    excluded_domains=o.excluded_domains or None,
                    enable_image_understanding=o.enable_image_understanding,
                )
            )
            if o.include_x:
                tools.append(
                    x_search(
                        allowed_x_handles=o.allowed_x_handles or None,
                        excluded_x_handles=o.excluded_x_handles or None,
                        from_date=o.from_date,
                        to_date=o.to_date,
                        enable_image_understanding=o.enable_image_understanding,
                        enable_video_understanding=o.enable_video_understanding,
                    )
                )
        chat = self.client.chat.create(
            model=MODEL,
            messages=[system(instructions), user(payload)],
            reasoning_effort=effort,
            max_tokens=max_tokens,
            max_turns=6 if search else None,
            tools=tools or None,
            tool_choice="required" if search else None,
            store_messages=False,
            parallel_tool_calls=True,
            response_format=shape,
            include=["inline_citations"] if search else None,
        )
        self.usage.model_calls += 1
        try:
            response = await chat.sample()
        except (Exception, asyncio.CancelledError):
            # A failed/cancelled RPC may still incur provider charges.
            self.usage.cost_complete = False
            raise
        record_usage(self.usage, response)
        if search and not any(response.server_side_tool_usage.values()):
            raise SearchNotPerformed("Hosted search execution could not be confirmed")
        return Completion(
            content=response.content or "",
            citations=list(dict.fromkeys(response.citations or [])),
            inline_citations=[
                MessageToDict(c, preserving_proto_field_name=True)
                for c in response.inline_citations
            ],
            finish_reason=response.finish_reason,
        )
