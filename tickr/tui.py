from __future__ import annotations

import webbrowser
from functools import partial
from time import monotonic

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, OptionList, Static
from textual.widgets.option_list import Option

from .app import _layout_columns, load_config
from .reader import fetch_article
from .sources import discover_widgets, load_source

# Sources are non-interactive panels (a rich renderable refreshed on a timer);
# "news" is special — an interactive, scrollable, selectable headline list, and
# "rates" pops a full-curve detail screen on enter/click.
_NEWS = "news"
_RATES = "rates"

# Live column-width nudge (Issue #3). The side column(s) have a fixed width and
# the last column flexes to fill the rest; `[` / `]` nudge that width live and
# persist it to [dashboard].left_width. Clamped so neither side vanishes.
_DEFAULT_SIDE_WIDTH = 56
_MIN_SIDE_WIDTH = 24
_WIDTH_STEP = 4  # columns per nudge
_FILL_FLOOR = 20  # keep at least this many cols for the flexing (news) column


class _PanelStatus:
    """Mixin: folds a subtle loading/stale/failed indicator into a panel's
    ``border_title`` so a blank or unchanging panel is always explained.

    State machine: panels start ``loading``; a good fetch flips them to ``ok``;
    a failed/empty fetch flips them to ``failed``. A panel that has shown data
    before keeps showing it on failure, but the indicator turns to ``stale Ns``
    (the age of the last good frame) so the staleness is visible rather than
    silent. Subclasses provide ``refresh_title`` to compose the full header."""

    def _init_status(self) -> None:
        self._ok_at: float | None = None  # monotonic time of last good fetch
        self._state = "loading"  # loading → ok → failed

    def mark_ok(self) -> None:
        self._ok_at = monotonic()
        self._state = "ok"

    def mark_failed(self) -> None:
        self._state = "failed"
        self.refresh_title()  # show it immediately, don't wait for the 1s tick

    def _indicator(self) -> str:
        """Rich-markup status badge, or empty string when healthy and fresh."""
        if self._state == "loading":
            return "[dim]loading…[/dim]"
        if self._state == "failed":
            if self._ok_at is None:
                return "[red dim]failed[/red dim]"
            return f"[yellow dim]stale {int(monotonic() - self._ok_at)}s[/yellow dim]"
        return ""

    def refresh_title(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


class SectionPanel(Static, _PanelStatus):
    """A non-interactive source panel: titled border + rendered body, refreshed
    on the source's own interval."""

    def __init__(self, source):
        super().__init__()
        self.source = source
        self._init_status()
        self.refresh_title()

    def apply(self, data) -> None:
        self.mark_ok()
        self.update(self.source.render(data))
        self.refresh_title()

    def refresh_title(self) -> None:
        parts = [self.source.title]
        st = self.source.status()
        if st:
            parts.append(st)
        ind = self._indicator()
        if ind:
            parts.append(ind)
        self.border_title = "  ".join(parts)


class RatesPanel(SectionPanel):
    """Treasury rates panel: the always-on curated ladder, focusable so enter or
    a click pops the full par yield curve in a modal."""

    can_focus = True
    BINDINGS = [("enter", "detail", "Full curve")]

    def __init__(self, source):
        super().__init__(source)
        self._data = None

    def apply(self, data) -> None:
        self._data = data
        super().apply(data)

    def action_detail(self) -> None:
        # Open the popup even before the (slow, once-on-startup) Treasury fetch
        # lands — RatesScreen shows a "loading" state for None data, so `r`
        # always gives feedback instead of silently doing nothing.
        self.app.push_screen(RatesScreen(self.source, self._data))

    def on_click(self) -> None:
        self.action_detail()

    def refresh_title(self) -> None:
        # Compose the base title (incl. the #9 loading/stale/failed indicator,
        # which the 1s status tick keeps refreshing), then append the popup hint
        # so it survives every refresh instead of being overwritten once.
        super().refresh_title()
        self.border_title = f"{self.border_title}  ↵ curve"


class RatesScreen(ModalScreen):
    """Full US Treasury par yield curve — every tenor, with day-over-day basis-
    point moves. The panel shows a curated ladder; this shows the whole thing."""

    CSS = """
    RatesScreen { align: center middle; }
    #curve { width: 54; height: auto; max-height: 90%; border: round #5f5f5f; background: $surface; padding: 1 2; }
    #curve-title { text-style: bold; color: $accent; }
    #curve-meta { color: $text-muted; margin-bottom: 1; }
    #curve-plot { margin-bottom: 1; }
    """
    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
    ]

    def __init__(self, source, data):
        super().__init__()
        self.source = source
        self.data = data

    def compose(self) -> ComposeResult:
        with Vertical(id="curve"):
            yield Static("US Treasury par yield curve", id="curve-title")
            if self.data is None:
                yield Static("loading…", id="curve-meta")
                yield Footer()
                return
            sub = self.data.date
            if self.data.prior_date:
                sub += f"  (Δbp vs {self.data.prior_date})"
            yield Static(sub, id="curve-meta")
            yield Static(self.source.render_curve(self.data, width=48, height=8), id="curve-plot")
            yield Static(self.source.render_detail(self.data))
        yield Footer()

    def action_close(self) -> None:
        self.dismiss()


