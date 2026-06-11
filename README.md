# tickr

A Bloomberg terminal from first principles — ambient feeds of **things that move**, sized for a corner of your terminal so you can stay where you work.

Not a to-do list, not a project dashboard. Just live, glanceable signal: markets, prediction odds, curated headlines, and other fast-changing numbers. A source earns a permanent corner of your screen only if it **moves fast enough to reward a glance**.

```
┌──────────────────────────────┐
│ STOCKS  OPEN   13:07:42  ↻ 8s │
│                              │
│ AAPL    313.84      ▲0.31%    │
│ NVDA    178.20      ▲1.04%    │
│ MSFT    471.03      ▼0.22%    │
│ TSLA    241.55      ▼1.130%   │
│ SPY     598.41      ▲0.18%    │
└──────────────────────────────┘
```

## Install

Requires Python 3.11+. Recommended — puts a `tickr` command on your PATH (editable,
so source edits take effect on next launch):

```bash
uv tool install --editable .
```

Or in a virtualenv: `python3 -m venv .venv && source .venv/bin/activate && pip install -e .`

## Run

```bash
tickr                 # run the dashboard from anywhere
tickr catalog         # list curated news topics + ticker sets
```

`q` or `Ctrl-C` to quit. The header clock ticks every second; network fetches are
throttled per source.

### Keys

| Key | Action |
|-----|--------|
| `↑` / `↓` | move the row cursor in the focused panel |
| `←` / `→` | move focus between panels (incl. into the left column from news) |
| `enter` / `o` / click | open the highlighted row — article reader (news) or detail popup (stocks/predict) |
| `space` | pause/resume the news auto-scroll |
| `s` | settings — add/remove tickers, prediction tags, Claude accounts, news feeds (saves live) |
| `Ctrl-P` | command palette (switch theme — it autosaves) |
| `esc` / `q` | close a popup |

## Panels

All free, no API keys.

| Panel | What it shows |
|-------|---------------|
| **stocks** | Watchlist + indices via Yahoo (batched, true day-change, market state). Gold/oil/rates work too (`GC=F`, `CL=F`, `^TNX`). |
| **news** | Curated headlines from direct RSS feeds, deduped + newest-first. Open any in an in-terminal reader (full arXiv papers; paywalled sources fall back to the browser). |
| **predict** | Live Polymarket odds by topic — favorite outcome + 24h move; drill in for the full outcome list. |
| **weather** | Current conditions + 4-day forecast as ASCII art (Open-Meteo; location auto-detects). |
| **claude usage** | Claude Code token/cost today + week + 5-hour window, auto-discovered across `~/.claude*` accounts (100% local). |

## Configure

Edit `config.toml`. Layout is columns of stacked panels; the last column fills the width:

```toml
[dashboard]
theme = "tokyo-night"    # switch live with Ctrl-P; autosaves here
columns = [["weather", "stocks", "predict", "claude_usage"], ["news"]]

[stocks]
tickers = ["^GSPC", "^IXIC", "NVDA", "AAPL", "GC=F"]
# sets = ["indices", "gold"]      # or reference curated catalog groups

[news]
topics = ["business", "tech", "politics"]   # curated feed bundles (see `tickr catalog`)
```

Reference curated **feed topics** and **ticker sets** by name instead of pasting
URLs/symbols — browse them with `tickr catalog`. Point `TICKR_CONFIG` at a config
elsewhere if you like.

## Architecture

Every panel is one `Source` (`tickr/sources/base.py`): a `fetch()` that pulls a little
data, and either a `render()` (static panels) or `list_rows()` + `detail()` (interactive
panels — focusable, selectable, with a detail popup). The app ([`tickr/tui.py`](tickr/tui.py),
a [Textual](https://textual.textualize.io/) app) lays the configured sources out in
columns, fetches each on its own interval in a worker thread, and keeps the last good
frame on failure. Adding a panel = one file in `tickr/sources/` registered in
`sources/__init__.py`.

## Roadmap

- [x] **stocks** — watchlist + indices via Yahoo (batched, true day-change)
- [x] **claude usage** — token/cost today + week + 5h-window, auto-discovered across accounts (100% local)
- [x] **news** — curated RSS feeds + in-terminal reader (arXiv full-text, paywall fallback)
- [x] **prediction markets** — Polymarket live odds, with per-event outcome detail
- [x] **weather** — ASCII-art current + forecast (Open-Meteo)
- [x] **interactive panels** — keyboard nav + detail popups; preset catalog; theme persistence
- [ ] **world oddities** — next rocket launch, earthquakes, ISS overhead (#2)
- [ ] **usage consumption bars** — needs plan caps (#4)
- [ ] **per-panel loading/failed state** (#5) · **resizable columns** (#3) · **user widgets dir** (#7)

Cross-platform (macOS + Linux). Runs great in [kitty](https://sw.kovidgoyal.net/kitty/).
