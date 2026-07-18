"""Style-preserving writes back to config.toml.

The app reads config with stdlib ``tomllib`` (fast, read-only). Writes go through
here with ``tomlkit`` so comments and formatting in config.toml survive an edit —
the file is hand-curated with lots of explanatory comments worth keeping.

Used by the in-app Settings screen (tui.py) to persist edits to list-valued
config (stock tickers, prediction tags, Claude homes, news feeds).
"""
from __future__ import annotations

import tomlkit

from .app import _find_config


def set_list(table: str, key: str, values: list[str]) -> None:
    """Set ``[table].key`` to ``values`` (a TOML array of strings), creating the
    table/key if absent, and write config.toml back in place. Arrays of 4+ items
    are written multiline for readability."""
    path = _find_config()
    doc = tomlkit.parse(path.read_text())

    tbl = doc.get(table)
    if tbl is None:
        tbl = tomlkit.table()
        doc[table] = tbl

    arr = tomlkit.array()
    for v in values:
        arr.append(v)
    if len(values) > 4:
        arr.multiline(True)
    tbl[key] = arr

    path.write_text(tomlkit.dumps(doc))


def set_value(table: str, key: str, value) -> None:
    """Set a scalar ``[table].key`` (int/float/str/bool), creating the table/key
    if absent, and write config.toml back in place with comments preserved. Used
    for live layout tweaks like the ``[dashboard].left_width`` column-width nudge."""
    path = _find_config()
    doc = tomlkit.parse(path.read_text())

    tbl = doc.get(table)
    if tbl is None:
        tbl = tomlkit.table()
        doc[table] = tbl

    tbl[key] = value
    path.write_text(tomlkit.dumps(doc))