class NewsPanel(OptionList, _PanelStatus):
    """Scrollable, selectable headline feed. Auto-advances (ambient) unless
    paused; arrows/j-k scroll; enter or click opens the article."""

    def __init__(self, source):
        super().__init__()
        self.source = source
        self.paused = False
        self._init_status()
        self.refresh_title()

    def apply(self, items: list[tuple[str, str, str]]) -> None:
        self.mark_ok()
        keep = self.highlighted
        self.clear_options()
        show_source = bool(self.source.config.get("show_source", False))
        # Option ids must be unique; feeds occasionally repeat a URL, so drop
        # later duplicates (items without a link keep id=None, never collide).
        seen: set[str] = set()
        opts = []
        for t, link, source in items:
            if link and link in seen:
                continue
            if link:
                seen.add(link)
            # Text() prompt → rendered literally; a headline with '[' won't be
            # mis-parsed as Rich markup (would crash the OptionList).
            row = Text(f"• {t}")
            if show_source and source:
                row.append(f"  {source}", style="dim")
            opts.append(Option(row, id=(link or None)))
        self.add_options(opts)
        if keep is not None and self.option_count:
            self.highlighted = min(keep, self.option_count - 1)
        self.refresh_title()

    def refresh_title(self) -> None:
        parts = ["NEWS"]
        if self.paused:
            parts.append("(paused)")
        ind = self._indicator()
        if ind:
            parts.append(ind)
        self.border_title = "  ".join(parts)

    def advance(self) -> None:
        if self.option_count:
            cur = self.highlighted if self.highlighted is not None else -1
            self.highlighted = (cur + 1) % self.option_count


class DataPanel(OptionList, _PanelStatus):
    """Interactive tabular panel (stocks, predict). ↑/↓ moves the row cursor;
    enter / 'o' / click opens a detail popup for the highlighted row."""

    def __init__(self, source):
        super().__init__()
        self.source = source
        self._data = None
        self._init_status()
        self.refresh_title()

    def apply(self, data) -> None:
        self.mark_ok()
        self._data = data
        keep = self.highlighted
        self.clear_options()
        width = self.content_size.width or 50
        rows = self.source.list_rows(data, width)
        self.add_options([Option(row, id=str(key)) for row, key in rows])
        if keep is not None and self.option_count:
            self.highlighted = min(keep, self.option_count - 1)
        elif self.option_count:
            self.highlighted = 0  # show a cursor row from the start
        self.refresh_title()

    def refresh_title(self) -> None:
        parts = [self.source.title]
        st = self.source.status()
        if st:
            parts.append(st)
        ind = self._indicator()
        if ind:
            parts.append(ind)
        self.border_title = "  ".join(parts)

    def open_detail(self) -> None:
        if self.highlighted is None or self._data is None:
            return
        opt = self.get_option_at_index(self.highlighted)
        if opt is None or opt.id is None:
            return
        self.app.push_screen(DetailScreen(self.source.title, self.source.detail(opt.id, self._data)))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()  # don't let it bubble to the app's news handler
        self.open_detail()


