"""The Stats tab's Minimum bracket part shows the tutor count (E9-S29) over the real
page scripts and DOM double.

No network, server, database or simulation is needed.
"""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


FIXTURE = """
  const panelWith = (tutors) => commanderPanel({sources: {}, commander: {ok: true,
    size: {ok: true, cards: 100, expected: 100}, commanders: ['Commander'],
    eligibility: {ok: true}, singleton: {ok: true, duplicates: [], allowed: []},
    identity: {ok: true, outside: []}, legality: {ok: true, banned: [], banned_as_companion: [], not_legal: []},
    bracket: {label: 'Bracket 1 or 2 (theme and intent decide)',
      reasons: ['No Game Changers, mass land denial or extra turns.'], tutors}}}, {});
  const minimum = (panel) => panel.querySelector('.formula');
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class StatsTutorUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_count_list_date_and_land_searches(self):
        self.run_js("""
          const part = minimum(panelWith({checked: true, count: 2, tags_date: '2026-10-30',
            cards: [{name: 'Demonic Tutor', qty: 1}, {name: 'The Seriema', qty: 1}],
            land_searches: [{name: 'Rampant Growth', qty: 1}]}));
          const text = part.textContent;
          assert(text.includes('Tutors found: 2'), text);
          assert(text.includes('Demonic Tutor') && text.includes('The Seriema'), text);
          assert(text.includes("Scryfall's oracle tags of 2026-10-30"), text);
          assert(text.includes("Searches for lands only aren't counted (1: Rampant Growth)."), text);
          assert(text.includes("The count informs only: it doesn't change the minimum bracket."), text);
        """)

    def test_none_found_and_unknown_date(self):
        self.run_js("""
          const text = minimum(panelWith({checked: true, count: 0, tags_date: null, cards: [],
            land_searches: []})).textContent;
          assert(text.includes('Tutors found: 0'), text);
          assert(text.includes('(date unknown)'), text);
          assert(text.includes("Searches for lands only aren't counted."), text);
          assert(!text.includes('null') && !text.includes('undefined'), text);
        """)

    def test_not_counted_and_older_answers_show_no_count(self):
        self.run_js("""
          for (const tutors of [undefined, null, {checked: false, reason: 'no file'}]) {
            const text = minimum(panelWith(tutors)).textContent;
            assert(!text.includes('Tutors found'), text);
          }
        """)
