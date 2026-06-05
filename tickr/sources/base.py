from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from rich.console import RenderableType


class Source(ABC):
    """A tickr data source: ``fetch()`` pulls a little data, ``render()`` draws it.

    Every panel — stocks, crypto, prediction odds, news, oddities — is one of
    these. ``fetch()`` should be cheap and may raise on failure (the app keeps
    the last good frame and shows it going stale). ``render()`` must not raise.
    """

    #: Short title shown in the panel header, e.g. ``"STOCKS"``.
    title: str = "SOURCE"

    def __init__(self, config: dict[str, Any]):
        self.config = config

    @abstractmethod
    def fetch(self) -> Any:
        """Return fresh data, or raise on failure."""

    @abstractmethod
    def render(self, data: Any) -> RenderableType:
        """Render ``data`` to a rich renderable. Must not raise."""

    def status(self) -> str:
        """Optional one-word source status (e.g. market ``OPEN``/``CLOSED``).

        Empty string means no status badge.
        """
        return ""
