"""Tests of the CodeNOW logo on every hub page shell (lib/cn_hub_logo.py): the index, the data views, the error
pages and Try it each carry the logo once, linked to the index, and the mark as an inline favicon.

    python3 -m unittest discover -s tests
"""
import base64
import pathlib
import re
import sys
import unittest
import xml.dom.minidom

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
import cn_hub_logo  # noqa: E402
import cn_hub_render  # noqa: E402
import cn_hub_render_a2a  # noqa: E402
import cn_hub_render_runs  # noqa: E402
import cn_hub_render_valkey  # noqa: E402

P = "sandbox-alpha"
CARD = {"name": "alpha", "skills": [{"id": "advice", "description": "d"}]}


def pages():
    return {
        "index": cn_hub_render.page([]),
        "runs": cn_hub_render_runs.runs_page(P, {"runs": [{"run_id": "run0001", "status": "completed"}]}),
        "run": cn_hub_render_runs.run_page(P, {"run": {"run_id": "run0001"}}),
        "not found": cn_hub_render_runs.shell("Not found", P, '<p class="err">No such sandbox.</p>'),
        "too large": cn_hub_render_runs.shell("Too large", "", "<p>x</p>"),
        "valkey": cn_hub_render_valkey.keys_page(P, {"keys": [], "complete": True}),
        "valkey key": cn_hub_render_valkey.key_page(P, {"key": "k", "type": "none"}),
        "search": cn_hub_render_valkey.search_page(P, {"q": ""}),
        "try": cn_hub_render_a2a.try_page(P, "csrf", CARD, "http://localhost:1/", {"label": "you"}, "shadow"),
        "try, no card": cn_hub_render_a2a.try_page(P, "csrf", None, "", {}, "", "down"),
    }


class LogoTest(unittest.TestCase):
    def test_every_page_shell_has_the_logo_once_linked_to_the_index(self):
        for name, html in pages().items():
            with self.subTest(page=name):
                self.assertEqual(html.count(cn_hub_logo.LOGO_SVG), 1)
                self.assertEqual(html.count('aria-label="CodeNOW"'), 1)
                self.assertEqual(html.count('class="cnlogo"'), 1)
                self.assertIn(f'<a class="home" href="/" title="All sandboxes">{cn_hub_logo.LOGO_SVG}</a><h1>', html)
                self.assertEqual(html.count("<h1>"), 1)
                self.assertEqual(html.count(f'id="{cn_hub_logo.GRADIENT_ID}"'), 1)
                self.assertEqual(len(re.findall(r'\bid="cnlogo-g"', html)), 1)
                self.assertNotIn("#222533", html)
                self.assertEqual(html.count(cn_hub_logo.FAVICON_LINK), 1)
                self.assertLess(html.index(cn_hub_logo.FAVICON_LINK), html.index("</head>"))
                self.assertIn(".cnlogo{", html)

    def test_logo_markup(self):
        svg = cn_hub_logo.LOGO_SVG
        self.assertIn('role="img"', svg)
        self.assertEqual(svg.count('fill="url(#cnlogo-g)"'), 1)
        self.assertEqual(re.findall(r'url\(#([^)]+)\)', svg), ["cnlogo-g"])
        self.assertEqual(svg.count('fill="currentColor"'), 7)
        self.assertNotIn("http", svg)     # inline in HTML: no xmlns, no external reference
        xml.dom.minidom.parseString(svg)

    def test_favicon_is_the_mark_only(self):
        link = cn_hub_logo.FAVICON_LINK
        self.assertTrue(link.startswith('<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,'))
        mark = base64.b64decode(link.split("base64,", 1)[1].rstrip('">')).decode("ascii")
        self.assertIn('viewBox="0 0 37 41"', mark)
        self.assertNotIn("currentColor", mark)    # no wordmark
        self.assertIn('fill="url(#g)"', mark)
        xml.dom.minidom.parseString(mark)

    def test_title_is_escaped(self):
        row = cn_hub_logo.title_row('<script>x</script> & "y"')
        self.assertIn("<h1>&lt;script&gt;x&lt;/script&gt; &amp; &quot;y&quot;</h1>", row)
        self.assertNotIn("<script>", row)


if __name__ == "__main__":
    unittest.main()
