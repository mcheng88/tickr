from __future__ import annotations

import re
import urllib.error
import urllib.request
from html.parser import HTMLParser

from .textnorm import normalize

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_SKIP = {"script", "style", "nav", "aside", "figure", "footer", "header",
         "form", "noscript", "svg", "button"}
# Semantic content containers. When a page has one, we trust only the text
# inside it — that reliably excludes nav/promo chrome, which lets us safely
# pull richer structure (headings, list items) that would otherwise drag in
# menus. Pages without a container fall back to paragraphs-only (see _extract).
_MAIN = {"article", "main"}
_SAFE = {"p", "blockquote"}            # trustworthy even outside a container
_EXTRA = {"li", "h1", "h2", "h3", "h4"}  # only trusted inside a container
_BLOCK = _SAFE | _EXTRA


class _Article(HTMLParser):
    """Readable-text extractor. Collects text block-by-block, tagging each block
    with (a) whether it sits inside an <article>/<main> container and (b) whether
    it's a paragraph-type ("safe") block. ``_extract`` uses those tags to pick the
    best subset: the article body when present, else paragraphs-only. Chrome
    (script/nav/footer/…) is dropped outright."""

    def __init__(self) -> None:
        super().__init__()
        # (in_main, is_safe, text) per captured block.
        self.blocks: list[tuple[bool, bool, str]] = []
        self._skip = 0
        self._main = 0
        self._stack: list[str] = []  # open block tags (they can nest, e.g. p in li)
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP:
            self._skip += 1
        elif tag in _MAIN:
            self._main += 1
        elif tag in _BLOCK:
            self._flush()  # text before a nested block becomes its own block
            self._stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self._skip:
            self._skip -= 1
        elif tag in _MAIN and self._main:
            self._main -= 1
        elif tag in _BLOCK and self._stack:
            self._flush()
            for k in range(len(self._stack) - 1, -1, -1):  # pop innermost match
                if self._stack[k] == tag:
                    del self._stack[k]
                    break

    def handle_data(self, data: str) -> None:
        if self._stack and not self._skip:
            text = data.strip()
            if text:
                self._buf.append(text)

    def _flush(self) -> None:
        if self._buf and self._stack:
            text = " ".join(self._buf).strip()
            if text:
                self.blocks.append((self._main > 0, self._stack[-1] in _SAFE, text))
        self._buf = []


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
    # Some servers mislabel (or omit) the content-type on binary files; sniff the
    # magic bytes so a PDF served as text/html still routes to the browser note.
    if raw[:5] == b"%PDF-":
        raise _NotReadable("application/pdf")
    return raw.decode("utf-8", "replace")


# Below this many characters of body text we assume extraction hit a paywall /
# JS-rendered stub and nudge the reader toward the full page in a browser.
_THIN = 280


def _extract(html: str) -> str:
    parser = _Article()
    try:
        parser.feed(html)
    except Exception:
        pass  # malformed markup — keep whatever blocks we captured before the fault
    parser._flush()
    blocks = parser.blocks
    in_main = [t for (m, _s, t) in blocks if m]
    if in_main:
        parts = in_main  # trust the semantic article body wholesale
    else:
        parts = [t for (_m, safe, t) in blocks if safe]  # no container → paragraphs only
    text = normalize("\n\n".join(parts).strip())
    while "\n\n\n" in text:  # collapse runs of blank lines
        text = text.replace("\n\n\n", "\n\n")
    if not text:
        return "(couldn't extract readable text -- try opening in the browser with 'b')"
    if len(text) < _THIN:
        text += ("\n\n-- This looks truncated (paywall or a page that renders its "
                 "body in JavaScript). Press 'b' to open the full article in your browser.")
    return text


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