class DetailScreen(ModalScreen):
    """Compact popup (smaller than the article reader) showing a row's detail —
    a stock's full quote or a prediction event's complete outcome list."""

    CSS = """
    DetailScreen { align: center middle; }
    #detail { width: auto; min-width: 40; max-width: 70; height: auto; max-height: 80%;
              border: round $accent; background: $surface; padding: 1 2; }
    """
    BINDINGS = [("escape", "close", "Close"), ("q", "close", "Close")]

    def __init__(self, title: str, content):
        super().__init__()
        self._title = title
        self._content = content

    def compose(self) -> ComposeResult:
        box = VerticalScroll(id="detail")
        box.border_title = self._title
        with box:
            yield Static(self._content)
        yield Footer()

    def action_close(self) -> None:
        self.dismiss()


class ArticleScreen(ModalScreen):
    """In-terminal reader: fetches the article and shows extracted text. Bloomberg-
    style — read without leaving the terminal. 'b' falls back to the browser."""

    CSS = """
    ArticleScreen { align: center middle; }
    #reader { width: 96%; height: 96%; border: round #5f5f5f; background: $surface; padding: 1 3; }
    #reader-body { margin-top: 1; }
    #reader-title { text-style: bold; color: $accent; }
    #reader-meta { color: $text-muted; }
    """
    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("b", "browser", "Open in browser"),
    ]

    def __init__(self, url: str, headline: str):
        super().__init__()
        self.url = url
        self.headline = headline

    def compose(self) -> ComposeResult:
        # markup=False: headlines/URLs/article text are untrusted and routinely
        # contain '[' — never parse them as Rich markup (would MarkupError-crash).
        with VerticalScroll(id="reader"):
            yield Static(self.headline, id="reader-title", markup=False)
            yield Static(self.url, id="reader-meta", markup=False)
            yield Static("Loading…", id="reader-body", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#reader").focus()
        self.run_worker(self._load, thread=True)

    def _load(self) -> None:
        try:
            text = fetch_article(self.url)
        except Exception as e:
            text = f"(failed to load: {e})"
        self.app.call_from_thread(self.query_one("#reader-body", Static).update, text)

    def action_close(self) -> None:
        self.dismiss()

    def action_browser(self) -> None:
        webbrowser.open(self.url)


# Editable list-valued config exposed in the Settings screen. Each entry maps a
# config `[table].key` (a TOML array of strings) to a friendly label + hint. The
# table name doubles as the source name, so edits can live-refresh that panel.
SETTINGS_FIELDS = [
    {"table": "stocks", "key": "tickers", "label": "Stock tickers",
     "hint": "Yahoo symbols — plain (NVDA, AAPL) or indices with a caret (^GSPC)."},
    {"table": "predict", "key": "tags", "label": "Prediction searches",
     "hint": "Polymarket tag slugs — e.g. politics, geopolitics, economy. No crypto."},
    {"table": "claude_usage", "key": "homes", "label": "Claude accounts",
     "hint": "Config homes like ~/.claude-berry. Empty = auto-discover all ~/.claude* homes."},
    {"table": "news", "key": "feeds", "label": "News feeds",
     "hint": "RSS feed URLs (must expose <item>, not Atom <entry>)."},
]


class ListEditScreen(ModalScreen):
    """Add/remove entries of one list-valued config field. Type + Enter adds;
    Enter/click on an existing row removes it. Each change persists to
    config.toml immediately and live-refreshes the panel if it's on screen."""

    CSS = """
    ListEditScreen { align: center middle; }
    #editbox { width: 72; height: auto; max-height: 90%; border: round $accent;
               background: $surface; padding: 1 2; }
    #edithint { color: $text-muted; margin-bottom: 1; }
    #editadd { margin-bottom: 1; }
    #editlist { height: auto; max-height: 18; }
    #editempty { color: $text-muted; }
    """
    BINDINGS = [
        ("escape", "close", "Done"),
        ("shift+up", "move(-1)", "Move up"),
        ("shift+down", "move(1)", "Move down"),
        ("backspace", "remove", "Remove"),
        ("delete", "remove", "Remove"),
    ]

    def __init__(self, field: dict, values: list[str]):
        super().__init__()
        self.field = field
        self.values = list(values)

    def compose(self) -> ComposeResult:
        box = Vertical(id="editbox")
        box.border_title = self.field["label"]
        with box:
            yield Static(
                f"{self.field['hint']}\n"
                "↑/↓ select · Shift+↑/↓ reorder · ⌫ remove · Tab → add box · Esc when done",
                id="edithint",
            )
            yield Input(placeholder="type a value + Enter to add…", id="editadd")
            yield OptionList(id="editlist")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_list(highlight=0)
        self.query_one("#editlist", OptionList).focus()  # list is home: arrows/reorder/remove ready

    def _refresh_list(self, highlight: int | None = None) -> None:
        ol = self.query_one("#editlist", OptionList)
        ol.clear_options()
        if not self.values:
            ol.add_option(Option(Text("(none yet — Tab to the box above to add)"), id=None))
            return
        # markup=False semantics: values can contain '[' (URLs, etc.) — render
        # literally via Text(). id is the position so removal is unambiguous.
        ol.add_options([Option(Text(f"• {v}"), id=str(i)) for i, v in enumerate(self.values)])
        if highlight is not None and self.values:
            ol.highlighted = max(0, min(highlight, len(self.values) - 1))

    def _save(self) -> None:
        self.app.save_setting(self.field["table"], self.field["key"], self.values)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        val = event.value.strip()
        event.input.value = ""
        if not val or val in self.values:
            return  # ignore blanks and duplicates
        self.values.append(val)
        self._save()
        # Return home to the list, highlighting the new (last) row so it's
        # immediately reorderable/removable.
        self._refresh_list(highlight=len(self.values) - 1)
        self.query_one("#editlist", OptionList).focus()

    def action_remove(self) -> None:
        """Remove the highlighted row (⌫/Del). Explicit, so navigating/clicking a
        row never deletes it by surprise."""
        ol = self.query_one("#editlist", OptionList)
        i = ol.highlighted
        if i is None or not self.values:
            return
        del self.values[i]
        self._save()
        self._refresh_list(highlight=i)  # keep the cursor near where it was
        ol.focus()

    def action_move(self, delta: int) -> None:
        """Shift the highlighted row up/down one slot — order is meaningful (it's
        the panel's display order). Keeps the highlight on the moved item."""
        ol = self.query_one("#editlist", OptionList)
        i = ol.highlighted
        if i is None or not self.values:
            return
        j = i + delta
        if j < 0 or j >= len(self.values):
            return  # already at an end
        self.values[i], self.values[j] = self.values[j], self.values[i]
        self._save()
        self._refresh_list(highlight=j)
        ol.focus()

    def action_close(self) -> None:
        self.dismiss()


class SettingsScreen(ModalScreen):
    """Top-level settings menu: pick a config list to edit. Changes made in the
    child editors save live, so closing this needs no explicit save step."""

    CSS = """
    SettingsScreen { align: center middle; }
    #setbox { width: 60; height: auto; max-height: 80%; border: round $accent;
              background: $surface; padding: 1 2; }
    #sethint { color: $text-muted; margin-bottom: 1; }
    """
    BINDINGS = [("escape", "close", "Close")]

    def compose(self) -> ComposeResult:
        box = Vertical(id="setbox")
        box.border_title = "Settings"
        with box:
            yield Static("Edit a list — changes save to config.toml instantly.", id="sethint")
            yield OptionList(id="setmenu")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_menu()
        self.query_one("#setmenu", OptionList).focus()

    def _refresh_menu(self) -> None:
        ol = self.query_one("#setmenu", OptionList)
        keep = ol.highlighted
        ol.clear_options()
        opts = []
        for i, f in enumerate(SETTINGS_FIELDS):
            n = len(self.app.setting_values(f["table"], f["key"]))
            opts.append(Option(Text(f"{f['label']}  ({n})"), id=str(i)))
        ol.add_options(opts)
        ol.highlighted = min(keep, ol.option_count - 1) if keep is not None else 0

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        field = SETTINGS_FIELDS[int(event.option.id)]
        values = self.app.setting_values(field["table"], field["key"])
        # Re-render counts after the editor closes.
        self.app.push_screen(ListEditScreen(field, values), lambda _=None: self._refresh_menu())

    def action_close(self) -> None:
        self.dismiss()


class TickrApp(App):
    TITLE = "tickr"
    CSS = """
    Screen { background: $background; }
    /* The stacked side column scrolls when its panels total more than the
       window height — so a tall panel (e.g. oddities at the bottom) is reachable
       instead of clipped. Panels stay content-sized, so there's no wasted
       whitespace when everything already fits. */
    .side { width: 56; height: 1fr; overflow-y: auto; scrollbar-size-vertical: 1; }
    .fill { width: 1fr; height: 1fr; }
    SectionPanel { border: round #5f5f5f; padding: 0 1; width: 1fr; height: auto; margin-bottom: 0;
                   overflow-y: auto; scrollbar-size-vertical: 1; }
    /* Interactive list panels flex to share the column height and scroll inside
       when content overflows — so the column always fills and never spills. */
    DataPanel { border: round #5f5f5f; padding: 0 1; width: 1fr; height: 1fr; min-height: 5;
                margin-bottom: 0; scrollbar-size-vertical: 1; }
    NewsPanel { border: round #5f5f5f; padding: 0 1; height: 1fr; scrollbar-size-vertical: 1; }
    OptionList > .option-list--option { padding: 0; }  /* drop the default per-row padding */
    DataPanel:focus, NewsPanel:focus { border: round $accent; }
    DataPanel > .option-list--option-highlighted,
    NewsPanel > .option-list--option-highlighted { background: $accent 30%; color: $text; }
    """
    # `s`/`r` are marked priority so they're resolved at the App level *before*
    # the focused widget's own binding chain. Some terminals (kitty keyboard
    # protocol) otherwise let a focused OptionList swallow these two specific
    # keys; priority bindings sidestep that. See action_settings/rates_detail.
    BINDINGS = [
        ("space", "toggle_pause", "Pause/resume scroll"),
        ("left", "focus_panel('prev')", "Prev panel"),
        ("right", "focus_panel('next')", "Next panel"),
        ("o", "open", "Open / detail"),
        Binding("r", "rates_detail", "Treasury curve", priority=True),
        Binding("s", "settings", "Settings", priority=True),
        # Live column-width nudge. Priority so a focused OptionList (kitty keyboard
        # protocol) can't swallow them — same reason `s`/`r` are priority.
        Binding("[", "nudge_width(-1)", "Narrower side", priority=True),
        Binding("]", "nudge_width(1)", "Wider side", priority=True),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        dash = cfg.get("dashboard", {})
        self._saved_theme = dash.get("theme")  # persisted theme name, applied on mount
        self.default_refresh = int(dash.get("refresh_seconds", 60))
        self.scroll_seconds = float(cfg.get(_NEWS, {}).get("scroll_seconds", 4))
        self.left_width = dash.get("left_width")
        self.columns = _layout_columns(cfg)
        self.names = [n for col in self.columns for n in col]
        self.sources = {n: load_source(cfg, n) for n in self.names}
        self.widgets = {n: self._make_panel(n) for n in self.names}
        self.paused = False
        self._theme_ready = False  # gate theme autosave until after startup applies the saved theme

    def _make_panel(self, name: str):
        src = self.sources[name]
        if name == _NEWS:
            return NewsPanel(src)
        if name == _RATES:
            return RatesPanel(src)
        if getattr(src, "interactive", False):
            return DataPanel(src)
        return SectionPanel(src)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        last = len(self.columns) - 1
        with Horizontal():
            for ci, col in enumerate(self.columns):
                with Vertical(classes="fill" if ci == last else "side"):
                    for name in col:
                        yield self.widgets[name]
        yield Footer()

    def on_mount(self) -> None:
        if self._saved_theme:
            try:
                self.theme = self._saved_theme
            except Exception:
                pass  # unknown theme name in config → keep default
        if self.left_width:
            self._apply_side_width(int(self.left_width))
        # Per-panel height: `[<panel>] height = N` pins that panel to N rows
        # (content scrolls inside if it overflows) so a tall panel like rates
        # doesn't dominate its column. Unset = auto (fit content), the default.
        for name in self.names:
            h = self.cfg.get(name, {}).get("height")
            if h:
                self.widgets[name].styles.height = int(h)
        for name in self.names:
            self._kickoff(name)  # initial fetch
            interval = int(self.cfg.get(name, {}).get("refresh_seconds", self.default_refresh))
            self.set_interval(interval, partial(self._kickoff, name))
        if _NEWS in self.widgets:
            self.set_interval(self.scroll_seconds, self._advance_news)
            self.widgets[_NEWS].focus()
        # Keep "stale Ns" counters ticking while a panel sits failed/unrefreshed.
        self.set_interval(1, self._refresh_statuses)
        self._theme_ready = True  # from here on, theme changes autosave

    def _refresh_statuses(self) -> None:
        for w in self.widgets.values():
            w.refresh_title()

    def watch_theme(self, theme: str) -> None:
        """Persist the theme to config.toml whenever it changes (e.g. picked live
        in the Ctrl-P palette) — no manual save step."""
        if self._theme_ready and theme:
            self._persist_theme(theme)

    # --- data plumbing: blocking fetch in a thread, apply on the UI thread ---

    def _kickoff(self, name: str) -> None:
        self.run_worker(partial(self._fetch, name), thread=True, exclusive=False, group=f"fetch-{name}")

    def _fetch(self, name: str) -> None:
        try:
            data = self.sources[name].fetch()
        except Exception:
            data = None
        if not data:  # failed or empty → flag the panel, retry soon
            self.call_from_thread(self.widgets[name].mark_failed)
            self.call_from_thread(self.set_timer, 5, partial(self._kickoff, name))
            return
        self.call_from_thread(self.widgets[name].apply, data)

    def _advance_news(self) -> None:
        if not self.paused:
            self.widgets[_NEWS].advance()

    # --- actions ---

    def action_toggle_pause(self) -> None:
        self.paused = not self.paused
        news = self.widgets.get(_NEWS)
        if news is not None:
            news.paused = self.paused
            news.refresh_title()

    def _open(self, option) -> None:
        if option is not None and option.id:
            headline = str(option.prompt).lstrip("• ").strip()
            self.push_screen(ArticleScreen(option.id, headline))

    def action_rates_detail(self) -> None:
        panel = self.widgets.get(_RATES)
        if isinstance(panel, RatesPanel):
            panel.action_detail()

    def action_open(self) -> None:
        f = self.focused
        if isinstance(f, DataPanel):
            f.open_detail()
        elif isinstance(f, NewsPanel) and f.highlighted is not None:
            self._open(f.get_option_at_index(f.highlighted))

    def action_focus_panel(self, direction: str) -> None:
        """←/→ move focus between the interactive panels (incl. into the left
        column from news)."""
        panels = [w for w in self.widgets.values() if isinstance(w, (DataPanel, NewsPanel))]
        if not panels:
            return
        step = 1 if direction == "next" else -1
        try:
            i = panels.index(self.focused) + step
        except ValueError:
            i = 0
        panels[i % len(panels)].focus()

    def action_settings(self) -> None:
        self.push_screen(SettingsScreen())

    # --- live column resize (Issue #3) ---

    def _apply_side_width(self, width: int) -> None:
        """Set the width of every fixed (non-flexing) side column."""
        for node in self.query(".side"):
            node.styles.width = width

    def _max_side_width(self) -> int:
        """Widest a side column may get while leaving the flexing column room.
        Shared across all side columns, so the ceiling shrinks with their count."""
        n_sides = max(1, len(self.columns) - 1)  # last column always flexes
        return max(_MIN_SIDE_WIDTH, (self.size.width - _FILL_FLOOR) // n_sides)

    def action_nudge_width(self, direction: int) -> None:
        """`[` / `]` widen or narrow the fixed side column(s) live, then persist
        the new width to [dashboard].left_width so it survives a restart."""
        if len(self.columns) < 2:
            return  # single column: nothing flexes beside it, so width is moot
        cur = int(self.left_width or _DEFAULT_SIDE_WIDTH)
        new = cur + direction * _WIDTH_STEP
        new = max(_MIN_SIDE_WIDTH, min(new, self._max_side_width()))
        if new == cur:
            return  # already at a bound — don't thrash the file
        self.left_width = new
        self._apply_side_width(new)
        self._persist_left_width(new)
        self.notify(f"Side column width: {new}", timeout=1.5)

    # --- settings persistence ---

    def setting_values(self, table: str, key: str) -> list[str]:
        """Current value of a list-valued config field, from live in-memory cfg."""
        return list(self.cfg.get(table, {}).get(key, []))

    def save_setting(self, table: str, key: str, values: list[str]) -> None:
        """Persist a list field to config.toml, update in-memory cfg, and refetch
        the affected panel now so the edit shows without waiting for the timer."""
        from .configwrite import set_list

        set_list(table, key, values)
        self.cfg.setdefault(table, {})[key] = list(values)
        src = self.sources.get(table)
        if src is not None:
            src.config = self.cfg[table]  # keep the live source reading the new value
            self._kickoff(table)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if isinstance(event.option_list, NewsPanel):  # DataPanels handle their own
            self._open(event.option)

    def _persist_left_width(self, width: int) -> None:
        """Write the nudged side-column width into [dashboard].left_width via
        tomlkit so config.toml's comments survive (same path the Settings editor
        uses for list fields)."""
        from .configwrite import set_value

        set_value("dashboard", "left_width", width)
        self.cfg.setdefault("dashboard", {})["left_width"] = width

    def _persist_theme(self, theme: str) -> None:
        """Write the theme into config.toml's [dashboard] table. Idempotent —
        a no-op if config already has this theme (palette previews don't thrash
        the file)."""
        import re

        from .app import _find_config

        path = _find_config()
        text = path.read_text()
        if re.search(r'(?m)^\s*theme\s*=\s*"%s"\s*$' % re.escape(theme), text):
            return  # already persisted
        line = f'theme = "{theme}"'
        if re.search(r"(?m)^\s*theme\s*=", text):
            text = re.sub(r"(?m)^\s*theme\s*=.*$", line, text, count=1)
        elif re.search(r"(?m)^\[dashboard\]", text):
            text = re.sub(r"(?m)^(\[dashboard\].*)$", r"\1\n" + line, text, count=1)
        else:
            text = f"[dashboard]\n{line}\n\n" + text
        path.write_text(text)


def main(argv: list[str] | None = None) -> None:
    import argparse

    ap = argparse.ArgumentParser(prog="tickr", description="Ambient terminal feeds of things that move.")
    sub = ap.add_subparsers(dest="cmd")
    cat = sub.add_parser("catalog", help="list curated news topics + ticker sets (or one entry's detail)")
    cat.add_argument("name", nargs="?", help="topic or ticker-set name to show in detail")
    args = ap.parse_args(argv)

    if args.cmd == "catalog":
        from .catalog import render_catalog

        print(render_catalog(args.name))
        return

    discover_widgets()  # register ~/.config/tickr/widgets/*.py before sources load
    TickrApp(load_config()).run()


if __name__ == "__main__":
    main()
