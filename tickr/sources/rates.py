from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from datetime import datetime
from xml.etree import ElementTree as ET

from rich.table import Table
from rich.text import Text

from .base import Source

# US Treasury daily par yield curve — free, no API key. The XML feed returns
# every business day of a given year (chronological), so the last two entries
# give us today's curve plus the prior session for a day-over-day move. This is
# the full bill + note/bond ladder Yahoo can't do: Yahoo only exposes the
# 13-week bill (^IRX) and has no 26-week, which is the tenor Matt actually wants.
#
# If Treasury ever changes this feed, swapping providers is a self-contained
# change to this file — nothing else in tickr depends on it.
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_FEED = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
)

# Ordered full curve: (display label, Treasury XML field). Bills (≤52wk) are
# labelled in weeks to match how the desk quotes them; notes/bonds in years.
_CURVE: list[tuple[str, str]] = [
    ("4wk", "BC_1MONTH"),
    ("8wk", "BC_2MONTH"),
    ("13wk", "BC_3MONTH"),
    ("17wk", "BC_4MONTH"),
    ("26wk", "BC_6MONTH"),
    ("52wk", "BC_1YEAR"),
    ("2Y", "BC_2YEAR"),
    ("3Y", "BC_3YEAR"),
    ("5Y", "BC_5YEAR"),
    ("7Y", "BC_7YEAR"),
    ("10Y", "BC_10YEAR"),
    ("20Y", "BC_20YEAR"),
    ("30Y", "BC_30YEAR"),
]

# Curated subset shown in the always-on panel; the detail popup shows _CURVE
# in full. 26wk is Matt's priority bill, so it's emphasised in render(). Kept
# compact by default so the panel doesn't dominate its column — override per
# config with `[rates] ladder = ["4wk", "26wk", ...]`.
_LADDER_DEFAULT = ["4wk", "13wk", "26wk", "52wk", "2Y", "10Y", "30Y"]
_HERO = "26wk"


@dataclass
class Tenor:
    label: str
    yld: float | None  # par yield, percent
    bp: float | None   # day-over-day move in basis points (None if no prior day)


@dataclass
class Curve:
    date: str          # latest curve date, e.g. "Jun 18"
    prior_date: str    # comparison date, e.g. "Jun 17"
    tenors: list[Tenor]  # full curve, in _CURVE order


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _rows(xml: bytes) -> list[dict[str, str]]:
    """Each daily entry's <properties> flattened to {FIELD: text}, chronological."""
    root = ET.fromstring(xml)
    rows: list[dict[str, str]] = []
    for props in root.iter():
        if _local(props.tag) != "properties":
            continue
        rows.append({_local(c.tag): (c.text or "").strip() for c in props})
    return rows


def _num(row: dict[str, str], field: str) -> float | None:
    raw = row.get(field, "")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _date(row: dict[str, str]) -> str:
    raw = row.get("NEW_DATE", "")
    try:
        return datetime.fromisoformat(raw.replace("Z", "")).strftime("%b %d")
    except ValueError:
        return raw[:10]


