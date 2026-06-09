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

    #: If True, the panel is a focusable, selectable list (↑/↓ to move, enter to
    #: open a detail popup) instead of a static renderable. Such sources provide
    #: ``list_rows()`` + ``detail()`` instead of ``render()``.
    interactive: bool = False

    def __init__(self, config: dict[str, Any]):
        self.config = config

    @abstractmethod
    def fetch(self) -> Any:
        """Return fresh data, or raise on failure."""

    def render(self, data: Any) -> RenderableType:
        """Render ``data`` to a rich renderable. Must not raise. (Static panels
        only; interactive sources use ``list_rows``/``detail`` instead.)"""
        raise NotImplementedError

    def list_rows(self, data: Any, width: int) -> list[tuple[RenderableType, str]]:
        """Interactive sources: one ``(row_renderable, key)`` per selectable row.
        ``key`` is passed back to ``detail()``; ``width`` is the panel's inner
        width so rows can right-align columns."""
        return []

    def detail(self, key: str, data: Any) -> RenderableType:
        """Interactive sources: renderable shown in the row's detail popup."""
        return ""

    def status(self) -> str:
        """Optional one-word source status (e.g. market ``OPEN``/``CLOSED``).

        Empty string means no status badge.
        """
        return ""
