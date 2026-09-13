import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from grok_search_mcp import reader
from grok_search_mcp.models import SearchOptions


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1",
        "http://[::1]/",
        "http://169.254.169.254/",
        "http://[::ffff:127.0.0.1]/",
        "file:///etc/passwd",
        "http://user:pass@example.com",
        "http://example.com:8080",
        "https://example.com/\nfoo",
    ],
)
def test_private_and_unsafe_urls_rejected(url):
    with pytest.raises(ValueError):
        reader.canonical_url(url)


def test_canonical_and_source_policies():
    assert reader.canonical_url("https://EXAMPLE.com:443/path#ref") == "https://example.com/path"
    policy = reader.SourcePolicy(
        SearchOptions(query="q", allowed_domains=["example.com"], allowed_x_handles=["alice"])
    )
    assert policy.allows("https://docs.example.com/a")
    assert not policy.allows("https://example.com.evil.org")
    assert policy.allows("https://x.com/alice/status/1")
    assert not policy.allows("https://x.com/bob/status/1")
    assert not policy.allows("https://t.co/a")


async def test_dns_validates_actual_connection_addresses(monkeypatch):
    delegate = SimpleNamespace(
        resolve=AsyncMock(return_value=[{"host": "8.8.8.8"}, {"host": "10.0.0.1"}]),
        close=AsyncMock(),
    )
    monkeypatch.setattr(reader, "DefaultResolver", lambda: delegate)
    resolver = reader.PublicResolver()
    with pytest.raises(OSError, match="Non-public"):
        await resolver.resolve("public-looking.example")
    delegate.resolve.return_value = [{"host": "8.8.8.8"}]
    assert await resolver.resolve("example.com") == [{"host": "8.8.8.8"}]
    await resolver.close()
    delegate.close.assert_awaited_once()


def test_html_extraction_and_bounds():
    body = (
        b"<title>Example</title><nav>Nav noise</nav><main>Actual evidence "
        b"<script>inject()</script><p>more facts</p></main>"
    )
    title, text, truncated = reader.extract_text(body, "text/html")
    assert title == "Example" and text == "Actual evidence more facts" and not truncated
    _, text, truncated = reader.extract_text(b"a" * (reader.MAX_TEXT + 1), "text/plain")
    assert len(text) == reader.MAX_TEXT and truncated


class Response:
    def __init__(self, status=200, headers=None, body=b"The page has useful evidence. " * 10):
        self.status = status
        self.headers = headers or {"Content-Type": "text/plain"}
        self.body = body
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    def raise_for_status(self):
        pass

    async def iter_chunked(self, size):
        for offset in range(0, len(self.body), size):
            yield self.body[offset : offset + size]


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.urls = []

    def get(self, url, **kwargs):
        assert kwargs == {"allow_redirects": False}
        self.urls.append(url)
        return next(self.responses)


@pytest.mark.parametrize("location", ["http://127.0.0.1/secret", "https://excluded.com/secret"])
async def test_redirect_rechecks_network_and_filters(location):
    fetcher = reader.SourceReader(
        reader.SourcePolicy(SearchOptions(query="q", allowed_domains=["example.com"]))
    )
    fetcher.session = Session([Response(302, {"Location": location})])
    source = await fetcher.read("https://example.com/start")
    assert source.status == "failed"
    assert len(fetcher.session.urls) == 1


async def test_public_redirect_provenance_and_body_bounds():
    fetcher = reader.SourceReader(reader.SourcePolicy(SearchOptions(query="q")))
    fetcher.session = Session([Response(302, {"Location": "/final"}), Response()])
    source = await fetcher.read("https://example.com/start")
    assert source.status == "read" and source.url == "https://example.com/final"
    assert source.requested_url.endswith("/start") and source.content_hash
    fetcher.session = Session([Response(body=b"a" * (reader.MAX_BYTES + 1))])
    source = await fetcher.read("https://example.com/large")
    assert source.status == "failed" and "2 MiB" in source.error


async def test_reader_cancellation_propagates(monkeypatch):
    fetcher = reader.SourceReader(reader.SourcePolicy(SearchOptions(query="q")))
    monkeypatch.setattr(fetcher, "_read", AsyncMock(side_effect=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        await fetcher.read("https://example.com")


async def test_pdf_extraction_in_disposable_process():
    from io import BytesIO

    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(
        b"BT /F1 12 Tf 10 10 Td (The standard tier permits ten requests per minute.) Tj ET"
    )
    page[NameObject("/Contents")] = stream
    writer.add_metadata({"/Title": "Source policy"})
    body = BytesIO()
    writer.write(body)
    title, text, truncated = await reader.extract_in_process(body.getvalue(), "application/pdf")
    assert title == "Source policy" and "ten requests per minute" in text and not truncated


async def test_parser_is_killed_on_cancel_and_has_no_api_credentials(monkeypatch):
    from unittest.mock import Mock

    process = SimpleNamespace(
        returncode=None,
        communicate=AsyncMock(side_effect=asyncio.CancelledError),
        kill=Mock(),
        wait=AsyncMock(),
    )
    launch = AsyncMock(return_value=process)
    monkeypatch.setattr(reader.asyncio, "create_subprocess_exec", launch)
    with pytest.raises(asyncio.CancelledError):
        await reader.extract_in_process(b"untrusted text", "text/plain")
    process.kill.assert_called_once()
    process.wait.assert_awaited_once()
    assert "XAI_API_KEY" not in launch.call_args.kwargs["env"]
    assert "shell" not in launch.call_args.kwargs
