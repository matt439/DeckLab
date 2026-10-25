"""The viewer stays dark in both themes; ordinary links must remain readable."""
import re
import unittest
from decklab.tests.test_web import WEB


def properties(body):
    return {key: value.strip() for key, value in re.findall(r"(--[\w-]+):\s*([^;]+);", body)}


def luminance(value, props):
    while value.startswith("var("):
        value = props[re.fullmatch(r"var\((--[\w-]+)\)", value).group(1)]
    if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        rgb = [int(value[i:i + 2], 16) for i in (1, 3, 5)]
    else:
        assert re.fullmatch(r"rgb\(\s*\d+\s+\d+\s+\d+\s*\)", value), value
        rgb = [int(number) for number in re.findall(r"\d+", value)]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in (n / 255 for n in rgb)]
    return sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))


class ViewerLinkContrastTests(unittest.TestCase):
    def test_ordinary_viewer_links_pass_text_contrast_in_both_page_themes(self):
        tokens = re.sub(r"/\*.*?\*/", "", (WEB / "tokens.css").read_text(encoding="utf-8"), flags=re.S)
        base = properties(re.search(r":root\s*\{([^}]+)\}", tokens, re.S).group(1))
        dark = properties(re.search(r':root\[data-theme="dark"\]\s*\{([^}]+)\}', tokens, re.S).group(1))
        css = (WEB / "cards-ui.css").read_text(encoding="utf-8")
        links = re.search(r"\.viewer-text a\s*\{([^}]+)\}", css).group(1)
        panel = re.search(r"\.viewer-text\s*\{([^}]+)\}", css).group(1)
        color = re.search(r"color:\s*([^;]+);", links).group(1).strip()
        background = re.search(r"background:\s*([^;]+);", panel).group(1).strip()
        for theme, overrides in (("light", {}), ("dark", dark)):
            with self.subTest(theme=theme):
                props = {**base, **overrides}
                a, b = luminance(color, props), luminance(background, props)
                self.assertGreaterEqual((max(a, b) + .05) / (min(a, b) + .05), 4.5)
