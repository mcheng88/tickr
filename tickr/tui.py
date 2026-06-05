from __future__ import annotations

import webbrowser
from functools import partial

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, OptionList, Static
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
        self.add_options([Option(f"• {t}", id=(link or None)) for t, link in items])
        if keep is not None and self.option_count:
            self.highlighted = min(keep, self.option_count - 1)

    def advance(self) -> None:
        if self.option_count:
            cur = self.highlighted if self.highlighted is not None else -1
            self.highlighted = (cur + 1) % self.option_count


class ArticleScreen(ModalScreen):
    """In-terminal reader: fetches the article and shows extracted text. Bloomberg-
    style — read without leaving the terminal. 'b' falls back to the browser."""

    CSS = """
    ArticleScreen { align: center middle; }
    #reader { width: 84%; height: 86%; border: round #5f5f5f; background: $surface; padding: 1 2; }
    #reader-title { text-style: bold; color: $accent; }
    #reader-meta { color: $text-muted; }
    #reader-body { margin-top: 1; }
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
        with VerticalScroll(id="reader"):
            yield Static(self.headline, id="reader-title")
            yield Static(self.url, id="reader-meta")
            yield Static("Loading…", id="reader-body")
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


class TickrApp(App):
    TITLE = "tickr"
    CSS = """
    Screen { background: $background; }
    .side { width: 56; height: 1fr; }
    .fill { width: 1fr; height: 1fr; }
    SectionPanel { border: round #5f5f5f; padding: 0 1; width: 1fr; height: auto; margin-bottom: 1; }
    NewsPanel { border: round #5f5f5f; padding: 0 1; height: 1fr; }
    NewsPanel > .option-list--option-highlighted { background: $accent 30%; color: $text; }
    """
    BINDINGS = [
        ("space", "toggle_pause", "Pause/resume scroll"),
        ("o", "open", "Open highlighted"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        dash = cfg.get("dashboard", {})
        self.default_refresh = int(dash.get("refresh_seconds", 60))
        self.scroll_seconds = float(cfg.get(_NEWS, {}).get("scroll_seconds", 4))
        self.left_width = dash.get("left_width")
        self.columns = _layout_columns(cfg)
        self.names = [n for col in self.columns for n in col]
        self.sources = {n: load_source(cfg, n) for n in self.names}
        self.widgets = {
            n: (NewsPanel(self.sources[n]) if n == _NEWS else SectionPanel(self.sources[n]))
            for n in self.names
        }
        self.paused = False

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
        news = self.widgets.get(_NEWS)
        if news is not None and news.highlighted is not None:
            self._open(news.get_option_at_index(news.highlighted))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._open(event.option)


def main(argv: list[str] | None = None) -> None:
    TickrApp(load_config()).run()


if __name__ == "__main__":
    main()
