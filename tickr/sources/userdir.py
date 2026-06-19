from __future__ import annotations

import importlib.util
import inspect
import os
import sys
import traceback
from pathlib import Path

from .base import Source

# Where personal/experimental panels live, so a new widget is a file you drop in
# rather than a module inside the installed package. Override with
# ``TICKR_WIDGETS_DIR`` (handy for trying a dir out), otherwise follow XDG.
_ENV = "TICKR_WIDGETS_DIR"


def widgets_dir() -> Path:
    env = os.environ.get(_ENV)
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "tickr" / "widgets"


def _warn(msg: str) -> None:
    # stderr, not the panel — discovery runs before the TUI takes the screen, so a
    # broken widget surfaces in the scrollback instead of vanishing behind Live.
    print(f"tickr: {msg}", file=sys.stderr)


def _import_file(fp: Path):
    """Import a standalone .py file under a private namespace so user widgets
    can't collide with each other (or with the package) on bare module names."""
    mod_name = f"tickr_user_widgets.{fp.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, fp)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot create import spec for {fp}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod  # so dataclasses / pickling / relative lookups work
    spec.loader.exec_module(mod)
    return mod


def _sources_in(mod) -> list[type[Source]]:
    found: list[type[Source]] = []
    for obj in vars(mod).values():
        if not (isinstance(obj, type) and issubclass(obj, Source)):
            continue
        if obj is Source or obj.__module__ != mod.__name__:
            continue  # skip the base class and anything merely imported into the file
        if inspect.isabstract(obj):
            continue  # skip intermediate abstract bases a widget might define
        found.append(obj)
    return found


def load_user_widgets(registry: dict[str, type[Source]], dir_path: Path | None = None) -> list[str]:
    """Discover ``Source`` subclasses in the user widgets dir and add them to
    ``registry`` (the ``SOURCES`` dict), keyed by each class's ``name`` attribute
    or, lacking one, the file stem.

    Fail-soft by contract: a missing dir, an unreadable file, an import error, or
    a widget that explodes is reported on stderr and skipped — it never raises,
    so one bad widget can't take down the app. Returns the names registered.
    """
    d = dir_path or widgets_dir()
    registered: list[str] = []
    try:
        if not d.is_dir():
            return registered
        files = sorted(d.glob("*.py"))
    except OSError as e:
        _warn(f"could not read widgets dir {d}: {e}")
        return registered

    for fp in files:
        if fp.name.startswith("_"):
            continue  # _helpers.py etc. are support files, not widgets
        try:
            mod = _import_file(fp)
            classes = _sources_in(mod)
        except Exception:
            _warn(f"skipped widget {fp.name} (failed to import):\n{traceback.format_exc().rstrip()}")
            continue
        if not classes:
            _warn(f"widget {fp.name} defines no Source subclass — skipped")
            continue
        for cls in classes:
            key = str(getattr(cls, "name", "") or fp.stem)
            if key in registry and registry[key] is not cls:
                _warn(f"widget '{key}' from {fp.name} overrides an existing source")
            registry[key] = cls
            registered.append(key)
    return registered
