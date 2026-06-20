from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime

from rich.console import Group
from rich.table import Table
from rich.text import Text

from .base import Source

# Three free, no-key feeds of "things that move" in the world. Each is fetched
# on its own internal cadence (see the intervals below) so the one ambient panel
# stays cheap and polite to every upstream — the ISS races (refetched every
# cycle), quakes trickle, and launches are essentially fixed until liftoff.
#
#   • Launch Library 2 (The Space Devs) — next rocket launch + liftoff time.
#       Anonymous clients are throttled to ~15 req/hour, so we cache hard.
#   • USGS earthquake GeoJSON — recent quakes, M2.5+ in the last 24h.
#   • wheretheiss.at — current ISS sub-point (lat/lon), altitude, speed.
#
# If any one feed fails we keep its last good value; the panel never goes dark
# just because one upstream hiccupped.
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_LAUNCH = "https://ll.thespacedevs.com/2.2.0/launch/upcoming/?limit=1&hide_recent_previous=true"
_QUAKES = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson"
_ISS = "https://api.wheretheiss.at/v1/satellites/25544"

# Per-feed refetch intervals (seconds). The source's own ``refresh_seconds``
# (default 30) is how often ``fetch()`` is called; these gate the actual network
# hits inside it so a fast ISS tick doesn't hammer the slow feeds.
_LAUNCH_EVERY = 900  # 15 min → 4 req/hr, comfortably under LL2's anon limit
_QUAKES_EVERY = 180  # 3 min
_ISS_EVERY = 0       # every cycle — the ISS sub-point is the fast-moving bit


@dataclass
class Launch:
    name: str
    provider: str
    net: float  # liftoff time (unix seconds), "no earlier than"


@dataclass
class Quake:
    mag: float
    place: str
    time: float  # unix seconds


@dataclass
class ISS:
    lat: float
    lon: float
    alt: float  # km
    vel: float  # km/h
    visibility: str


@dataclass
class Oddities:
    launch: Launch | None = None
    quakes: list[Quake] = field(default_factory=list)
    iss: ISS | None = None


def _get_json(url: str, timeout: float = 10) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _parse_net(net: str) -> float:
    # LL2 stamps are ISO-8601 with a trailing Z; fromisoformat handles the
    # offset form on 3.11+, so normalise Z → +00:00 first.
    return datetime.fromisoformat(net.replace("Z", "+00:00")).timestamp()


def _countdown(secs: float) -> str:
    if secs <= 0:
        return "T-0  liftoff imminent"
    s = int(secs)
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return f"T- {d}d {h:02d}:{m:02d}:{s:02d}"
    return f"T- {h:02d}:{m:02d}:{s:02d}"


def _ago(secs: float) -> str:
    s = int(max(secs, 0))
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h"
    return f"{s // 86400}d"


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


class OdditiesSource(Source):
    """Ambient-delight panel: next rocket launch + live countdown, recent
    earthquakes, and where the ISS is right now. Three free, no-key feeds, each
    cached on its own cadence so the panel is cheap and never fully dark."""

    title = "ODDITIES"

    def __init__(self, config):
        super().__init__(config)
        self._min_mag = float(self.config.get("min_mag", 2.5))
        self._rows = int(self.config.get("quake_rows", 4))
        self._place_width = int(self.config.get("place_width", 26))
        self._data = Oddities()
        self._launch_at = 0.0
        self._quakes_at = 0.0
        self._iss_at = 0.0

    def fetch(self) -> Oddities:
        now = time.monotonic()
        # Each feed is wrapped so one failure leaves the others (and the last
        # good value) intact — fetch() itself never raises.
        if self._data.launch is None or now - self._launch_at >= _LAUNCH_EVERY:
            try:
                self._data.launch = self._fetch_launch()
                self._launch_at = now
            except Exception:
                pass
        if not self._data.quakes or now - self._quakes_at >= _QUAKES_EVERY:
            try:
                self._data.quakes = self._fetch_quakes()
                self._quakes_at = now
            except Exception:
                pass
        if self._data.iss is None or now - self._iss_at >= _ISS_EVERY:
            try:
                self._data.iss = self._fetch_iss()
                self._iss_at = now
            except Exception:
                pass
        return self._data

    def _fetch_launch(self) -> Launch | None:
        results = _get_json(_LAUNCH).get("results", [])
        if not results:
            return None
        r = results[0]
        provider = (r.get("launch_service_provider") or {}).get("name", "")
        return Launch(name=r.get("name", "—"), provider=provider, net=_parse_net(r["net"]))

    def _fetch_quakes(self) -> list[Quake]:
        feats = _get_json(_QUAKES).get("features", [])
        quakes: list[Quake] = []
        for f in feats:
            p = f.get("properties", {})
            mag = p.get("mag")
            if mag is None or mag < self._min_mag:
                continue
            quakes.append(Quake(mag=float(mag), place=p.get("place") or "—", time=(p.get("time") or 0) / 1000))
        quakes.sort(key=lambda q: q.time, reverse=True)  # most recent first
        return quakes[: self._rows]

    def _fetch_iss(self) -> ISS:
        d = _get_json(_ISS)
        return ISS(
            lat=float(d["latitude"]),
            lon=float(d["longitude"]),
            alt=float(d.get("altitude", 0)),
            vel=float(d.get("velocity", 0)),
            visibility=str(d.get("visibility", "")),
        )

    def render(self, data: Oddities) -> Group:
        data = data or Oddities()
        now = time.time()
        blocks: list = []

        # --- next launch + live countdown ---
        if data.launch:
            blocks.append(Text(f"🚀 {data.launch.name}", style="bold", no_wrap=True, overflow="ellipsis"))
            line = Text(f"   {_countdown(data.launch.net - now)}", style="cyan")
            if data.launch.provider:
                line.append(f"  {data.launch.provider}", style="dim")
            blocks.append(line)
        else:
            blocks.append(Text("🚀 launch  —", style="dim"))
        blocks.append(Text(""))

        # --- ISS sub-point right now ---
        if data.iss:
            i = data.iss
            ns = "N" if i.lat >= 0 else "S"
            ew = "E" if i.lon >= 0 else "W"
            blocks.append(Text(f"🛰  ISS  {abs(i.lat):.1f}°{ns}  {abs(i.lon):.1f}°{ew}", style="bold"))
            vis = "sunlit" if i.visibility == "daylight" else "eclipsed" if i.visibility else ""
            sub = f"   {i.alt:,.0f} km · {i.vel:,.0f} km/h"
            if vis:
                sub += f" · {vis}"
            blocks.append(Text(sub, style="dim"))
        else:
            blocks.append(Text("🛰  ISS  —", style="dim"))
        blocks.append(Text(""))

        # --- recent quakes ---
        blocks.append(Text(f"🌎 quakes  M{self._min_mag:g}+ · 24h", style="bold"))
        if data.quakes:
            t = Table.grid(padding=(0, 1), expand=False)
            t.add_column(justify="left", no_wrap=True)   # magnitude
            t.add_column(justify="left", no_wrap=True)    # place
            t.add_column(justify="right", no_wrap=True)   # age
            for q in data.quakes:
                color = "red" if q.mag >= 5 else "yellow" if q.mag >= 4 else "white"
                t.add_row(
                    Text(f"M{q.mag:.1f}", style=color),
                    Text(_clip(q.place, self._place_width)),
                    Text(_ago(now - q.time), style="dim"),
                )
            blocks.append(t)
        else:
            blocks.append(Text("   (none)", style="dim"))

        return Group(*blocks)
