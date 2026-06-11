# tickr — agent notes

Terminal dashboard for ambient feeds of "things that move." Personal tool for Matt.

## Mode: ALWAYS EXECUTOR (never orchestrator)

When a session is rooted in `tickr/`, you are an **executor**, not an orchestrator.
The mcheng-brain "default to orchestrator" banner does **not** apply here. Do the
work directly: read the code, design, implement, test, commit. Never draft a
dispatch prompt for tickr work, never tell Matt to spin up a fresh session for it.
This overrides the brain's orchestrator default. Surfaced 2026-06-11.

## Product preferences (do not relitigate)

- **No crypto. Ever.** Never propose crypto tickers (BTC/ETH/etc.), a crypto panel,
  or crypto as filler for empty space. Matt has said this many times. Prediction
  markets (Polymarket, Issue #1) are fine — those are the "for fun" panel, crypto is not.
- **News = business / finance / econ / tech / politics.** Not crime, tabloid,
  celebrity, royals, or sport. Use topic-specific RSS section feeds, not general
  "world" firehose feeds. See `config.toml [news].feeds`.

## Install / run

Installed as a global command via `uv tool install --editable .` → just run `tickr`
from anywhere. Editable, so source edits take effect on next launch (no reinstall).
Reinstall after dependency changes: `uv tool install --editable . --force`.

## Configurability model

- **Everything is `config.toml`** — there's no separate settings store. Adding
  tickers/feeds/panels = editing that file.
- **In-app settings editor** (`s` key → `SettingsScreen` in `tui.py`): a modal to
  add/remove list-valued config without leaving the dashboard — stock tickers,
  prediction (Polymarket) tags, Claude account homes, news feeds. Type+Enter adds,
  Enter/click a row removes. Writes go through `configwrite.set_list` (tomlkit, so
  config.toml's comments survive) and live-refresh the affected panel via
  `save_setting` → `_kickoff`. To expose a new field, add it to `SETTINGS_FIELDS`
  (table+key+label+hint) — only list-of-strings fields are supported.
- **Preset catalog** (`tickr/presets.toml` + `tickr/catalog.py`): curated, named
  groups of feeds-by-topic and ticker-sets. Reference by name instead of pasting
  URLs/symbols: `[news] topics = [...]`, `[stocks] sets = [...]` (merged with any
  explicit `feeds`/`tickers`). Browse with `tickr catalog [name]`. Add catalog
  entries only after verifying a feed returns `<item>`s.
- **Theme** persists via `[dashboard].theme`. Switch live (Ctrl-P → theme) and it
  **autosaves** — `watch_theme` → `_persist_theme` in `tui.py`, gated by `_ready`
  so startup doesn't write, idempotent so palette previews don't thrash the file.

## Architecture notes

- Installed entry point is `tickr.tui:main` (Textual app). `app.py` is now a
  library + a legacy rich-`Live` renderer; tui.py imports helpers from it.
- News parser (`tickr/sources/news.py`) reads RSS `<item>` only — Atom feeds
  (`<entry>`, e.g. The Verge) are NOT parsed. Validate a new feed returns `<item>`s
  before adding it.
- Option ids in the news panel must be unique (Textual `DuplicateID`); feeds can
  repeat a URL, so `apply()` dedupes by link.
- In-terminal reader (`reader.py`) can't fetch paywalled/bot-blocked sources
  (MarketWatch, Economist → 401/403, blocked even via readability proxy); it
  returns a "press 'b' for browser" note instead of crashing. Those are excluded
  from the default/catalog business feeds — keep them out.
- Reader rewrites arXiv `/abs/` and `/pdf/` links to the full HTML paper at
  `/html/<id>` (`_arxiv_html_url`); falls back to the original if no HTML version.
- A widget/panel = a `Source` subclass (`fetch()`/`render()`/`status()`, see
  `sources/base.py`) registered in the `SOURCES` dict (`sources/__init__.py`).
- Panels are either static (`SectionPanel`, uses `render()`) or **interactive**
  (`DataPanel`/`NewsPanel`, OptionLists). A source opts in with `interactive=True`
  and implements `list_rows(data, width)` + `detail(key, data)` instead of relying
  on `render()`. ←/→ move focus between interactive panels; enter/o/click opens a
  `DetailScreen` popup. stocks + predict are interactive; news opens the reader.

## Backlog

GitHub Issues in `mcheng88/tickr`. Open:
- #2 world oddities panel (launch / quakes / ISS)
- #3 resizable columns (fill-height done)
- #4 usage consumption bars (needs plan caps)
- #5 per-panel loading/failed state
- #6 reader + news polish (reader half done; remaining: parallelize news fetch,
  per-feed source labels, richer extraction)
- #7 user widgets dir (`~/.config/tickr/widgets/*.py`)

Done (#1 prediction markets, and unticketed: weather panel, interactive panels +
detail popups, preset catalog, theme persistence, usage auto-discovery).
