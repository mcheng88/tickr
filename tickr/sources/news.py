from __future__ import annotations

import time
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

from rich.console import Group
from rich.text import Text

from .base import Source

# Google News RSS — free, no key. Default is the top-stories firehose; set a
# `query` in config for a topical firehose instead.
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_TOP = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
_SEARCH = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def _parse_feed(url: str) -> list[tuple[str, str, float]]:
    """Parse one RSS feed into (title, link, published_ts) with real article links."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=8) as r:
        root = ET.fromstring(r.read())
    out: list[tuple[str, str, float]] = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        link = (item.findtext("link") or "").strip()
        ts = 0.0
        pub = item.findtext("pubDate")
        if pub:
            try:
                ts = parsedate_to_datetime(pub).timestamp()
            except (TypeError, ValueError):
                ts = 0.0
        out.append((title, link, ts))
    return out


def _fetch_items(url: str, count: int, exclude: list[str]) -> list[tuple[str, str]]:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=8) as r:
        root = ET.fromstring(r.read())
    items: list[tuple[str, str]] = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        src = item.find("source")
        if src is not None and src.text and title.endswith(f" - {src.text}"):
            title = title[: -len(f" - {src.text}")].strip()  # drop " - Publisher"
        if not title:
            continue
        low = title.lower()
        if any(x in low for x in exclude):  # drop headlines matching a blocked term
            continue
        items.append((title, (item.findtext("link") or "").strip()))
        if len(items) >= count:
            break
    return items


class NewsSource(Source):
    """A vertical headline feed. fetch() pulls the firehose infrequently;
    render() shows `rows` headlines and advances by one every `scroll_seconds`,
    so the feed gently rolls without a refetch — readable, not a marquee."""

    title = "NEWS"

    def fetch(self) -> list[tuple[str, str]]:
        from ..catalog import feeds_for

        exclude = [str(x).lower() for x in self.config.get("exclude", [])]
        count = int(self.config.get("count", 40))
        # `topics` names expand to curated catalog feeds and merge with any
        # explicit `feeds`, so config can say topics = ["business", "tech"].
        feeds = list(self.config.get("feeds") or [])
        feeds += [u for u in feeds_for(self.config.get("topics", [])) if u not in feeds]
        if feeds:
            # Direct RSS feeds: real article links (cmd-click + in-term reader work).
            items: list[tuple[str, str, float]] = []
            for url in feeds:
                try:
                    items.extend(_parse_feed(url))
                except Exception:
                    continue
            seen: set[str] = set()
            merged: list[tuple[str, str]] = []
            for title, link, _ in sorted(items, key=lambda x: x[2], reverse=True):
                low = title.lower()
                if low in seen or any(x in low for x in exclude):
                    continue
                seen.add(low)
                merged.append((title, link))
            return merged[:count]
        # Fallback: Google News firehose (links are interstitials — open in browser only).
        q = self.config.get("query")
        url = _SEARCH.format(q=urllib.parse.quote(q)) if q else _TOP
        return _fetch_items(url, count, exclude)

    def render(self, data: list[tuple[str, str]]) -> Group:
        if not data:
            return Group(Text("(no headlines)", style="dim"))
        rows = int(self.config.get("rows", 8))
        interval = float(self.config.get("scroll_seconds", 4))

        n = len(data)
        start = int(time.monotonic() / interval) % n
        lines = []
        for i in range(min(rows, n)):
            title, link = data[(start + i) % n]
            # `link <url>` makes the line a terminal hyperlink — cmd-click opens it
            # in kitty. Clips to its column width via ellipsis overflow.
            style = f"white link {link}" if link else "white"
            lines.append(Text(f"• {title}", style=style, no_wrap=True, overflow="ellipsis"))
        return Group(*lines)
