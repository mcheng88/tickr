from __future__ import annotations

import argparse
import os
import time
import tomllib
from datetime import datetime
from pathlib import Path

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .sources import load_source


def _find_config() -> Path:
    candidates: list[Path] = []
    env = os.environ.get("TICKR_CONFIG")
    if env:
        candidates.append(Path(env))
    candidates.append(Path.cwd() / "config.toml")
    candidates.append(Path(__file__).resolve().parent.parent / "config.toml")
    for c in candidates:
        if c.is_file():
            return c
    raise SystemExit("No config.toml found (set TICKR_CONFIG or run from the repo root).")


def load_config() -> dict:
    with open(_find_config(), "rb") as f:
        return tomllib.load(f)


def _source_names(cfg: dict) -> list[str]:
    dash = cfg.get("dashboard", {})
    names = dash.get("sources")
    if names:
        return list(names)
    single = dash.get("source")
    return [single] if single else ["stocks"]


def _layout_columns(cfg: dict) -> list[list[str]]:
    """A list of columns, each a list of source names. Falls back to one column."""
    cols = cfg.get("dashboard", {}).get("columns")
    if cols:
        return [list(c) for c in cols]
    return [_source_names(cfg)]


def _section(source, data) -> list:
    title = Text()
    title.append(source.title, style="bold white")
    st = source.status()
    if st:
        title.append("  ")
        title.append(st, style="green" if st == "OPEN" else "yellow")
    body = source.render(data) if data is not None else Text("loading…", style="dim")
    return [title, body]


def _column(names: list[str], sources: dict, data: dict) -> Group:
    blocks: list = []
    for j, name in enumerate(names):
        blocks.extend(_section(sources[name], data.get(name)))
        if j < len(names) - 1:
            blocks.append(Text(""))  # spacer between stacked sections
    return Group(*blocks)


def _frame(columns: list[list[str]], sources: dict, data: dict) -> Panel:
    clock = Text(datetime.now().strftime("%H:%M:%S"), style="bold cyan")
    if len(columns) == 1:
        body = _column(columns[0], sources, data)
    else:
        grid = Table.grid(expand=True, padding=(0, 4))
        for i in range(len(columns)):
            grid.add_column(ratio=1 if i == len(columns) - 1 else None)  # last column fills
        grid.add_row(*[_column(c, sources, data) for c in columns])
        body = grid
    return Panel(Group(clock, Text(""), body), border_style="grey37", padding=(0, 1), expand=True)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="tickr", description="Ambient terminal feeds of things that move.")
    ap.add_argument("--once", action="store_true", help="render a single frame and exit (sanity check / screenshot)")
    args = ap.parse_args(argv)

    cfg = load_config()
    dash = cfg.get("dashboard", {})
    default_refresh = int(dash.get("refresh_seconds", 60))
    fullscreen = bool(dash.get("fullscreen", True))
    tick = float(dash.get("tick_seconds", 0.5))  # animation cadence (e.g. ticker crawl)

    columns = _layout_columns(cfg)
    names = [n for col in columns for n in col]
    sources = {n: load_source(cfg, n) for n in names}
    intervals = {n: int(cfg.get(n, {}).get("refresh_seconds", default_refresh)) for n in names}

    if args.once:
        data: dict = {}
        for n in names:
            try:
                data[n] = sources[n].fetch()
            except Exception:
                data[n] = None
        Console().print(_frame(columns, sources, data))
        return

    data = {n: None for n in names}
    last_fetch = {n: 0.0 for n in names}
    try:
        with Live(auto_refresh=False, screen=fullscreen) as live:
            while True:
                now = time.monotonic()
                for n in names:
                    if last_fetch[n] == 0.0 or now - last_fetch[n] >= intervals[n]:
                        try:
                            data[n] = sources[n].fetch()
                        except Exception:
                            pass  # keep last good section; no visible staleness meter
                        last_fetch[n] = now
                live.update(_frame(columns, sources, data), refresh=True)
                time.sleep(tick)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
