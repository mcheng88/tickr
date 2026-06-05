from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from http.cookiejar import CookieJar

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
_LABELS = {"^GSPC": "S&P", "^IXIC": "NASDAQ", "^DJI": "DOW", "^RUT": "RUSSELL"}


@dataclass
class Quote:
    symbol: str
    name: str
    last: float | None
    change_pct: float | None  # true day change vs. previous close
    state: str = ""


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

    def __init__(self, config):
        super().__init__(config)
        self._yahoo = _Yahoo()
        self._state = ""

    def fetch(self) -> list[Quote]:
        symbols = [str(t).strip().upper() for t in self.config.get("tickers", []) if str(t).strip()]
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
