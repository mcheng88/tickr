from __future__ import annotations

import urllib.request
from html.parser import HTMLParser

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_SKIP = {"script", "style", "nav", "aside", "figure", "footer", "header", "form"}
# Paragraphs only — pulling headings/list items drags in nav menus on most sites.
_TEXT = {"p", "blockquote"}


class _Article(HTMLParser):
    """Crude readable-text extractor: collect text inside paragraph/heading/list
    tags, drop chrome (script/nav/footer/…). Good enough for clean news HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0
        self._capture = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP:
            self._skip += 1
        elif tag in _TEXT:
            self._capture += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self._skip:
            self._skip -= 1
        elif tag in _TEXT and self._capture:
            self._capture -= 1
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self._capture and not self._skip:
            text = data.strip()
            if text:
                self.parts.append(text + " ")


def fetch_article(url: str, timeout: int = 12) -> str:
    """Fetch a URL and return extracted readable text (or a short error note)."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        html = r.read().decode("utf-8", "replace")
    parser = _Article()
    parser.feed(html)
    text = "".join(parser.parts).strip()
    # collapse runs of blank lines
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text or "(couldn't extract readable text — try opening in the browser with 'b')"
