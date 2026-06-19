"""Tests for user-widget discovery (stdlib unittest — no extra deps).

Run: python -m unittest tests.test_userdir
"""

from __future__ import annotations

import sys
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tickr.sources.base import Source
from tickr.sources.userdir import load_user_widgets

_GOOD = """
from tickr.sources.base import Source

class MyPanel(Source):
    title = "MINE"
    name = "mine"
    def fetch(self): return 1
    def render(self, data): return str(data)
"""

_NO_NAME = """
from tickr.sources.base import Source

class NoName(Source):
    title = "NONAME"
    def fetch(self): return 1
    def render(self, data): return str(data)
"""

_BROKEN = "this is not valid python ::: ="

_IMPORTS_BASE_ONLY = """
# A file that imports Source but defines no subclass must not register anything.
from tickr.sources.base import Source
X = 1
"""


def _write(d: Path, name: str, body: str) -> None:
    (d / name).write_text(textwrap.dedent(body))


class LoadUserWidgetsTest(unittest.TestCase):
    def _load(self, files: dict[str, str]) -> tuple[dict, list[str]]:
        with TemporaryDirectory() as tmp:
            d = Path(tmp)
            for n, b in files.items():
                _write(d, n, b)
            registry: dict[str, type[Source]] = {}
            names = load_user_widgets(registry, dir_path=d)
            return registry, names

    def test_registers_by_name_attr(self):
        registry, names = self._load({"anything.py": _GOOD})
        self.assertEqual(names, ["mine"])
        self.assertIn("mine", registry)
        self.assertTrue(issubclass(registry["mine"], Source))

    def test_falls_back_to_filename(self):
        registry, names = self._load({"weather.py": _NO_NAME})
        self.assertEqual(names, ["weather"])
        self.assertIn("weather", registry)

    def test_broken_widget_is_skipped_not_raised(self):
        registry, names = self._load({"ok.py": _GOOD, "bad.py": _BROKEN})
        # bad.py is skipped; the good one still loads.
        self.assertEqual(names, ["mine"])
        self.assertIn("mine", registry)

    def test_file_with_no_source_subclass_skipped(self):
        registry, names = self._load({"helper.py": _IMPORTS_BASE_ONLY})
        self.assertEqual(names, [])
        self.assertEqual(registry, {})

    def test_underscore_files_ignored(self):
        registry, names = self._load({"_priv.py": _GOOD})
        self.assertEqual(names, [])

    def test_missing_dir_returns_empty(self):
        names = load_user_widgets({}, dir_path=Path("/no/such/tickr/widgets"))
        self.assertEqual(names, [])

    def test_does_not_register_base_class(self):
        registry, names = self._load({"ok.py": _GOOD})
        self.assertNotIn("Source", registry)
        self.assertNotIn(Source, registry.values())


if __name__ == "__main__":
    sys.exit(unittest.main())
