"""Bounded source text extraction; executable as a disposable parser process."""

import json
import sys
from io import BytesIO

from bs4 import BeautifulSoup
from pypdf import PdfReader

MAX_BYTES = 2 * 1024 * 1024
MAX_TEXT = 18000


def normalize_text(text: str) -> str:
    return " ".join(text.split())


def extract_text(body: bytes, media_type: str) -> tuple[str, str, bool]:
    truncated = False
    if media_type == "application/pdf":
        pdf = PdfReader(BytesIO(body))
        title = str((pdf.metadata or {}).get("/Title", ""))[:300]
        fragments = []
        size = 0
        for page in pdf.pages[:20]:
            text = page.extract_text() or ""
            fragments.append(text[:MAX_TEXT])
            size += len(text)
            if size > MAX_TEXT:
                truncated = True
                break
        truncated |= len(pdf.pages) > 20
        text = " ".join(fragments)
    elif media_type in ("text/html", "application/xhtml+xml"):
        soup = BeautifulSoup(body, "html.parser")
        title = normalize_text(soup.title.get_text())[:300] if soup.title else ""
        for tag in soup(
            [
                "script",
                "style",
                "nav",
                "header",
                "footer",
                "aside",
                "form",
                "noscript",
                "svg",
                "template",
            ]
        ):
            tag.decompose()
        root = soup.find("main") or soup.find("article") or soup.body or soup
        text = root.get_text(" ", strip=True)
    else:
        title, text = "", body.decode("utf-8", errors="replace")
    text = normalize_text(text)
    return title, text[:MAX_TEXT], truncated or len(text) > MAX_TEXT


def main():
    # CPU/address-space caps where supported; the parent also enforces a wall deadline.
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (4, 4))
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    except (ImportError, ValueError, OSError):
        pass
    body = sys.stdin.buffer.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("Source exceeds parser limit")
    print(json.dumps(extract_text(body, sys.argv[1])))


if __name__ == "__main__":
    main()
