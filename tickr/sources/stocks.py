from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from http.cookiejar import CookieJar

from rich.console import Group
from rich.table import Table
from rich.text import Text

from .base import Source

# Yahoo Finance quote endpoint — unofficial, but one request returns every
# symbol (batched) and gives true day-change vs. previous close, real index
# symbols (^IXIC, ^GSPC), and pre/after-hours market state. A 15-name watchlist
# polled each minute is ~1 request/min. Needs a cookie+crumb handshake.
#
# If Yahoo ever breaks this, swapping to a keyed provider (e.g. Finnhub) is a
# self-contained change to this file — nothing else in tickr depends on it.
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_PRIMER = "https://fc.yahoo.com"
_CRUMB = "https://query1.finance.yahoo.com/v1/test/getcrumb"
_QUOTE = "https://query1.finance.yahoo.com/v7/finance/quote?symbols={syms}&crumb={crumb}"

# Yahoo marketState -> short badge.
_STATE = {
    "REGULAR": "OPEN",
    "PRE": "PRE",
    "PREPRE": "PRE",
    "POST": "AFTER",
    "POSTPOST": "AFTER",
    "CLOSED": "CLOSED",
}


# Friendly display labels for index symbols (Yahoo carets read poorly).
_LABELS = {"^GSPC": "S&P", "^IXIC": "NASDAQ", "^DJI": "DOW", "^RUT": "RUSSELL", "GC=F": "GOLD"}


@dataclass
class Quote:
    symbol: str
    name: str
    last: float | None
    change_pct: float | None  # true day change vs. previous close
    state: str = ""
    raw: dict = field(default_factory=dict)  # full Yahoo quote, for the detail popup


def _human(n) -> str:
    if not isinstance(n, (int, float)):
        return "—"
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= div:
            return f"{n / div:,.2f}{suf}"
    return f"{n:,.0f}"


