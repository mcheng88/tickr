"""Example tickr user widget.

Drop a copy of this file in your widgets dir to get a live panel — no editing of
the installed package required:

    mkdir -p ~/.config/tickr/widgets
    cp examples/widgets/uptime.py ~/.config/tickr/widgets/

Then name it in config.toml's [dashboard].columns (the panel's key is the `name`
attribute below, falling back to the filename stem if you omit it):

    [dashboard]
    columns = [["stocks", "uptime"], ["news"]]

    [uptime]               # whatever you return from config.get() lands here
    label = "since boot"

The Source contract (see tickr/sources/base.py):
  * title       — header text for the panel.
  * name        — registry key used in config (optional; defaults to the filename).
  * fetch()     — pull a little data; cheap; may raise (last good frame is kept).
  * render(data)— draw `data` to a rich renderable; must NOT raise.
  * status()    — optional one-word badge (e.g. OPEN/CLOSED); "" for none.

self.config is the [<name>] table from config.toml (an empty dict if absent).
"""

from __future__ import annotations

import time

from rich.text import Text

from tickr.sources.base import Source


class UptimeSource(Source):
    title = "UPTIME"
    name = "uptime"  # the key you reference in [dashboard].columns

    def __init__(self, config):
        super().__init__(config)
        self._start = time.monotonic()

    def fetch(self) -> float:
        return time.monotonic() - self._start

    def render(self, data: float) -> Text:
        secs = int(data or 0)
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        label = self.config.get("label", "running")
        return Text(f"{label}: {h:d}:{m:02d}:{s:02d}", style="bold cyan")
