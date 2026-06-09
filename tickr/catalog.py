from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path

# The curated preset catalog ships next to this module. config.toml references
# entries by name (news `topics`, stocks `sets`); the sources expand them here.
_CATALOG = Path(__file__).resolve().parent / "presets.toml"


@lru_cache(maxsize=1)
def _load() -> dict:
    try:
        with open(_CATALOG, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


def feeds_for(topics: list[str]) -> list[str]:
    """Expand topic names (e.g. ["business", "tech"]) to RSS feed URLs, in order,
    de-duplicated. Unknown topic names are skipped."""
    cat = _load().get("feeds", {})
    urls: list[str] = []
    for name in topics:
        for url in cat.get(str(name), {}).get("urls", []):
            if url not in urls:
                urls.append(url)
    return urls


def tickers_for(sets: list[str]) -> list[str]:
    """Expand ticker-set names (e.g. ["indices", "gold"]) to Yahoo symbols, in
    order, de-duplicated. Unknown set names are skipped."""
    cat = _load().get("tickers", {})
    syms: list[str] = []
    for name in sets:
        for sym in cat.get(str(name), {}).get("symbols", []):
            if sym not in syms:
                syms.append(sym)
    return syms


def render_catalog(name: str | None = None) -> str:
    """Human-readable catalog listing for the `tickr catalog [name]` CLI."""
    cat = _load()
    feeds, tickers = cat.get("feeds", {}), cat.get("tickers", {})
    if name:
        if name in feeds:
            e = feeds[name]
            head = f"news topic '{name}' — {e.get('description', '')}".rstrip()
            return head + "\n" + "\n".join(f"  {u}" for u in e.get("urls", []))
        if name in tickers:
            e = tickers[name]
            head = f"ticker set '{name}' — {e.get('description', '')}".rstrip()
            return head + "\n  " + "  ".join(e.get("symbols", []))
        known = ", ".join([*feeds, *tickers]) or "(catalog empty)"
        return f"Unknown catalog entry '{name}'. Known: {known}"

    lines = ["News topics  (config: [news] topics = [...]):"]
    for k, e in feeds.items():
        lines.append(f"  {k:<12} {e.get('description', '')}  ({len(e.get('urls', []))} feeds)")
    lines.append("")
    lines.append("Ticker sets  (config: [stocks] sets = [...]):")
    for k, e in tickers.items():
        lines.append(f"  {k:<18} {e.get('description', '')}  ({len(e.get('symbols', []))} symbols)")
    lines.append("")
    lines.append("Detail: tickr catalog <name>")
    return "\n".join(lines)
