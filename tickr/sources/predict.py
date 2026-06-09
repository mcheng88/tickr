from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass

from rich.console import Group
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
class Outcome:
    name: str
    pct: float  # probability, 0..100
    delta: float | None  # 24h change in points


@dataclass
class Market:
    label: str  # event title
    pct: float  # favorite outcome probability
    delta: float | None  # favorite's 24h change
    outcomes: list[Outcome]  # all outcomes, sorted most-likely first
    volume24: float
    end: str  # event end date (ISO)


def _market(event: dict) -> Market | None:
    """Reduce an event to its favorite outcome + the full sorted outcome list."""
    outs: list[Outcome] = []
    for m in event.get("markets", []):
        try:
            if json.loads(m.get("outcomes") or "[]") != ["Yes", "No"]:
                continue
            p = float(json.loads(m.get("outcomePrices") or "[]")[0])
        except (ValueError, TypeError, IndexError, json.JSONDecodeError):
            continue
        d = m.get("oneDayPriceChange")
        name = (m.get("groupItemTitle") or m.get("question") or "").strip()
        outs.append(Outcome(name, p * 100, d * 100 if isinstance(d, (int, float)) else None))
    if not outs:
        return None
    outs.sort(key=lambda o: o.pct, reverse=True)
    fav = outs[0]
    return Market(event.get("title", "").strip(), fav.pct, fav.delta, outs,
                  event.get("volume24hr") or 0, str(event.get("endDate") or "")[:10])


class PredictSource(Source):
    """Live Polymarket odds on topical events — one line each: question + the
    favorite's probability + its 24h move."""

    title = "PREDICT"
    interactive = True

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
            m = _market(e)
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

    @staticmethod
    def _delta_text(delta: float | None, width: int = 4) -> Text:
        if delta is None or abs(delta) < 0.5:
            return Text(f"{'·':>{width}}", style="dim")
        up = delta >= 0
        return Text(f"{('▲' if up else '▼') + str(round(abs(delta))):>{width}}",
                    style="green" if up else "red")

    def list_rows(self, data: list[Market], width: int) -> list[tuple[Text, str]]:
        pct_w, d_w = 5, 4
        label_w = max(6, width - pct_w - d_w - 2)
        rows: list[tuple[Text, str]] = []
        for i, m in enumerate(data or []):
            label = (m.label[: label_w - 1] + "…") if len(m.label) > label_w else m.label.ljust(label_w)
            t = Text(label)
            t.append(f"{m.pct:>{pct_w - 1}.0f}%", style="bold cyan")
            t.append(" ")
            t.append_text(self._delta_text(m.delta, d_w))
            rows.append((t, str(i)))
        return rows

    def detail(self, key: str, data: list[Market]) -> Group:
        try:
            m = (data or [])[int(key)]
        except (ValueError, IndexError):
            return Group(Text("(no data)", style="dim"))
        t = Table.grid(padding=(0, 2))
        t.add_column(no_wrap=True, max_width=34)
        t.add_column(justify="right", no_wrap=True)
        t.add_column(justify="right", no_wrap=True)
        shown = [o for o in m.outcomes if o.pct >= 0.5][:12] or m.outcomes[:3]
        for o in shown:
            t.add_row(Text(o.name or "—"), Text(f"{o.pct:.0f}%", style="bold cyan"),
                      self._delta_text(o.delta))
        foot = Text(f"24h vol ${m.volume24/1e6:.1f}M", style="grey58")
        if m.end:
            foot.append(f"   ends {m.end}", style="grey58")
        return Group(Text(m.label, style="bold cyan"), Text(""), t, Text(""), foot)

    def render(self, data: list[Market]) -> Table:  # fallback (non-interactive mode)
        t = Table.grid(padding=(0, 1), expand=True)
        t.add_column(justify="left", no_wrap=True, ratio=1)
        t.add_column(justify="right", no_wrap=True)
        for m in data or []:
            t.add_row(Text(m.label, overflow="ellipsis", no_wrap=True),
                      Text(f"{m.pct:.0f}%", style="bold cyan"))
        return t