class RatesSource(Source):
    title = "RATES"

    def _fetch_year(self, year: int) -> list[dict[str, str]]:
        req = urllib.request.Request(_FEED.format(year=year), headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=10) as r:
            return _rows(r.read())

    def fetch(self) -> Curve:
        year = datetime.now().year
        rows = self._fetch_year(year)
        if len(rows) < 2:  # early January: reach back for the prior session
            rows = self._fetch_year(year - 1) + rows
        if not rows:
            raise RuntimeError("no Treasury yield data returned")
        latest = rows[-1]
        prior = rows[-2] if len(rows) >= 2 else None
        tenors: list[Tenor] = []
        for label, field in _CURVE:
            cur = _num(latest, field)
            prev = _num(prior, field) if prior else None
            bp = round((cur - prev) * 100) if (cur is not None and prev is not None) else None
            tenors.append(Tenor(label, cur, bp))
        return Curve(
            date=_date(latest),
            prior_date=_date(prior) if prior else "",
            tenors=tenors,
        )

    def status(self) -> str:
        return ""

    def _move(self, bp: float | None) -> Text:
        if bp is None:
            return Text("—", style="dim")
        if bp == 0:
            return Text("·0bp", style="dim")
        up = bp > 0
        arrow = "▲" if up else "▼"
        return Text(f"{arrow}{abs(int(bp))}bp", style="green" if up else "red")

    def _table(self, tenors: list[Tenor]) -> Table:
        t = Table.grid(padding=(0, 2), expand=False)
        t.add_column("tenor", justify="left", no_wrap=True)
        t.add_column("yield", justify="right", no_wrap=True)
        t.add_column("move", justify="right", no_wrap=True)
        for ten in tenors:
            hero = ten.label == _HERO
            label = Text(ten.label, style="bold yellow" if hero else "bold")
            if ten.yld is None:
                t.add_row(label, Text("—", style="dim"), Text("·", style="dim"))
                continue
            yld_style = "bold yellow" if hero else ""
            t.add_row(label, Text(f"{ten.yld:.2f}%", style=yld_style), self._move(ten.bp))
        return t

    def render(self, data: Curve) -> Table:
        if data is None:
            return Table.grid()
        ladder = set(self.config.get("ladder", _LADDER_DEFAULT))
        return self._table([ten for ten in data.tenors if ten.label in ladder])

    def render_detail(self, data: Curve) -> Table:
        """Full curve — every tenor — for the interactive detail popup."""
        return self._table(data.tenors)

    def render_curve(self, data: Curve, width: int = 40, height: int = 8) -> Text:
        """An ASCII line chart of the par yield curve: x = tenor (left→right,
        short→long), y = yield. A continuous interpolated line with a ``●`` at
        each real tenor, plus a small yield gutter. Pure-text, no deps."""
        pts = [(i, t.yld) for i, t in enumerate(data.tenors) if t.yld is not None]
        if len(pts) < 2:
            return Text("(not enough data to plot)", style="dim")
        n = len(data.tenors)
        ys = [y for _, y in pts]
        lo, hi = min(ys), max(ys)
        if hi - lo < 1e-9:
            hi = lo + 0.01  # flat curve → avoid divide-by-zero
        gutter = 6  # width of the "x.xx%" y-axis labels
        W = max(16, width - gutter)
        H = max(4, height)

        def interp(fi: float) -> float:
            """Piecewise-linear yield at fractional tenor index ``fi``."""
            for (a, ya), (b, yb) in zip(pts, pts[1:]):
                if a <= fi <= b:
                    return ya + (yb - ya) * (fi - a) / (b - a) if b != a else ya
            return pts[0][1] if fi < pts[0][0] else pts[-1][1]

        def row_of(y: float) -> int:
            return H - 1 - round((y - lo) / (hi - lo) * (H - 1))

        grid = [[" "] * W for _ in range(H)]
        for x in range(W):
            fi = x * (n - 1) / (W - 1)
            grid[row_of(interp(fi))][x] = "·"
        for i, y in pts:  # overlay real tenors on top of the interpolated line
            grid[row_of(y)][round(i * (W - 1) / (n - 1))] = "●"

        out = Text()
        for r, line in enumerate(grid):
            if r == 0:
                label = f"{hi:.2f}%"
            elif r == H - 1:
                label = f"{lo:.2f}%"
            else:
                label = ""
            out.append(f"{label:>{gutter - 1}} ", style="dim")
            for ch in line:
                out.append(ch, style="bold green" if ch == "●" else ("green" if ch == "·" else " "))
            out.append("\n")
        # x-axis: first / middle / last tenor labels under the plot
        first, mid, last = data.tenors[0].label, data.tenors[n // 2].label, data.tenors[-1].label
        line = [" "] * W
        for label, pos in ((first, 0), (mid, (W - len(mid)) // 2), (last, W - len(last))):
            for k, c in enumerate(label):
                if 0 <= pos + k < W:
                    line[pos + k] = c
        out.append(" " * gutter, style="dim")
        out.append("".join(line), style="dim")
        return out
