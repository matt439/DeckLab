"""Checks of the page's tests of changes (decklab/web/variant.js and variant.css, simulation wave 3's
R15, forge-trial/sim-wave3-contract.md section 11.6), in test_web's way: they read the files, and run
a few of the page's functions under Node.js when it's installed.

- The editor's Test row: retained in its labelled Forge panel; shown while the deck or commander
  differs from the saved list, disabled with its visible reason for a size change or sideboard-only change.
- The test page while it plays: progress, the next check, the dashed live range and Stop, and no
  verdict words; it stops asking once its page is left.
- "Save this change" asks before replacing another unsaved draft of that list.
- Every class variant.js and variant.css make starts with "vt-".

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_web_variant
"""
import json
import re
import unittest

from decklab.tests.test_web import NODE, _function, _run_page, _styles, _text

SCRIPT = _text("variant.js")
CSS = _text("variant.css")
# Classes of the page's own that variant.css styles only in context (it makes none of them).
SHARED = {"edit-bar", "sheet-inner", "progress", "btn", "sub", "actions", "crumbs", "run-blocked",
          "fresh",      # sim-ui.js's freshness badge, beside a test in the deck page's list
          "spinner", "sr-only"}   # core's waiting spinner, and a status line only a screen reader hears


class VariantPageTests(unittest.TestCase):

    def test_every_class_starts_with_vt(self):
        for name in re.findall(r"\.([a-zA-Z][\w-]*)", re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)):
            with self.subTest(name=name):
                self.assertTrue(name.startswith("vt-") or name in SHARED, name)
        names = []
        for plain, template in re.findall(r'class: (?:"([^"]*)"|`((?:[^`$]|\$\{[^}]*\})*)`)', SCRIPT):
            names += plain.split()
            names += re.sub(r"\$\{[^}]*\}", " ", template).split()
            for inner in re.findall(r"\$\{([^}]*)\}", template):
                names += [x for q in re.findall(r'"([^"]*)"', inner) for x in q.split()
                          if re.fullmatch(r"[a-z][\w-]*", x)]
        self.assertIn("vt-chip-add", names)
        for name in names:
            with self.subTest(name=name):
                self.assertTrue(name.startswith(("vt-", "btn")) or name in SHARED, name)

    def test_the_test_row_lives_in_the_retained_forge_panel(self):
        self.assertRegex(CSS, r"\.vt-test-btn \{[^}]*min-height: 44px")
        self.assertIn(".vt-test-row[hidden], .vt-test-why[hidden] { display: none; }", CSS)
        self.assertNotIn(".edit-bar:has(> .vt-test-row", CSS)
        side = _function(_text("editor-screen.js"), "sidePanel")
        self.assertIn('ed.dom.forgeTest = typeof vtTestRow === "function" ? vtTestRow() : null;', side)
        self.assertIn('"aria-labelledby": "h-editor-forge"', side)
        self.assertIn('ed.dom.stats, ed.dom.forge', side)
        # drawStats replaces the numbers only; the original action and its reason stay attached.
        stats = _function(_text("editor-screen.js"), "drawStats")
        self.assertNotIn("ed.dom.forge", stats)
        bar = _function(_text("editor-screen.js"), "drawBar")
        self.assertIn("p.test = ed.dom.forgeTest || null;", bar)
        self.assertIn("vtSyncTestRow(p.test)", bar)
        self.assertIn("ed.dom.forge.hidden = p.test.hidden", bar)
        self.assertNotIn("add(bar, [p.test", bar)
        self.assertNotIn(".edit-bar .vt-test-why", _styles())

    def test_the_live_state_has_no_verdict(self):
        live = _function(SCRIPT, "vtLivePanel")
        self.assertNotIn("data.words", live)
        self.assertIn("Live range:", live)
        self.assertIn("dashed: true", live)
        self.assertIn("Next check at", live)
        self.assertIn('text: "Stop"', live)
        draw = _function(SCRIPT, "vtDraw")
        self.assertIn("page.token !== routeToken || !page.host || !page.host.isConnected", draw)
        self.assertIn("vtLive(data) ? vtLivePanel(page, data) : vtVerdictPanel(page, data)", draw)
        stop = _function(SCRIPT, "vtStop")
        self.assertLess(stop.index("ask("), stop.index("apiWrite("))

    def test_save_this_change_asks_first(self):
        save = _function(SCRIPT, "vtSaveChange")
        self.assertIn("Replace your unsaved changes to ${base.title} with this tested change?", save)
        self.assertLess(save.index("if (local.get(key))"), save.index("ask("))
        self.assertLess(save.index("ask("), save.index("local.set(key"))
        # The key is the editor's own draft key for that list (editor-drafts.js draftKey).
        self.assertIn("`draft.${state.profile.id}.${base.id}.${version}`", save)
        self.assertIn("draft.${ed.profile}.${ed.id}.${ed.version}", _text("editor-drafts.js"))


