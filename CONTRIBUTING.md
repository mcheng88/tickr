# Contributing to tickr

Thanks for poking at tickr. It's a small, no-build-step Python TUI — easy to hack on.

## Dev setup

```bash
git clone https://github.com/mcheng88/tickr.git
cd tickr
python3 -m venv .venv && source .venv/bin/activate
pip install -e .          # editable — source edits take effect on next launch
tickr                     # run it
pytest                    # run the tests
```

(If you use [uv](https://github.com/astral-sh/uv): `uv tool install --editable .` puts
a `tickr` command on your PATH and keeps it editable.)

## The easiest way to contribute: write a widget

Every panel is one `Source` subclass (`tickr/sources/base.py`): a `fetch()` that pulls a
little data and a `render()` (or `list_rows()` + `detail()` for interactive panels). You
don't have to touch the installed package to add one — drop a `.py` file in
`~/.config/tickr/widgets/` and it's auto-discovered at startup.

Start from the worked example: [`examples/widgets/uptime.py`](examples/widgets/uptime.py).
Copy it into your widgets dir, add the panel name to `[dashboard].columns` in
`config.toml`, and launch. If yours is broadly useful, send it in as a built-in under
`tickr/sources/` (register it in `tickr/sources/__init__.py`).

## House rules

- **Keyless, free APIs only.** tickr's whole pitch is zero-config, no API keys. A panel
  that needs a key or a paid plan won't be merged as a built-in.
- **No crypto.** Not a built-in panel, not a default ticker. (Write it as a personal
  widget if you want it locally — that's what the widgets dir is for.)
- **News feeds must be RSS.** The news parser reads RSS `<item>` only — Atom (`<entry>`)
  feeds aren't parsed. Verify a feed returns `<item>`s before adding it to the catalog.
- **`render()` must not raise.** `fetch()` may raise (the last good frame is kept), but
  rendering has to be safe — a panel that throws while drawing breaks the dashboard.
- Keep PRs focused; run `pytest` before opening one.

## Bugs & ideas

Open a [GitHub issue](https://github.com/mcheng88/tickr/issues). Short and concrete beats
long and vague.
