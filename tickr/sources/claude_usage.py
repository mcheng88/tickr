from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.console import Group
from rich.table import Table
from rich.text import Text

from .base import Source

# Per-model pricing, $/1M tokens (input, output). Matched by prefix so dated IDs
# like "claude-haiku-4-5-20251001" resolve. Cache tiers are multiples of input:
#   cache read = 0.1x · cache write 5m = 1.25x · cache write 1h = 2.0x
# (Authoritative as of 2026-06; refresh via the claude-api skill if models change.)
_PRICES = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
_CACHE_READ = 0.10
_CACHE_WRITE_5M = 1.25
_CACHE_WRITE_1H = 2.0

_BLOCK = 5 * 3600  # Claude's rolling 5-hour usage window
_WEEK = 7 * 24 * 3600  # rolling 7-day window (proxy for the weekly subscription cap)
_MTIME_WINDOW = 8 * 24 * 3600  # only parse transcripts touched in the last ~8 days
_DEFAULT_HOMES = ["~/.claude", "~/.claude-berry", "~/.claude-cheng"]


@dataclass
class AcctUsage:
    label: str
    today_cost: float
    week_cost: float
    block_tokens: int
    reset_in: float | None  # seconds until the active 5h block resets; None if none active

    @property
    def active(self) -> bool:
        return self.today_cost > 0 or self.week_cost > 0 or self.block_tokens > 0


def _price(model: str | None) -> tuple[float, float]:
    if model:
        for key, val in _PRICES.items():
            if model.startswith(key):
                return val
    return (5.0, 25.0)  # unknown model → assume Opus-tier


def _tally(model: str | None, u: dict) -> tuple[int, float]:
    """Return (total_tokens, api_equivalent_cost) for one usage record."""
    inp = u.get("input_tokens") or 0
    out = u.get("output_tokens") or 0
    cread = u.get("cache_read_input_tokens") or 0
    cc = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else {}
    c5m = cc.get("ephemeral_5m_input_tokens")
    c1h = cc.get("ephemeral_1h_input_tokens")
    if c5m is None and c1h is None:  # no breakdown → treat all writes as 5m
        c5m, c1h = (u.get("cache_creation_input_tokens") or 0), 0
    else:
        c5m, c1h = (c5m or 0), (c1h or 0)

    in_rate, out_rate = _price(model)
    cost = (
        inp * in_rate
        + out * out_rate
        + cread * in_rate * _CACHE_READ
        + c5m * in_rate * _CACHE_WRITE_5M
        + c1h * in_rate * _CACHE_WRITE_1H
    ) / 1_000_000
    return inp + out + cread + c5m + c1h, cost


def _parse_ts(s: str) -> float | None:
    try:
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError):
        return None


def _local_midnight(now: float) -> float:
    dt = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
    return dt.timestamp()


def _active_block_start(timestamps: list[float]) -> float | None:
    """Floor of the current 5-hour block, ccusage-style (new block on a >5h gap
    or once 5h elapses from the block's start)."""
    if not timestamps:
        return None
    ts = sorted(timestamps)
    start = (ts[0] // 3600) * 3600
    last = ts[0]
    for t in ts[1:]:
        if t - last >= _BLOCK or t - start >= _BLOCK:
            start = (t // 3600) * 3600
        last = t
    return start


def _label(home: Path) -> str:
    name = home.name
    if name.startswith(".claude-"):
        return name[len(".claude-"):]
    if name == ".claude":
        return "default"
    return name


def _scan(home: Path, mtime_cutoff: float) -> list[tuple[float, int, float]]:
    """Return (ts, tokens, cost) for usage records in recently-touched transcripts."""
    recs: list[tuple[float, int, float]] = []
    projects = home / "projects"
    if not projects.is_dir():
        return recs
    for fp in projects.rglob("*.jsonl"):
        try:
            if fp.stat().st_mtime < mtime_cutoff:
                continue
        except OSError:
            continue
        try:
            f = open(fp, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with f:
            for line in f:
                if '"output_tokens"' not in line:  # cheap skip for non-usage lines
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = d.get("message")
                if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
                    continue
                epoch = _parse_ts(d.get("timestamp"))
                if epoch is None:
                    continue
                tokens, cost = _tally(msg.get("model"), msg["usage"])
                recs.append((epoch, tokens, cost))
    return recs


class ClaudeUsageSource(Source):
    title = "CLAUDE USAGE"

    def fetch(self) -> list[AcctUsage]:
        homes = self.config.get("homes") or _DEFAULT_HOMES
        now = time.time()
        today_start = _local_midnight(now)
        week_start = now - _WEEK
        mtime_cutoff = now - _MTIME_WINDOW

        out: list[AcctUsage] = []
        for home in homes:
            path = Path(home).expanduser()
            recs = _scan(path, mtime_cutoff)
            today_cost = sum(r[2] for r in recs if r[0] >= today_start)
            week_cost = sum(r[2] for r in recs if r[0] >= week_start)

            block_start = _active_block_start([r[0] for r in recs])
            if block_start is not None and now < block_start + _BLOCK:
                block_tokens = sum(r[1] for r in recs if r[0] >= block_start)
                reset_in: float | None = block_start + _BLOCK - now
            else:
                block_tokens, reset_in = 0, None

            out.append(AcctUsage(_label(path), today_cost, week_cost, block_tokens, reset_in))
        return out

    def render(self, data: list[AcctUsage]) -> Group:
        # Hide idle accounts; if every account is idle, fall back to showing all.
        shown = [a for a in (data or []) if a.active] or list(data or [])

        t = Table.grid(padding=(0, 2), expand=False)
        for _ in range(5):
            t.add_column(justify="right", no_wrap=True)
        # dim column-header row
        t.add_row(
            Text(""),
            Text("today", style="dim"),
            Text("week", style="dim"),
            Text("5h", style="dim"),
            Text("window", style="dim"),
        )
        for a in shown:
            t.add_row(
                Text(a.label, style="bold"),
                Text(f"${a.today_cost:,.2f}", style="green"),
                Text(f"${a.week_cost:,.2f}", style="green"),
                Text(_humanize(a.block_tokens), style="cyan"),
                _window_cell(a.reset_in),
            )
        if len(shown) > 1:
            t.add_row(
                Text("Σ", style="dim"),
                Text(f"${sum(a.today_cost for a in shown):,.2f}", style="bold green"),
                Text(f"${sum(a.week_cost for a in shown):,.2f}", style="bold green"),
                Text(""),
                Text(""),
            )
        note = Text("$ = API-equiv (not billed)", style="dim italic")
        return Group(t, note)


def _humanize(n: int) -> str:
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _fmt_reset(secs: float | None) -> str:
    if not secs or secs <= 0:
        return "—"
    return f"{int(secs // 3600)}:{int((secs % 3600) // 60):02d}"


def _bar(frac: float, width: int = 8) -> str:
    frac = max(0.0, min(1.0, frac))
    filled = round(frac * width)
    return "█" * filled + "░" * (width - filled)


def _window_cell(reset_in: float | None) -> Text:
    # Bar fills with elapsed time in the 5h window; more filled = closer to reset.
    if not reset_in or reset_in <= 0:
        return Text(f"{'░' * 8} —", style="dim")
    frac = (_BLOCK - reset_in) / _BLOCK
    return Text(f"{_bar(frac)} {_fmt_reset(reset_in)}", style="cyan")