@unittest.skipUnless(NODE, "needs Node.js")
class VariantScriptTests(unittest.TestCase):

    NAMES = ("core.js", "deck.js", "editor.js", "editor-drafts.js", "variant.js")

    def state(self, base, now, kind="casual"):
        return (f"(editor = {{mode: 'edit', hasFileList: true, kind: {json.dumps(kind)}, "
                f"base: {{lists: {json.dumps(base)}}}, lists: {json.dumps(now)}}}, "
                f"JSON.stringify(vtTestState(editor)))")

    def test_when_test_applies(self):
        deck = [{"qty": 4, "name": "Grizzly Bears"}, {"qty": 56, "name": "Forest"}]
        side = [{"qty": 2, "name": "Lightning Bolt"}]
        swapped = [{"qty": 3, "name": "Grizzly Bears"}, {"qty": 57, "name": "Forest"}]
        calls = [self.state({"Deck": deck, "Sideboard": side}, {"Deck": deck, "Sideboard": side}),
                 self.state({"Deck": deck, "Sideboard": side}, {"Deck": swapped, "Sideboard": side}),
                 self.state({"Deck": deck, "Sideboard": side}, {"Deck": deck, "Sideboard": [{"qty": 1, "name": "Lightning Bolt"}]}),
                 self.state({"Deck": deck}, {"Deck": swapped[:1]}),
                 # A printing change alone is no change to test.
                 self.state({"Deck": deck}, {"Deck": [{"qty": 4, "name": "Grizzly Bears", "set": "fdn"}, deck[1]]})]
        found = [json.loads(x) for x in _run_page(calls, self.NAMES)]
        self.assertEqual(found[0], {"show": False})
        self.assertEqual(found[1], {"show": True, "ok": True, "why": None})
        self.assertEqual(found[2], {"show": True, "ok": False, "why": "Sideboard changes aren't tested (games are best of one)"})
        self.assertEqual(found[3], {"show": True, "ok": False, "why": "Keep the same number of cards to test a change"})
        self.assertEqual(found[4], {"show": False})

    def test_words_and_the_change(self):
        calls = ["vtChangeWords({remove: [[1, 'Fiery Annihilation']], add: [[1, 'Rabid Gnaw']]}).join(', ')",
                 "vtPoints(0.024) + ' ' + vtPoints(-0.006) + ' ' + vtPoints(0)",
                 "vtMinutes([25, 40], false) + ' / ' + vtMinutes([25, 110], true)",
                 "JSON.stringify(vtApplyChange({Deck: [{qty: 2, name: 'Fire // Ice', set: 'apc'}, {qty: 3, name: 'Shock'}]},"
                 " {remove: [[1, 'Fire']], add: [[1, 'Shock'], [2, 'Opt']]}))"]
        words, points, minutes, applied = _run_page(calls, self.NAMES)
        self.assertEqual(words, "−1 Fiery Annihilation, +1 Rabid Gnaw")
        self.assertEqual(points, "+2.4 −0.6 0.0")
        self.assertEqual(minutes, "about 25-40 minutes / up to about 1 h 50 min")
        self.assertEqual(json.loads(applied), {"Deck": [{"qty": 1, "name": "Fire // Ice", "set": "apc"},
                                                        {"qty": 4, "name": "Shock"}, {"qty": 2, "name": "Opt"}]})

    def test_the_panels_draw(self):
        done = {"status": "done", "verdict": "better", "words": "Better against the field: +2.4 points of win rate (+0.6 to +4.2)",
                "margin": 0.02, "field": {"delta": 0.024, "low": 0.006, "high": 0.042}, "error": None,
                "test": {"test": "a" * 64, "base": {"id": "casual/gruul-ramp", "version": "target", "title": "Gruul Ramp"},
                         "against": "field:Constructed", "outcome": "better", "starter_mismatch": {"games": 30, "of": 1800},
                         "looks": [{"games_per_opponent": 400, "decision": "better", "stopped": False}],
                         "variant": {"changes": {"remove": [[1, "Fiery Annihilation"]], "add": [[1, "Rabid Gnaw"]]}}},
                "opponents": [{"id": "casual/izzet", "title": "Izzet", "base_key": "b" * 64,
                               "paired": {"delta": 0.03, "low": 0.0, "high": 0.06, "n": 400, "same": 0.64,
                                          "saved_share": 0.5}, "games": 400},
                              {"id": "casual/red", "title": "Red", "dropped": "couldn't be played: no."}]}
        live = dict(done, status="running", words=None, verdict=None,
                    job={"done": 1800, "total": 14400, "next_look": 400, "seconds": 600, "ahead": 0,
                         "pairs": {"k": {"opponent": {"title": "Izzet"}, "done": 200, "total": 400}},
                         "range": {"delta": 0.02, "low": -0.03, "high": 0.07}})
        verdict, playing, rows = _run_page([f"vtVerdictPanel({{}}, {json.dumps(done)})",
                                            # (the stand-in document has no style: progress bars set it)
                                            "(Object.defineProperty(Node.prototype, 'style', {get() { return this._s "
                                            "|| (this._s = {}); }, configurable: true}), "
                                            f"vtLivePanel({{}}, {json.dumps(live)}))", f"vtRows({json.dumps(done)})"],
                                           self.NAMES)
        self.assertIn("Better against the field", verdict)
        self.assertIn("Pairing the games saved about 50%", verdict)
        self.assertIn("didn't get the same games (30 of 1,800", verdict)
        self.assertIn("Play more", verdict)
        self.assertIn("Save this change", verdict)
        self.assertIn("1,800 of up to 14,400 games", playing)
        self.assertIn("Next check at 400 games a deck", playing)
        self.assertIn("Live range: −3.0 to +7.0 points", playing)
        self.assertNotIn("Better", playing)
        self.assertIn("played out the same in 64% of games", rows)
        self.assertIn("couldn't be played: no.", rows)
        self.assertIn("−10 · worse0better · +10", rows)          # one shared scale with its axis (MU-10)

    def test_one_scale_coloured_by_verdict(self):
        # Every difference bar on the page shares one span (the widest end, rounded up to 5 points) and its axis;
        # a bar's colour is its verdict: its whole range above 0 helps, below 0 hurts, across 0 is even.
        data = {"field": {"delta": 0.024, "low": 0.006, "high": 0.042},
                "opponents": [{"paired": {"delta": -0.06, "low": -0.11, "high": -0.02}}, {"dropped": "no"}]}
        span, kinds = _run_page([f"String(vtSpan({json.dumps(data)}))",
                                 "[vtDiffKind(0.01, 0.05), vtDiffKind(-0.05, -0.01), vtDiffKind(-0.01, 0.02)].join(',')"],
                                self.NAMES)
        self.assertEqual(span, "0.15")
        self.assertEqual(kinds, "good,crit,even")


if __name__ == "__main__":
    unittest.main()
