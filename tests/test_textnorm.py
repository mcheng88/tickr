"""Tests for smart-punctuation normalization (stdlib unittest — no extra deps).

Run: python -m unittest tests.test_textnorm
"""

from __future__ import annotations

import unittest

from tickr.reader import _extract
from tickr.textnorm import normalize


class NormalizeTests(unittest.TestCase):
    def test_curly_double_quotes_become_ascii(self) -> None:
        self.assertEqual(normalize("“quoted”"), '"quoted"')

    def test_curly_single_quotes_and_apostrophe(self) -> None:
        self.assertEqual(
            normalize("prosecutor’s ‘office’"), "prosecutor's 'office'"
        )

    def test_dashes_and_ellipsis(self) -> None:
        self.assertEqual(normalize("a–b—c…"), "a-b--c...")

    def test_guillemets_and_primes(self) -> None:
        self.assertEqual(normalize("«x» 5′ 6″"), '"x" 5\' 6"')

    def test_nbsp_and_zero_width(self) -> None:
        self.assertEqual(normalize("a b"), "a b")  # non-breaking space -> space
        self.assertEqual(normalize("a​b"), "ab")   # zero-width space dropped

    def test_plain_ascii_untouched(self) -> None:
        s = 'Plain "text" with -- and ... already.'
        self.assertEqual(normalize(s), s)


class ReaderIntegrationTests(unittest.TestCase):
    def test_extract_normalizes_entities_and_glyphs(self) -> None:
        html = "<p>&ldquo;The prosecutor&rsquo;s office&rdquo; — case…</p>"
        out = _extract(html)
        for bad in ("“", "”", "’", "—", "…"):
            self.assertNotIn(bad, out)
        self.assertIn('"The prosecutor\'s office"', out)


if __name__ == "__main__":
    unittest.main()
