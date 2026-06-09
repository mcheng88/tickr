from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

from rich.table import Table
from rich.text import Text

from .base import Source

# Polymarket Gamma API — public, no key. The /events endpoint honors tag_slug
# (the /markets endpoint silently ignores it and leaks sports), so we query
# events by tag, ordered by 24h volume ("things that move"), and reduce each
# event to its favorite outcome: one scannable line per event.
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_EVENTS = "https://gamma-api.polymarket.com/events"
_DEFAULT_TAGS = ["politics"]  # Fed / elections / geopolitics. (No crypto.)


@dataclass
class Market:
    label: str
    pct: float  # favorite outcome probability, 0..100
    delta: float | None  # 24h change in the favorite's probability, in points


def _favorite(event: dict) -> Market | None:
    """Reduce an event to its single most-likely Yes/No outcome."""
    best: tuple[float, float | None] | None = None
    for m in event.get("markets", []):
        try:
            if json.loads(m.get("outcomes") or "[]") != ["Yes", "No"]:
                continue
            p = float(json.loads(m.get("outcomePrices") or "[]")[0])
        except (ValueError, TypeError, IndexError, json.JSONDecodeError):
            continue
        if best is None or p > best[0]:
            d = m.get("oneDayPriceChange")
            best = (p, d * 100 if isinstance(d, (int, float)) else None)
    if best is None:
        return None
    return Market(event.get("title", "").strip(), best[0] * 100, best[1])


class PredictSource(Source):
    """Live Polymarket odds on topical events — one line each: question + the
    favorite's probability + its 24h move."""

    title = "PREDICT"

    def _events(self, tag: str) -> list[dict]:
        q = urllib.parse.urlencode(
            {"closed": "false", "active": "true", "order": "volume24hr",
             "ascending": "false", "limit": 40, "tag_slug": tag}
        )
        req = urllib.request.Request(f"{_EVENTS}?{q}", headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    def fetch(self) -> list[Market]:
        tags = self.config.get("tags") or _DEFAULT_TAGS
        count = int(self.config.get("count", 12))
        exclude = [str(x).lower() for x in self.config.get("exclude", [])]

        events: dict[str, dict] = {}
        for tag in tags:
            try:
                for e in self._events(str(tag)):
                    events.setdefault(str(e.get("id")), e)
            except Exception:
                continue
        ranked = sorted(events.values(), key=lambda e: e.get("volume24hr") or 0, reverse=True)

        rows: list[Market] = []
        for e in ranked:
            m = _favorite(e)
            if m is None or not m.label:
                continue
            if m.pct >= 97:  # drop near-settled markets (low info)
                continue
            if any(x in m.label.lower() for x in exclude):
                continue
            rows.append(m)
            if len(rows) >= count:
                break
        return rows

    def render(self, data: list[Market]) -> Table:
        t = Table.grid(padding=(0, 1), expand=True)
        t.add_column("q", justify="left", no_wrap=True, ratio=1)
        t.add_column("pct", justify="right", no_wrap=True)
        t.add_column("d", justify="right", no_wrap=True)
        for m in data or []:
            pct = Text(f"{m.pct:.0f}%", style="bold cyan")
            if m.delta is None or abs(m.delta) < 0.5:
                d = Text("·", style="dim")
            else:
                up = m.delta >= 0
                d = Text(f"{'▲' if up else '▼'}{abs(m.delta):.0f}", style="green" if up else "red")
            t.add_row(Text(m.label, overflow="ellipsis", no_wrap=True), pct, d)
        if not data:
            t.add_row(Text("(no markets)", style="dim"), Text(""), Text(""))
        return t
