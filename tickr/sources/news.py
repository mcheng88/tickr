from __future__ import annotations

import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

from rich.console import Group
from rich.text import Text

from .base import Source
from ..textnorm import normalize

# Google News RSS — free, no key. Default is the top-stories firehose; set a
# `query` in config for a topical firehose instead.
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_TOP = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
_SEARCH = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


# Right-hand host labels that are TLDs / country codes, not the brand.
_TLD = {"com", "org", "net", "co", "uk", "us", "au", "nz", "gov", "ac", "io", "edu"}


def _source_from_host(url: str) -> str:
    """Fallback source label from a feed URL's host (only used when a feed omits a
    channel title), e.g. npr.org → NPR, techcrunch.com → Techcrunch."""
    host = urlsplit(url).hostname or ""
    parts = [p for p in host.split(".") if p not in ("www", "feeds", "rss", "feed")]
    while len(parts) > 1 and parts[-1] in _TLD:  # peel TLD/ccTLD labels off the right
        parts.pop()
    if not parts:
        return ""
    name = parts[-1]
    return name.upper() if len(name) <= 4 else name.capitalize()


def _parse_feed(url: str) -> list[tuple[str, str, float, str]]:
    """Parse one RSS feed into (title, link, published_ts, source) with real
    article links. `source` is the feed's channel title (falling back to the host)."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=8) as r:
        root = ET.fromstring(r.read())
    source = normalize((root.findtext(".//channel/title") or "").strip()) or _source_from_host(url)
    out: list[tuple[str, str, float, str]] = []
    for item in root.findall(".//item"):
        title = normalize((item.findtext("title") or "").strip())
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
        out.append((title, link, ts, source))
    return out


def _fetch_items(url: str, count: int, exclude: list[str]) -> list[tuple[str, str, str]]:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=8) as r:
        root = ET.fromstring(r.read())
    items: list[tuple[str, str, str]] = []
    for item in root.findall(".//item"):
        title = normalize((item.findtext("title") or "").strip())
        src = item.find("source")
        source = normalize((src.text or "").strip()) if src is not None and src.text else ""
        if source and title.endswith(f" - {source}"):
            title = title[: -len(f" - {source}")].strip()  # drop " - Publisher"
        if not title:
            continue
        low = title.lower()
        if any(x in low for x in exclude):  # drop headlines matching a blocked term
            continue
        items.append((title, (item.findtext("link") or "").strip(), source))
        if len(items) >= count:
            break
    return items


class NewsSource(Source):
    """A vertical headline feed. fetch() pulls the firehose infrequently;
    render() shows `rows` headlines and advances by one every `scroll_seconds`,
    so the feed gently rolls without a refetch — readable, not a marquee."""

    title = "NEWS"

    def fetch(self) -> list[tuple[str, str, str]]:
        from ..catalog import feeds_for

        exclude = [str(x).lower() for x in self.config.get("exclude", [])]
        count = int(self.config.get("count", 40))
        # `topics` names expand to curated catalog feeds and merge with any
        # explicit `feeds`, so config can say topics = ["business", "tech"].
        feeds = list(self.config.get("feeds") or [])
        feeds += [u for u in feeds_for(self.config.get("topics", [])) if u not in feeds]
        if feeds:
            # Direct RSS feeds: real article links (cmd-click + in-term reader work).
            # Fetch all feeds concurrently — network-bound, so a dozen feeds finish
            # in about the time of the slowest one instead of the sum (~2s → ~0.3s).
            items: list[tuple[str, str, float, str]] = []
            with ThreadPoolExecutor(max_workers=min(12, len(feeds))) as pool:
                for result in pool.map(_safe_parse, feeds):
                    items.extend(result)
            seen: set[str] = set()
            merged: list[tuple[str, str, str]] = []
            for title, link, _ts, source in sorted(items, key=lambda x: x[2], reverse=True):
                low = title.lower()
                if low in seen or any(x in low for x in exclude):
                    continue
                seen.add(low)
                merged.append((title, link, source))
            return merged[:count]
        # Fallback: Google News firehose (links are interstitials — open in browser only).
        q = self.config.get("query")
        url = _SEARCH.format(q=urllib.parse.quote(q)) if q else _TOP
        return _fetch_items(url, count, exclude)

    def render(self, data: list[tuple[str, str, str]]) -> Group:
        if not data:
            return Group(Text("(no headlines)", style="dim"))
        rows = int(self.config.get("rows", 8))
        interval = float(self.config.get("scroll_seconds", 4))
        show_source = bool(self.config.get("show_source", False))

        n = len(data)
        start = int(time.monotonic() / interval) % n
        lines = []
        for i in range(min(rows, n)):
            title, link, source = data[(start + i) % n]
            line = Text(f"• {title}", no_wrap=True, overflow="ellipsis")
            # `link <url>` makes the line a terminal hyperlink — cmd-click opens it
            # in kitty. Clips to its column width via ellipsis overflow.
            line.stylize(f"white link {link}" if link else "white")
            if show_source and source:
                line.append(f"  {source}", style="dim")
            lines.append(line)
        return Group(*lines)


def _safe_parse(url: str) -> list[tuple[str, str, float, str]]:
    """_parse_feed that never raises — a dead feed just contributes nothing."""
    try:
        return _parse_feed(url)
    except Exception:
        return []
