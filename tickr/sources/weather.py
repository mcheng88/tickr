from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from rich.console import Group
from rich.table import Table
from rich.text import Text

from .base import Source

# Open-Meteo (no key) for the forecast. Location: config pin > macOS Location
# Services (CoreLocation, Wi-Fi positioning) > ip-api IP guess — IP geolocation
# drifts to the VPN/CDN egress city (Cloudflare WARP once put us in Aurora, CO).
# ASCII art is the wttr.in aesthetic — a weather glyph drawn in characters,
# no image rendering needed.
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_GEO = "http://ip-api.com/json/?fields=city,regionName,lat,lon"
_REVGEO = "https://api.bigdatacloud.net/data/reverse-geocode-client"  # keyless
_FORECAST = "https://api.open-meteo.com/v1/forecast"

# WMO weather code -> condition group.
_GROUPS = {
    0: "clear", 1: "clear", 2: "partly", 3: "cloudy",
    45: "fog", 48: "fog",
    51: "rain", 53: "rain", 55: "rain", 56: "rain", 57: "rain",
    61: "rain", 63: "rain", 65: "rain", 66: "rain", 67: "rain",
    80: "rain", 81: "rain", 82: "rain",
    71: "snow", 73: "snow", 75: "snow", 77: "snow", 85: "snow", 86: "snow",
    95: "storm", 96: "storm", 99: "storm",
}
_LABEL = {"clear": "Clear", "partly": "Partly cloudy", "cloudy": "Cloudy",
          "fog": "Fog", "rain": "Rain", "snow": "Snow", "storm": "Thunderstorm"}
# Compact tag for the daily forecast rows.
_SHORT = {"clear": "clr", "partly": "part", "cloudy": "cld", "fog": "fog",
          "rain": "rain", "snow": "snow", "storm": "storm"}

# 5-line ASCII glyphs (wttr.in style). Style colors are applied at render time.
_ART = {
    "clear":  [r"   \   /   ", r"    .-.    ", r" --(   )-- ", r"    `-'    ", r"   /   \   "],
    "partly": [r"   \  /    ", r" _ /''.-.  ", r"   \_(   ).", r"   /(___(__)", r"           "],
    "cloudy": [r"           ", r"    .--.   ", r"  .(    ).  ", r" (___.__)__)", r"           "],
    "fog":    [r"           ", r"  _ - _ -  ", r"   _ - _   ", r"  _ - _ -  ", r"           "],
    "rain":   [r"    .-.    ", r"   (   ).  ", r"  (___(__) ", r"   ' ' ' ' ", r"  ' ' ' '  "],
    "snow":   [r"    .-.    ", r"   (   ).  ", r"  (___(__) ", r"   *  *  * ", r"  *  *  *  "],
    "storm":  [r"    .-.    ", r"   (   ).  ", r"  (___(__) ", r"   /_  /_  ", r"   /   /   "],
}
_ART_STYLE = {"clear": "yellow", "partly": "yellow", "cloudy": "grey70",
              "fog": "grey58", "rain": "blue", "snow": "bright_white", "storm": "magenta"}


def _group(code) -> str:
    return _GROUPS.get(int(code) if code is not None else -1, "cloudy")


@dataclass
class Weather:
    place: str
    temp: float | None
    feels: float | None
    code: int | None
    wind: float | None
    humidity: int | None
    unit: str = "F"
    days: list[tuple[str, int, float, float]] = field(default_factory=list)  # (day, code, hi, lo)


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _device_location() -> tuple[float, float, str] | None:
    """Ask macOS Location Services for the device position.

    Returns None off-macOS (pyobjc not installed), when the terminal app lacks
    Location Services permission, or on timeout — caller falls back to IP.
    CoreLocation is callback-based, so we poll while pumping this thread's
    runloop; works from worker threads as well as the main one.
    """
    try:
        import CoreLocation
        from Foundation import NSDate, NSRunLoop
    except ImportError:
        return None

    runloop = NSRunLoop.currentRunLoop()
    mgr = CoreLocation.CLLocationManager.alloc().init()
    mgr.requestWhenInUseAuthorization()
    mgr.startUpdatingLocation()
    loc = None
    deadline = time.time() + 5
    while time.time() < deadline:
        runloop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.2))
        loc = mgr.location()
        if loc is not None:
            break
    mgr.stopUpdatingLocation()
    if loc is None:
        return None
    coord = loc.coordinate()
    lat, lon = float(coord.latitude), float(coord.longitude)
    return lat, lon, _reverse_geocode(lat, lon)


