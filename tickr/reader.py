from __future__ import annotations

import re
import urllib.error
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


# Browser-like headers — some sites (MarketWatch, etc.) 401/403 a bare UA.
_HEADERS = {
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


# arXiv links resolve to the abstract page; the full paper is the native HTML at
# /html/<id>. Rewrite abs/pdf links to that (newer papers only — fall back if 404).
_ARXIV = re.compile(r"^https?://arxiv\.org/(?:abs|pdf)/(.+?)(?:\.pdf)?/?$")


def _arxiv_html_url(url: str) -> str | None:
    m = _ARXIV.match(url)
    return f"https://arxiv.org/html/{m.group(1)}" if m else None


_MAX_BYTES = 4_000_000  # cap the read so a giant/binary response can't blow up the UI


class _NotReadable(Exception):
    """Response isn't HTML text (e.g. a PDF or other binary)."""


def _get_html(url: str, timeout: int) -> str:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        ctype = (r.headers.get_content_type() or "").lower()
        if ctype and not (ctype.startswith("text/") or "xml" in ctype or "html" in ctype):
            raise _NotReadable(ctype)  # PDF, image, octet-stream, …
        raw = r.read(_MAX_BYTES)
    return raw.decode("utf-8", "replace")


def _extract(html: str) -> str:
    parser = _Article()
    parser.feed(html)
    text = "".join(parser.parts).strip()
    while "\n\n\n" in text:  # collapse runs of blank lines
        text = text.replace("\n\n\n", "\n\n")
    return text or "(couldn't extract readable text — try opening in the browser with 'b')"


def fetch_article(url: str, timeout: int = 12) -> str:
    """Fetch a URL and return extracted readable text (or a short error note).

    For arXiv links, pulls the full HTML paper instead of just the abstract."""
    alt = _arxiv_html_url(url)
    if alt:
        try:
            return _extract(_get_html(alt, timeout))
        except Exception:
            pass  # no HTML version (older paper) → fall back to the original page
    try:
        html = _get_html(url, timeout)
    except _NotReadable:
        return "This link isn't a readable article (PDF or other file).\n\nPress 'b' to open it in your browser."
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 451):
            return ("This source blocks in-terminal reading (paywall or bot protection).\n\n"
                    "Press 'b' to open it in your browser.")
        return f"(couldn't load: HTTP {e.code} — press 'b' to open in the browser)"
    except Exception as e:
        return f"(couldn't load: {e} — press 'b' to open in the browser)"
    return _extract(html)
