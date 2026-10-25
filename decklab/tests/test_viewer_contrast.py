"""The viewer stays dark in both themes; ordinary links must remain readable."""
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


def properties(body):
    return {key: value.strip() for key, value in re.findall(r"(--[\w-]+):\s*([^;]+);", body)}


def resolve(value, props):
    seen = set()
    while value.startswith("var("):
        key = re.fullmatch(r"var\((--[\w-]+)\)", value).group(1)
        assert key not in seen, f"Cyclic token alias: {key}"
        seen.add(key)
        value = props[key]
    return value


def luminance(value, props):
    value = resolve(value, props)
    if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        rgb = [int(value[i:i + 2], 16) for i in (1, 3, 5)]
    else:
        assert re.fullmatch(r"rgb\(\s*\d+\s+\d+\s+\d+\s*\)", value), value
        rgb = [int(number) for number in re.findall(r"\d+", value)]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in (n / 255 for n in rgb)]
    return sum(v * weight for v, weight in zip(linear, (.2126, .7152, .0722)))


def theme_properties():
    tokens = re.sub(r"/\*.*?\*/", "", (WEB / "tokens.css").read_text(encoding="utf-8"), flags=re.S)
    base = properties(re.search(r":root\s*\{([^}]+)\}", tokens, re.S).group(1))
    dark = properties(re.search(r':root\[data-theme="dark"\]\s*\{([^}]+)\}', tokens, re.S).group(1))
    return {"light": base, "dark": {**base, **dark}}


STRIPE_CODES = "wubrgc"
LIGHT_STRIPES = dict(zip(STRIPE_CODES, ("#e2c472", "#2f7fbf", "#5a4f4b", "#d9473e", "#1f8a55", "#8f8a85")))
DARK_STRIPES = dict(zip(STRIPE_CODES, ("#e2c472", "#4a97d6", "#8c7f7a", "#e5594f", "#2fa86a", "#a39e99")))


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

    def test_normal_page_stripe_palettes_keep_their_recorded_resolved_values(self):
        for theme, props in theme_properties().items():
            with self.subTest(theme=theme):
                expected = LIGHT_STRIPES if theme == "light" else DARK_STRIPES
                self.assertEqual({code: resolve(f"var(--stripe-{code})", props) for code in STRIPE_CODES}, expected)
                self.assertEqual({code: resolve(f"var(--stripe-{code}-dark)", props) for code in STRIPE_CODES}, DARK_STRIPES)

    def test_saved_holder_swatches_use_all_six_dark_colors_only_in_the_viewer_and_pass_cue_contrast(self):
        css = re.sub(r"/\*.*?\*/", "", (WEB / "cards-ui.css").read_text(encoding="utf-8"), flags=re.S)
        selector = ".viewer-text .col-packing-hints .deck-swatch"
        rules = [(rule.strip(), properties(body)) for rule, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]
        dark_rules = [(rule, props) for rule, props in rules
                      if any(f"var(--stripe-{code}-dark)" in props.values() for code in STRIPE_CODES)]
        self.assertEqual([rule for rule, _ in dark_rules], [selector])
        local = dark_rules[0][1]
        self.assertEqual(local, {f"--stripe-{code}": f"var(--stripe-{code}-dark)" for code in STRIPE_CODES})
        panel = re.search(r"\.viewer-text\s*\{([^}]+)\}", css).group(1)
        background = re.search(r"background:\s*([^;]+);", panel).group(1).strip()
        for theme, page_props in theme_properties().items():
            props = {**page_props, **local}
            for code in STRIPE_CODES:
                with self.subTest(theme=theme, code=code):
                    value = resolve(f"var(--stripe-{code})", props)
                    self.assertEqual(value, DARK_STRIPES[code])
                    a, b = luminance(value, props), luminance(background, props)
                    # These tiny swatches are decorative identity cues; link text has its own 4.5:1 check.
                    self.assertGreaterEqual((max(a, b) + .05) / (min(a, b) + .05), 3.0)
