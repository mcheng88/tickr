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

Requires Python 3.11+.

```bash
git clone <repo> tickr && cd tickr
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Run

```bash
tickr            # or: python -m tickr
```

Pop the window into a corner of your terminal. `Ctrl-C` to quit. The clock and staleness age (`↻ Ns`) tick every second; network fetches are throttled to `refresh_seconds`.

## Configure

Edit `config.toml`:

```toml
[dashboard]
source = "stocks"        # active panel
refresh_seconds = 60

[stocks]
tickers = ["SPY", "^IXIC", "NVDA", "AAPL", "GOOG"]
```

Plain tickers work as-is. Indices use a leading caret — `^IXIC` (Nasdaq Composite), `^GSPC` (S&P 500), `^DJI` (Dow). Point `TICKR_CONFIG` at a config elsewhere if you like.

Data: Yahoo Finance quotes — free, no API key. Every symbol is fetched in a single batched request per cycle (a 15-name watchlist polled each minute is ~1 request/min), with true day-change vs. previous close and pre/after-hours market state.

## Architecture

Every panel is one `Source` (`tickr/sources/base.py`): a `fetch()` that pulls a little data and a `render()` that draws it. The app loop ([`tickr/app.py`](tickr/app.py)) stacks the configured sources in one pane, fetches each on its own interval, keeps the last good frame on failure, and redraws every `tick_seconds` so time-derived renders (like the news ticker) animate. Adding a panel = one file in `tickr/sources/` registered in `sources/__init__.py`.

## Roadmap

- [x] **stocks** — watchlist + indices via Yahoo (batched, true day-change)
- [x] **claude usage** — Claude Code token/cost today + week + 5-hour-window across accounts (100% local)
- [x] **news** — scrolling top-stories ticker (Google News firehose)
- [x] **multi-panel** — stack any sources in one pane
- [ ] **prediction markets** — Polymarket live odds
- [ ] **world oddities** — next rocket launch, earthquakes, ISS overhead
- [ ] **fill / layout** — expand sections to fill the window; usage consumption bars (needs plan caps)

Cross-platform (macOS + Linux). Runs great in [kitty](https://sw.kovidgoyal.net/kitty/).
