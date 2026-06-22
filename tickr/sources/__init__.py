from __future__ import annotations

from .base import Source
from .claude_usage import ClaudeUsageSource
from .news import NewsSource
from .predict import PredictSource
from .rates import RatesSource
from .stocks import StocksSource
from .userdir import load_user_widgets
from .weather import WeatherSource

#: Registry of available sources. Built-in panels live here; user panels dropped
#: into the widgets dir (see ``discover_widgets``) register themselves at startup.
SOURCES: dict[str, type[Source]] = {
    "stocks": StocksSource,
    "claude_usage": ClaudeUsageSource,
    "news": NewsSource,
    "predict": PredictSource,
    "weather": WeatherSource,
    "rates": RatesSource,
}

_discovered = False


def discover_widgets() -> list[str]:
    """Load user widgets from the widgets dir into ``SOURCES`` (idempotent).

    Call once at startup before :func:`load_source`. Returns the names newly
    registered (empty after the first call). Never raises — see
    :func:`tickr.sources.userdir.load_user_widgets`.
    """
    global _discovered
    if _discovered:
        return []
    _discovered = True
    return load_user_widgets(SOURCES)


def load_source(cfg: dict, name: str | None = None) -> Source:
    if name is None:
        name = cfg.get("dashboard", {}).get("source", "stocks")
    if name not in SOURCES:
        raise SystemExit(f"Unknown source '{name}'. Available: {', '.join(SOURCES)}")
    return SOURCES[name](cfg.get(name, {}))
