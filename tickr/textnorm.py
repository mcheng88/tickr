from __future__ import annotations

# Feed text (article HTML, RSS titles) routinely contains "smart" typographic
# punctuation — curly quotes, en/em dashes, ellipsis, non-breaking spaces. Many
# terminal fonts lack those glyphs and fall back to rendering the character's
# *name* (e.g. a curly double-quote shows up as the literal words "double
# quotation mark"). We don't control the reader's font, so normalize this
# punctuation to plain ASCII that renders identically everywhere before it hits
# the terminal. See mcheng88/tickr#15.
_PUNCT = {
    "‘": "'",   # ‘  left single quote
    "’": "'",   # ’  right single quote / apostrophe
    "‚": "'",   # ‚  single low-9 quote
    "‛": "'",   # ‛  single high-reversed-9 quote
    "“": '"',   # “  left double quote
    "”": '"',   # ”  right double quote
    "„": '"',   # „  double low-9 quote
    "‟": '"',   # ‟  double high-reversed-9 quote
    "′": "'",   # ′  prime
    "″": '"',   # ″  double prime
    "«": '"',   # «  left guillemet
    "»": '"',   # »  right guillemet
    "–": "-",   # –  en dash
    "—": "--",  # —  em dash
    "‐": "-",   # ‐  hyphen
    "‑": "-",   # ‑  non-breaking hyphen
    "‒": "-",   # ‒  figure dash
    "―": "--",  # ―  horizontal bar
    "…": "...", # …  horizontal ellipsis
    " ": " ",   #    non-breaking space
    " ": " ",   #    thin space
    " ": " ",   #    narrow no-break space
    "​": "",    #    zero-width space
    "﻿": "",    #    zero-width no-break space / BOM
}
_TABLE = {ord(k): v for k, v in _PUNCT.items()}


def normalize(text: str) -> str:
    """Replace smart typographic punctuation with plain-ASCII equivalents that
    render in any terminal font."""
    return text.translate(_TABLE)
