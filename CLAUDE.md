# tickr — agent notes

Terminal dashboard for ambient feeds of "things that move." Personal tool for Matt.

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

## Backlog

GitHub Issues in `mcheng88/tickr`. Open: #1 prediction markets (Polymarket),
#2 world oddities, #3 vertical fill, #4 usage bars, #5 loading/failed state,
#6 reader + news polish, #7 user widgets dir (`~/.config/tickr/widgets/*.py`).
