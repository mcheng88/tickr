from __future__ import annotations

from .base import Source
from .claude_usage import ClaudeUsageSource
from .news import NewsSource
from .predict import PredictSource
from .stocks import StocksSource
from .weather import WeatherSource

#: Registry of available sources. Each backlog panel (oddities, …) registers here.
SOURCES: dict[str, type[Source]] = {
    "stocks": StocksSource,
    "claude_usage": ClaudeUsageSource,
    "news": NewsSource,
    "predict": PredictSource,
    "weather": WeatherSource,
}


def load_source(cfg: dict, name: str | None = None) -> Source:
    if name is None:
        name = cfg.get("dashboard", {}).get("source", "stocks")
    if name not in SOURCES:
        raise SystemExit(f"Unknown source '{name}'. Available: {', '.join(SOURCES)}")
    return SOURCES[name](cfg.get(name, {}))
