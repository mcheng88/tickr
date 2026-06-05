from __future__ import annotations

from .base import Source
from .claude_usage import ClaudeUsageSource
from .news import NewsSource
from .stocks import StocksSource

#: Registry of available sources. Each backlog panel (crypto, predict, oddities)
#: registers itself here.
SOURCES: dict[str, type[Source]] = {
    "stocks": StocksSource,
    "claude_usage": ClaudeUsageSource,
    "news": NewsSource,
}


def load_source(cfg: dict, name: str | None = None) -> Source:
    if name is None:
        name = cfg.get("dashboard", {}).get("source", "stocks")
    if name not in SOURCES:
        raise SystemExit(f"Unknown source '{name}'. Available: {', '.join(SOURCES)}")
    return SOURCES[name](cfg.get(name, {}))
