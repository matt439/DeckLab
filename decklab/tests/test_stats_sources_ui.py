"""Stats citations display recorded dates over the real page scripts and DOM double.

No network, server, database or simulation is needed.
"""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


FIXTURE = """
  const sources = Object.fromEntries(['formula', 'thumb', 'thumb2', 'colour', 'bracket', 'unused'].map((id) =>
    [id, {title: id + ' study', date: '2022-07-29; updated 2025-02-13; checked 2026-09-29',
      url: 'https://example.test/' + id}]));
  const requirement = (colour, needed, have) => ({cost_in_colours: colour, turn: 1, needed, have,
    have_lands: have, margin: have - needed, ok: have >= needed, cards: [], notes: []});
  const white = requirement('W', 14, 13), green = requirement('GG', 21, 8);
  const st = {
    sources,
    lands: {lands: 24, effective: 24, formula: {source: 'formula', text: 'recorded formula'},
      rule_of_thumb: {text: 'recorded advice', sources: ['thumb', 'thumb2']}},
    colours: {source: 'colour', table: 60, colours: [
      {colours: 'W', name: 'white', ok: false, hardest: white, checks: [white], short: [white]},
      {colours: 'G', name: 'green', ok: false, hardest: green, checks: [green], short: [green]}]},
    commander: {ok: true, size: {ok: true, cards: 100, expected: 100}, commanders: ['Commander'],
      eligibility: {ok: true}, singleton: {ok: true, duplicates: [], allowed: []},
      identity: {ok: true, outside: []}, legality: {ok: true, banned: [], banned_as_companion: [], not_legal: []},
      bracket: {sources: ['bracket'], brackets: [{number: 2, name: 'Core', game_changers: 0}]}}
  };
  const disclosure = (panel, name) => panel.querySelectorAll('details').find((d) =>
    d.querySelector('summary').textContent === name);
  const panels = () => [disclosure(landPanel(st), 'How is this worked out?'),
    disclosure(colourPanel(st), 'How is this worked out?'), disclosure(commanderPanel(st, {}), 'The five brackets')];
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class StatsSourceUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), FIXTURE + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_each_disclosure_keeps_titles_links_and_the_recorded_date(self):
        self.run_js("""
          const expected = [['thumb', 'thumb2', 'formula'], ['colour'], ['bracket']];
          panels().forEach((panel, i) => {
            const links = panel.querySelectorAll('a');
            same(links.map((a) => a.textContent), expected[i].map((id) => sources[id].title));
            links.forEach((link, j) => {
              const source = sources[expected[i][j]];
              assert.equal(link.getAttribute('href'), source.url);
              assert.equal(link.getAttribute('target'), '_blank');
              assert.equal(link.getAttribute('rel'), 'noopener noreferrer');
              assert.equal(link.parentNode.textContent, source.title + ' (' + source.date + ')');
            });
          });
          // A larger green shortfall does not move it above white: each colour keeps its own hardest requirement.
          const rows = colourPanel(st).querySelector('.colour-list').children;
          assert(rows[0].textContent.includes('White'));
          assert(rows[1].textContent.includes('Green'));
          assert(rows[0].textContent.includes('13 of 14 needed'));
          assert(rows[1].textContent.includes('8 of 21 needed'));
        """)

    def test_unknown_dates_are_explicit_in_every_disclosure_and_the_source_list(self):
        self.run_js("""
          for (const value of [undefined, null, '', '   ', 2026]) {
            for (const source of Object.values(sources)) source.date = value;
            for (const panel of [...panels(), sourcesPanel(st)]) {
              const links = panel.querySelectorAll('a');
              assert(links.length > 0);
              links.forEach((link) => assert.equal(link.parentNode.textContent, link.textContent + ' (date unknown)'));
              assert(!panel.textContent.includes('undefined') && !panel.textContent.includes('(null)'));
            }
          }
          assert.equal(statsSourceCitation(sources, 'absent'), null);
          assert.equal(statsSourceCitation(null, 'absent'), null);
        """)

    def test_bottom_list_still_contains_only_cited_sources_and_shared_links_stay_title_only(self):
        self.run_js("""
          const list = sourcesPanel(st);
          same(list.querySelectorAll('a').map((a) => a.textContent),
            ['formula study', 'thumb study', 'thumb2 study', 'colour study', 'bracket study']);
          list.querySelectorAll('li').forEach((li) => assert(li.textContent.endsWith('(' + sources.formula.date + ')')));
          assert.equal(sourceLink(sources, 'formula').textContent, 'formula study');
          assert.equal(accLink({link: 'https://example.test/shop'}).textContent, 'Shop page');
          assert.equal(accLink({link: 'https://example.test/picture.png'}).textContent, 'Picture');
          assert.equal(sourcesPanel({sources}), null);
        """)