def _reverse_geocode(lat: float, lon: float) -> str:
    """Coords -> "City, Region" label. CLGeocoder won't do: its completion
    handler fires on the main thread's runloop, which Textual's asyncio loop
    never pumps — so use a keyless HTTP service instead. Empty label on failure
    is fine; fetch() renders bare coords then."""
    try:
        q = urllib.parse.urlencode(
            {"latitude": lat, "longitude": lon, "localityLanguage": "en"})
        g = _get(f"{_REVGEO}?{q}")
        return ", ".join(
            x for x in (g.get("city") or g.get("locality"),
                        g.get("principalSubdivision")) if x)
    except Exception:
        return ""


_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _dow(iso_date: str) -> str:
    # iso_date is YYYY-MM-DD; derive weekday without importing datetime parsing cost.
    from datetime import date

    try:
        return _DOW[date.fromisoformat(iso_date).weekday()]
    except ValueError:
        return iso_date[5:]


class WeatherSource(Source):
    """Current conditions + a few-day forecast as ASCII art (wttr.in style)."""

    title = "WEATHER"

    def __init__(self, config):
        super().__init__(config)
        self._loc: tuple[float, float, str] | None = None

    def _location(self) -> tuple[float, float, str]:
        lat, lon = self.config.get("latitude"), self.config.get("longitude")
        if lat is not None and lon is not None:
            return float(lat), float(lon), str(self.config.get("label", "")).strip()
        if self._loc is None:  # resolve once, then cache: device GPS/Wi-Fi first
            self._loc = _device_location()
        if self._loc is None:  # last resort: IP geolocation (drifts under VPN)
            g = _get(_GEO)
            city = ", ".join(x for x in (g.get("city"), g.get("regionName")) if x)
            self._loc = (float(g["lat"]), float(g["lon"]), city)
        return self._loc

    def fetch(self) -> Weather:
        lat, lon, place = self._location()
        unit = str(self.config.get("unit", "fahrenheit")).lower()
        u = "fahrenheit" if unit.startswith("f") else "celsius"
        q = urllib.parse.urlencode({
            "latitude": lat, "longitude": lon,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min",
            "temperature_unit": u, "wind_speed_unit": "mph", "timezone": "auto", "forecast_days": 4,
        })
        d = _get(f"{_FORECAST}?{q}")
        cur, day = d.get("current", {}), d.get("daily", {})
        days = []
        for i, date_s in enumerate(day.get("time", [])):
            days.append((_dow(date_s), day["weather_code"][i],
                         day["temperature_2m_max"][i], day["temperature_2m_min"][i]))
        return Weather(
            place=place or f"{lat:.2f},{lon:.2f}",
            temp=cur.get("temperature_2m"), feels=cur.get("apparent_temperature"),
            code=cur.get("weather_code"), wind=cur.get("wind_speed_10m"),
            humidity=cur.get("relative_humidity_2m"),
            unit="F" if u == "fahrenheit" else "C", days=days,
        )

    def status(self) -> str:
        return ""

    def render(self, w: Weather) -> Group:
        grp = _group(w.code)
        # Some glyphs (cloudy/partly/fog) carry blank top/bottom rows for visual
        # centering; strip them so the panel doesn't waste vertical space.
        rows = list(_ART[grp])
        while rows and not rows[0].strip():
            rows.pop(0)
        while rows and not rows[-1].strip():
            rows.pop()
        art = Text("\n".join(rows), style=_ART_STYLE[grp])

        stats = Table.grid(padding=(0, 0))
        temp = f"{w.temp:.0f}°{w.unit}" if w.temp is not None else "—"
        stats.add_row(Text(temp, style="bold white"))
        stats.add_row(Text(_LABEL[grp], style=_ART_STYLE[grp]))
        if w.feels is not None:
            stats.add_row(Text(f"feels {w.feels:.0f}°", style="grey70"))
        bits = []
        if w.wind is not None:
            bits.append(f"wind {w.wind:.0f}mph")
        if w.humidity is not None:
            bits.append(f"hum {w.humidity:.0f}%")
        if bits:
            stats.add_row(Text("  ".join(bits), style="grey58"))

        head = Table.grid(padding=(0, 2))
        head.add_column(no_wrap=True)
        head.add_column(no_wrap=True)
        head.add_row(art, stats)

        forecast = Table.grid(padding=(0, 2), expand=False)
        for _ in range(len(w.days)):
            forecast.add_column(justify="left", no_wrap=True)
        if w.days:
            forecast.add_row(*[
                Text(f"{dow} {_SHORT[_group(code)]}\n{hi:.0f}/{lo:.0f}°",
                     style="grey70")
                for dow, code, hi, lo in w.days
            ])
        return Group(Text(w.place, style="bold cyan"), head, forecast)