class _Yahoo:
    """Cookie+crumb Yahoo client. Re-primes automatically on auth failure."""

    def __init__(self):
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )
        self._crumb: str | None = None

    def _get(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with self._opener.open(req, timeout=10) as r:
            return r.read()

    def _prime(self) -> None:
        try:
            self._get(_PRIMER)  # seeds cookies; a 404 here is fine
        except Exception:
            pass
        crumb = self._get(_CRUMB).decode("utf-8", "replace").strip()
        if not crumb or "<" in crumb:
            raise RuntimeError("could not obtain Yahoo crumb")
        self._crumb = crumb

    def quotes(self, symbols: list[str]) -> list[dict]:
        syms = urllib.parse.quote(",".join(symbols))
        last_err: Exception | None = None
        for _ in range(2):  # one retry: re-prime crumb if it expired
            try:
                if self._crumb is None:
                    self._prime()
                url = _QUOTE.format(syms=syms, crumb=urllib.parse.quote(self._crumb))
                data = json.loads(self._get(url))
                return data.get("quoteResponse", {}).get("result", [])
            except Exception as e:
                last_err = e
                self._crumb = None
        raise RuntimeError(f"Yahoo quote failed: {last_err}")


class StocksSource(Source):
    title = "STOCKS"
    interactive = True

    def __init__(self, config):
        super().__init__(config)
        self._yahoo = _Yahoo()
        self._state = ""

    def fetch(self) -> list[Quote]:
        from ..catalog import tickers_for

        # `sets` names expand to curated catalog symbols and merge with any
        # explicit `tickers`, so config can say sets = ["indices", "gold"].
        raw = list(self.config.get("tickers", [])) + tickers_for(self.config.get("sets", []))
        symbols: list[str] = []
        for t in raw:
            s = str(t).strip().upper()
            if s and s not in symbols:
                symbols.append(s)
        by_symbol = {q.get("symbol", "").upper(): q for q in self._yahoo.quotes(symbols)}
        quotes: list[Quote] = []
        for sym in symbols:
            q = by_symbol.get(sym)
            if not q:
                quotes.append(Quote(sym, "", None, None))
                continue
            quotes.append(
                Quote(
                    symbol=sym,
                    name=(q.get("shortName") or q.get("longName") or ""),
                    last=q.get("regularMarketPrice"),
                    change_pct=q.get("regularMarketChangePercent"),
                    state=_STATE.get(q.get("marketState", ""), q.get("marketState", "")),
                    raw=q,
                )
            )
        self._state = next((x.state for x in quotes if x.state), "")
        return quotes

    def status(self) -> str:
        return self._state

    def render(self, data: list[Quote]) -> Table:
        t = Table.grid(padding=(0, 2), expand=False)
        t.add_column("sym", justify="left", no_wrap=True)
        t.add_column("last", justify="right", no_wrap=True)
        t.add_column("chg", justify="right", no_wrap=True)
        for q in data or []:
            label = _LABELS.get(q.symbol, q.symbol.lstrip("^"))
            if q.last is None:
                t.add_row(Text(label, style="bold"), Text("—", style="dim"), Text("·", style="dim"))
                continue
            up = (q.change_pct or 0) >= 0
            color = "green" if up else "red"
            if q.change_pct is None:
                chg = Text("—", style="dim")
            else:
                arrow = "▲" if up else "▼"
                chg = Text(f"{arrow}{abs(q.change_pct):.2f}%", style=color)
            t.add_row(Text(label, style="bold"), Text(f"{q.last:,.2f}"), chg)
        return t

    def list_rows(self, data: list[Quote], width: int) -> list[tuple[Text, str]]:
        price_w, chg_w = 11, 9
        label_w = max(6, width - price_w - chg_w - 2)
        rows: list[tuple[Text, str]] = []
        for q in data or []:
            label = _LABELS.get(q.symbol, q.symbol.lstrip("^"))
            label = (label[: label_w - 1] + "…") if len(label) > label_w else label.ljust(label_w)
            t = Text()
            t.append(label, style="bold")
            if q.last is None:
                t.append(f"{'—':>{price_w}}", style="dim")
                t.append(f"{'·':>{chg_w + 1}}", style="dim")
            else:
                up = (q.change_pct or 0) >= 0
                t.append(f"{q.last:>{price_w},.2f}")
                chg = "—" if q.change_pct is None else f"{'▲' if up else '▼'}{abs(q.change_pct):.2f}%"
                t.append(f"{chg:>{chg_w + 1}}", style="dim" if q.change_pct is None else ("green" if up else "red"))
            rows.append((t, q.symbol))
        return rows

    def detail(self, key: str, data: list[Quote]) -> Group:
        q = next((x for x in (data or []) if x.symbol == key), None)
        if q is None:
            return Group(Text("(no data)", style="dim"))
        r = q.raw
        up = (q.change_pct or 0) >= 0
        head = Text()
        head.append(f"{q.last:,.2f}" if q.last is not None else "—", style="bold white")
        if q.change_pct is not None:
            chg = r.get("regularMarketChange")
            head.append(f"   {'▲' if up else '▼'}{abs(chg):,.2f} ({abs(q.change_pct):.2f}%)",
                        style="green" if up else "red")
        if q.state:
            head.append(f"   {q.state}", style="yellow")

        t = Table.grid(padding=(0, 2))
        t.add_column(style="grey70", no_wrap=True)
        t.add_column(justify="right", no_wrap=True)
        rng = lambda lo, hi: (f"{r.get(lo):,.2f} – {r.get(hi):,.2f}"
                              if isinstance(r.get(lo), (int, float)) else "—")
        num = lambda k, p=2: (f"{r.get(k):,.{p}f}" if isinstance(r.get(k), (int, float)) else "—")
        for k, v in [
            ("Open", num("regularMarketOpen")),
            ("Prev close", num("regularMarketPreviousClose")),
            ("Day range", rng("regularMarketDayLow", "regularMarketDayHigh")),
            ("52-wk range", rng("fiftyTwoWeekLow", "fiftyTwoWeekHigh")),
            ("Volume", _human(r.get("regularMarketVolume"))),
            ("Mkt cap", _human(r.get("marketCap"))),
        ]:
            t.add_row(k, v)
        name = q.name or q.symbol
        return Group(Text(name, style="bold cyan"), Text(q.symbol, style="dim"), Text(""), head, Text(""), t)
