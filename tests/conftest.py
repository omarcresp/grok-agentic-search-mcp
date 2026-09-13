import hashlib
from uuid import uuid4

import pytest

from grok_search_mcp.models import RunRecord, SearchOptions, SearchResult, Source
from grok_search_mcp.store import ResearchStore


@pytest.fixture(autouse=True)
def isolated_key(monkeypatch):
    # Offline tests must never consume a developer's real API key.
    monkeypatch.setenv("XAI_API_KEY", "offline-test-key")


@pytest.fixture
def store(tmp_path):
    return ResearchStore(tmp_path)


@pytest.fixture
def record():
    return RunRecord(
        options=SearchOptions(query="Which limits apply?", depth="deep"),
        output=SearchResult(research_id=str(uuid4()), depth="deep"),
    )


@pytest.fixture
def source():
    text = (
        "The standard tier permits ten requests per minute. "
        "The premium tier permits one hundred requests per minute."
    )
    return Source(
        id="s1",
        requested_url="https://example.com/docs",
        url="https://example.com/docs",
        status="read",
        text=text,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
