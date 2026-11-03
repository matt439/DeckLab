"""E3-S32: the deck page's "Against popular decks" part (gauntlet.css) never makes the page scroll sideways and
reads at the Matchups tab's other parts' widths. Static checks of the stylesheet's rules (no browser)."""
import re
import unittest

from decklab.tests.test_workspace_ui import WEB


def _rules(css):
    """{selector: declarations} for the top-level rules (phone first: media blocks left out), comments removed (a
    selector list's every selector gets the declarations; a later rule for the same selector is appended)."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*\s*\}", "", css)
    out = {}
    for sel, body in re.findall(r"([^{}@]+)\{([^{}]*)\}", css):
        for one in sel.split(","):
            key = " ".join(one.split())
            out[key] = out.get(key, "") + body
    return out


def _decl(body, prop):
    found = re.findall(rf"(?:^|[;\s]){re.escape(prop)}\s*:\s*([^;]+)", body)
    return found[-1].strip() if found else None


class GauntletWidthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = (WEB / "gauntlet.css").read_text(encoding="utf-8")
        cls.rules = _rules(cls.css)

    def rule(self, selector):
        self.assertIn(selector, self.rules, f"gauntlet.css has no rule for {selector}")
        return self.rules[selector]

    def test_every_child_of_the_part_may_shrink(self):
        """A grid item's automatic minimum is its min-content: the empty state's build command once pushed the
        page wider than a phone. The part's one column is minmax(0, 1fr) and its children may shrink."""
        self.assertEqual(_decl(self.rule(".gt-content"), "grid-template-columns"), "minmax(0, 1fr)")
        child = self.rule(".gt-content > *")
        self.assertEqual(_decl(child, "min-width"), "0")
        self.assertEqual(_decl(child, "max-width"), "100%")
        self.assertEqual(_decl(self.rule(".gt-layout"), "grid-template-columns"), "minmax(0, 1fr)")
        for sel in (".gt-section", ".gt-side", ".gt-main", ".gt-play", ".gt-groups-part"):
            self.assertEqual(_decl(self.rule(sel), "min-width"), "0", sel)

    def test_the_build_command_wraps_inside_the_column(self):
        command = self.rule(".gt-command")
        self.assertEqual(_decl(command, "max-width"), "100%")
        self.assertEqual(_decl(command, "white-space"), "pre-wrap")
        self.assertEqual(_decl(command, "overflow-wrap"), "anywhere")

    def test_long_names_and_notes_break(self):
        for sel in (".gt-name", ".gt-meta", ".gt-small", ".gt-caveat"):
            self.assertEqual(_decl(self.rule(sel), "overflow-wrap"), "anywhere", sel)

    def test_the_part_stops_at_readable_widths(self):
        self.assertEqual(_decl(self.rule(".gt-content"), "max-width"), "1400px")
        for sel in (".gt-content > .sub", ".gt-small", ".gt-caveat", ".gt-credit", ".gt-content > .gt-empty"):
            self.assertEqual(_decl(self.rule(sel), "max-width"), "72ch", sel)
        self.assertEqual(_decl(self.rule(".gt-groups-part"), "max-width"), "46rem")
        self.assertEqual(_decl(self.rule(".gt-groups-part > .segmented"), "justify-self"), "start")

    def test_the_play_box_is_capped_in_one_column_and_fills_its_side_column_beside_the_results(self):
        self.assertRegex(self.css, r"\.gt-play\s*\{[^}]*max-width:\s*40rem;")
        wide = re.search(r"@media \(min-width: 1600px\)\s*\{(.*?)\n\}", self.css, flags=re.S)
        self.assertIsNotNone(wide)
        self.assertRegex(wide.group(1), r"\.gt-layout\s*\{[^}]*grid-template-columns:\s*minmax\(300px, 380px\) minmax\(0, 1fr\)")
        self.assertRegex(wide.group(1), r"\.gt-play\s*\{\s*max-width:\s*none;\s*\}")

    def test_no_fixed_widths_or_nowrap(self):
        """Nothing in the part has a fixed width or refuses to wrap, which would outgrow a phone's column."""
        plain = re.sub(r"/\*.*?\*/", "", self.css, flags=re.S)
        self.assertNotRegex(plain, r"(?<![-\w])width:\s*\d")
        self.assertNotIn("nowrap", plain)


if __name__ == "__main__":
    unittest.main()
