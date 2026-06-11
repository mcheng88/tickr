from __future__ import annotations

import webbrowser
from functools import partial

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, OptionList, Static
from textual.widgets.option_list import Option

from .app import _layout_columns, load_config
from .reader import fetch_article
from .sources import load_source

# Sources are non-interactive panels (a rich renderable refreshed on a timer);
# "news" is special — an interactive, scrollable, selectable headline list.
_NEWS = "news"


class SectionPanel(Static):
    """A non-interactive source panel: titled border + rendered body, refreshed
    on the source's own interval."""

    def __init__(self, source):
        super().__init__()
        self.source = source
        self.border_title = source.title

    def apply(self, data) -> None:
        st = self.source.status()
        self.border_title = f"{self.source.title}  {st}".rstrip()
        self.update(self.source.render(data))


class NewsPanel(OptionList):
    """Scrollable, selectable headline feed. Auto-advances (ambient) unless
    paused; arrows/j-k scroll; enter or click opens the article."""

    def __init__(self, source):
        super().__init__()
        self.source = source
        self.border_title = "NEWS"

    def apply(self, items: list[tuple[str, str]]) -> None:
        keep = self.highlighted
        self.clear_options()
        # Option ids must be unique; feeds occasionally repeat a URL, so drop
        # later duplicates (items without a link keep id=None, never collide).
        seen: set[str] = set()
        opts = []
        for t, link in items:
            if link and link in seen:
                continue
            if link:
                seen.add(link)
            # Text() prompt → rendered literally; a headline with '[' won't be
            # mis-parsed as Rich markup (would crash the OptionList).
            opts.append(Option(Text(f"• {t}"), id=(link or None)))
        self.add_options(opts)
        if keep is not None and self.option_count:
            self.highlighted = min(keep, self.option_count - 1)

    def advance(self) -> None:
        if self.option_count:
            cur = self.highlighted if self.highlighted is not None else -1
            self.highlighted = (cur + 1) % self.option_count


class DataPanel(OptionList):
    """Interactive tabular panel (stocks, predict). ↑/↓ moves the row cursor;
    enter / 'o' / click opens a detail popup for the highlighted row."""

    def __init__(self, source):
        super().__init__()
        self.source = source
        self.border_title = source.title
        self._data = None

    def apply(self, data) -> None:
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
        st = self.source.status()
        self.border_title = f"{self.source.title}  {st}".rstrip()

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
    BINDINGS = [("escape", "close", "Done")]

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
                "Type a value + Enter to add · Enter/click a row to remove · Esc when done",
                id="edithint",
            )
            yield Input(placeholder="add new value…", id="editadd")
            yield OptionList(id="editlist")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_list()
        self.query_one("#editadd", Input).focus()

    def _refresh_list(self) -> None:
        ol = self.query_one("#editlist", OptionList)
        ol.clear_options()
        if not self.values:
            ol.add_option(Option(Text("(none — empty)"), id=None))
            return
        # markup=False semantics: values can contain '[' (URLs, etc.) — render
        # literally via Text(). id is the position so removal is unambiguous.
        ol.add_options([Option(Text(f"• {v}"), id=str(i)) for i, v in enumerate(self.values)])

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
        self._refresh_list()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option.id is None:  # the "(none)" placeholder
            return
        del self.values[int(event.option.id)]
        self._save()
        self._refresh_list()

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
    .side { width: 56; height: 1fr; }
    .fill { width: 1fr; height: 1fr; }
    SectionPanel { border: round #5f5f5f; padding: 0 1; width: 1fr; height: auto; margin-bottom: 0; }
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
    BINDINGS = [
        ("space", "toggle_pause", "Pause/resume scroll"),
        ("left", "focus_panel('prev')", "Prev panel"),
        ("right", "focus_panel('next')", "Next panel"),
        ("o", "open", "Open / detail"),
        ("s", "settings", "Settings"),
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
            for node in self.query(".side"):
                node.styles.width = int(self.left_width)
        for name in self.names:
            self._kickoff(name)  # initial fetch
            interval = int(self.cfg.get(name, {}).get("refresh_seconds", self.default_refresh))
            self.set_interval(interval, partial(self._kickoff, name))
        if _NEWS in self.widgets:
            self.set_interval(self.scroll_seconds, self._advance_news)
            self.widgets[_NEWS].focus()
        self._theme_ready = True  # from here on, theme changes autosave

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
        if not data:  # failed or empty → retry soon instead of waiting the full interval
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
            news.border_title = "NEWS  (paused)" if self.paused else "NEWS"

    def _open(self, option) -> None:
        if option is not None and option.id:
            headline = str(option.prompt).lstrip("• ").strip()
            self.push_screen(ArticleScreen(option.id, headline))

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

    TickrApp(load_config()).run()


if __name__ == "__main__":
    main()
