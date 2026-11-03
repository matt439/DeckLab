"""Tests for popular-decks results kept through a change (E3-S34): the previous list's figure,
the same-opponent comparison, "moved" opponents and older results (another Forge, other settings,
another pilot, a rebuilt catalogue), in forge.gauntlet (compare, notes_keys, older) and
api/gauntlet_before.py with GET /api/gauntlet and /api/gauntlet/summary.

The engine tests run on test_gauntlet_run's GauntletCase (its FakeField results, a hand-written
catalogue, a temporary gauntlet results folder) with results written in the runner's own side
shape (runner._side and runner._seen). The API tests run in test_gauntlet_api's sandbox with a
stand-in gauntlet whose view gives games by list (card_sha), and deck revisions from
test_deck_history's WithHistory. No Forge game, network, database or real catalogue is used.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_gauntlet_before
"""
import json
from unittest import mock

from decklab.lib import inventory
from decklab.lib.api import gauntlet_before, gauntlet_page
from decklab.lib.forge import engine, field, gauntlet, lists, runner
from decklab.tests.test_api import GRUUL as GRUUL_TEXT
from decklab.tests.test_deck_history import WithHistory, revision
from decklab.tests.test_gauntlet_api import ELVES, GRUUL, POPULAR, R_ELVES, FakeGauntlet, GauntletApiTestCase
from decklab.tests.test_gauntlet_run import CATALOGUE, IDS, GauntletCase

TODAY = {"id_version": 3, "run_version": 2, "kind": "decklab", "forge": "2.0.16+res.new", "clock_s": 120,
         "seeds": "splitmix64", "performance_mode": True, "game_patches": [], "overrides": "none",
         "complete": True, "ai_sha": {}}
OLD = dict(TODAY, forge="2.0.15+res.old")


def _fields(eng):
    return {k: eng[k] for k in engine.ENGINE_FIELDS}


# ============================================================ forge.gauntlet

class EngineCase(GauntletCase):

    def setUp(self):
        super().setUp()
        self.beta = lists.entry_from_cards("casual/alpha", "Alpha", "constructed",
                                           {"Commander": [], "Main": [[4, "Savannah Lions"], [19, "Plains"],
                                                                      [1, "Opt"]]})
        self.assertNotEqual(self.beta["card_sha"], self.alpha["card_sha"])

    def keep(self, entry):
        return gauntlet_page._keep(entry)

    def games(self, entry, deck_id, n, rate, key=None, eng=None, updated="2026-11-02T10:00:00"):
        stored = self.gfake.add_games(entry, self.opponent(deck_id), n, rate=rate, key=key)
        stored["updated"] = updated
        if eng is not None:
            stored["engine"] = _fields(eng)
        return stored

    def note(self, entry, keys, space="home"):
        field._append_note(entry, self.gauntlet_dir, {"per_opponent": {k: 100 for k in keys}}, space=space)


class KeepTests(EngineCase):

    def test_the_runners_own_side_shape_is_kept(self):
        # E3-S34 section 0: real sides keep their ids under seen_as only (runner._side, runner._seen).
        mine, theirs = runner._side(self.alpha), runner._side(self.opponent(IDS[0]))
        runner._seen(mine, self.alpha, "2026-11-02T10:00:00")
        runner._seen(theirs, self.opponent(IDS[0]), "2026-11-02T10:00:00")
        self.assertNotIn("id", theirs)
        keep = self.keep(self.alpha)
        self.assertTrue(keep({"sides": [mine, theirs]}))
        self.assertTrue(keep({"sides": [theirs, mine]}))
        house = runner._side(self.entry("casual/gamma"))
        runner._seen(house, self.entry("casual/gamma"), "2026-11-02T10:00:00")
        self.assertFalse(keep({"sides": [mine, house]}))                  # another house deck
        self.assertFalse(self.keep(self.beta)({"sides": [mine, theirs]}))  # another list
        nameless = dict(theirs, seen_as=[])
        self.assertFalse(keep({"sides": [mine, nameless]}))               # no id at all: not a gauntlet deck
        mixed = dict(theirs, seen_as=theirs["seen_as"] + [{"id": "casual/gamma"}])
        self.assertFalse(keep({"sides": [mine, mixed]}))                  # every id must be a gauntlet one


class CompareTests(EngineCase):

    def test_only_the_common_opponents_count(self):
        for deck_id, rate in zip(IDS[:3], (0.3, 0.5, 0.7)):
            self.games(self.beta, deck_id, 200, rate)
        for deck_id, rate in zip(IDS[1:], (0.55, 0.75, 0.4)):
            self.games(self.alpha, deck_id, 200, rate)
        found = gauntlet.compare(self.alpha, self.beta, self.sample, self.keep(self.alpha), self.keep(self.beta))
        self.assertEqual((found["same"], found["ids"]), (2, IDS[1:3]))
        self.assertEqual(set(found["before"]), {"rate", "low", "high"})
        # Each figure is the equal-weight average over those two opponents only.
        common_now = gauntlet._group("all", "", [m for m in gauntlet._members(self.alpha, self.sample,
                                                                               self.keep(self.alpha), CATALOGUE)[1]
                                                 if m[0]["id"] in IDS[1:3]])
        self.assertEqual(found["now"]["rate"], common_now["rate"])
        self.assertNotEqual(found["now"]["rate"], gauntlet.view(self.alpha, self.sample)["overall"]["rate"])

    def test_no_common_opponent_is_none(self):
        self.games(self.beta, IDS[0], 200, 0.4)
        self.games(self.alpha, IDS[1], 200, 0.4)
        self.assertIsNone(gauntlet.compare(self.alpha, self.beta, self.sample))

    def test_moved_only_when_the_ranges_dont_overlap(self):
        moved = gauntlet_before._moved
        self.assertTrue(moved({"low": 0.3, "high": 0.4}, {"low": 0.45, "high": 0.6}))
        self.assertTrue(moved({"low": 0.5, "high": 0.6}, {"low": 0.3, "high": 0.45}))
        self.assertFalse(moved({"low": 0.3, "high": 0.5}, {"low": 0.45, "high": 0.6}))
        self.assertFalse(moved({"low": 0.3, "high": 0.45}, {"low": 0.45, "high": 0.6}))   # touching overlaps
        self.assertFalse(moved(None, {"low": 0.45, "high": 0.6}))
        self.assertFalse(moved({"low": None, "high": 0.4}, {"low": 0.45, "high": 0.6}))


class NotesTests(EngineCase):

    def test_newest_runs_first_within_the_limit_and_this_space_only(self):
        self.note(self.alpha, ["k1", "k2"])
        self.note(self.alpha, ["k3", "k1"])
        self.note(self.alpha, ["other"], space="user2")
        self.assertEqual(gauntlet.notes_keys(self.alpha, "home"), ["k3", "k1", "k2"])
        self.assertEqual(gauntlet.notes_keys(self.alpha, "home", limit=2), ["k3", "k1"])
        self.assertEqual(gauntlet.notes_keys(self.alpha, "user2"), ["other"])
        self.assertEqual(gauntlet.notes_keys(self.beta, "home"), [])
        self.assertTrue(gauntlet.has_notes({"card_sha": self.alpha["card_sha"], "kind": "constructed"}, "home"))
        self.assertFalse(gauntlet.has_notes(self.beta, "home"))

    def test_a_run_notes_its_sample(self):
        note = gauntlet.run(self.alpha, self.sample, "fixed:50", inflight=2, pool=object())
        self.assertEqual((note["sample"], note["catalogue_sha"], note["standard"]),
                         (self.sample["id"], "a" * 64, False))


class OlderTests(EngineCase):

    def setUp(self):
        super().setUp()
        self.today = dict(TODAY)
        patcher = mock.patch.object(engine, "today", lambda *a, **k: self.today)
        patcher.start()
        self.addCleanup(patcher.stop)

    def old_key(self, deck_id, salt="old"):
        return salt + lists.matchup_key(self.alpha, self.opponent(deck_id))

    def older(self, today_keys=()):
        return gauntlet.older(self.alpha, self.sample, keep=self.keep(self.alpha), today_keys=today_keys)

    def test_nothing_older(self):
        self.assertIsNone(self.older())
        key = lists.matchup_key(self.alpha, self.opponent(IDS[0]))
        self.games(self.alpha, IDS[0], 100, 0.5, eng=TODAY)
        self.note(self.alpha, [key])
        self.assertIsNone(self.older(today_keys=[key]))         # today's keys are the view's, not older

    def test_an_older_forge(self):
        keys = []
        for deck_id, rate in zip(IDS[:3], (0.3, 0.5, 0.7)):
            keys.append(self.old_key(deck_id))
            self.games(self.alpha, deck_id, 200, rate, key=keys[-1], eng=OLD)
        self.note(self.alpha, keys)
        found = self.older()
        self.assertEqual((found["reason"], found["opponents"], found["of"], found["updated"]),
                         ("forge", 3, 4, "2026-11-02T10:00:00"))
        self.assertEqual(set(found["overall"]), {"rate", "low", "high"})
        self.assertLess(found["overall"]["low"], found["overall"]["rate"])
        # Unread by the view: today's key finds nothing.
        self.assertEqual(gauntlet.view(self.alpha, self.sample, keep=self.keep(self.alpha))["played"], 0)

    def test_opponents_played_today_replace_their_older_results(self):
        keys = []
        for deck_id in IDS[:3]:
            keys.append(self.old_key(deck_id))
            self.games(self.alpha, deck_id, 200, 0.5, key=keys[-1], eng=OLD)
        self.note(self.alpha, keys)
        found = gauntlet.older(self.alpha, self.sample, keep=self.keep(self.alpha), played=IDS[:1])
        self.assertEqual(found["opponents"], 2)
        self.assertIsNone(gauntlet.older(self.alpha, self.sample, keep=self.keep(self.alpha), played=IDS))

    def test_settings_pilot_and_the_order_of_reasons(self):
        self.games(self.alpha, IDS[0], 100, 0.5, key=self.old_key(IDS[0]), eng=dict(TODAY, clock_s=60))
        self.note(self.alpha, [self.old_key(IDS[0])])
        self.assertEqual(self.older()["reason"], "settings")
        self.gfake.store[self.old_key(IDS[0])]["engine"] = _fields(TODAY)
        self.assertEqual(self.older()["reason"], "pilot")
        # An opponent whose list changed in a rebuild is "catalogue" whatever its engine.
        stored = self.gfake.store[self.old_key(IDS[0])]
        side = next(s for s in stored["sides"] if s["card_sha"] != self.alpha["card_sha"])
        side["card_sha"] = "9" * 64
        self.assertEqual(self.older()["reason"], "catalogue")
        stored["engine"] = _fields(OLD)
        self.assertEqual(self.older()["reason"], "catalogue")

    def test_one_engine_only_the_newest_group(self):
        self.games(self.alpha, IDS[0], 100, 0.5, key=self.old_key(IDS[0], "a"), eng=OLD, updated="2026-10-01T00:00")
        self.games(self.alpha, IDS[1], 100, 0.5, key=self.old_key(IDS[1], "a"), eng=OLD, updated="2026-10-02T00:00")
        newer = dict(OLD, forge="2.0.15+res.mid")
        self.games(self.alpha, IDS[2], 100, 0.6, key=self.old_key(IDS[2], "b"), eng=newer,
                   updated="2026-10-20T00:00")
        self.note(self.alpha, [self.old_key(IDS[0], "a"), self.old_key(IDS[1], "a"), self.old_key(IDS[2], "b")])
        found = self.older()
        self.assertEqual((found["reason"], found["opponents"], found["updated"]), ("forge", 1, "2026-10-20T00:00"))

    def test_an_unconfirmed_forge_makes_no_claim(self):
        self.games(self.alpha, IDS[0], 100, 0.5, key=self.old_key(IDS[0]), eng=OLD)
        self.note(self.alpha, [self.old_key(IDS[0])])
        self.today = dict(TODAY, complete=False)
        found = self.older()
        self.assertEqual((found["reason"], found["opponents"], found["overall"]), ("unknown", None, None))

    def test_another_house_decks_results_never_count(self):
        gamma = self.entry("casual/gamma")
        key = "old" + lists.matchup_key(self.alpha, gamma)
        self.gfake.add_games(self.alpha, gamma, 100, rate=0.5, key=key)
        self.note(self.alpha, [key])
        self.assertIsNone(self.older())


# ============================================================ the API

def _text(forests):
    return GRUUL_TEXT.replace("9 Forest", f"{forests} Forest")


class ByListGauntlet(FakeGauntlet):
    """FakeGauntlet whose view gives each list (card_sha) the games in self.per {card_sha: {opponent
    id: rate}} (100 games each, range rate +/- 0.05), with compare, has_notes and older."""

    def __init__(self, forge, results):
        super().__init__(forge, results)
        self.per, self.views, self.noted, self.older_answer, self.olders = {}, [], [], None, []
        self.not_meaningful, self.older_by, self.compared = set(), {}, 0

    def plan(self, entry, chosen, budget):
        return {"pairs": []}

    def _rate(self, sha, deck_id):
        rate = self.per.get(sha, {}).get(deck_id)
        return None if rate is None else {"value": rate, "low": round(rate - 0.05, 4), "high": round(rate + 0.05, 4)}

    def view(self, entry, chosen, keep=None, cat=None):
        self.views.append(entry["card_sha"])
        opponents = [{"id": d, "title": d.rsplit("/", 1)[1], "key": f"{entry['card_sha'][:8]}-{d}",
                      "games": 100 if self._rate(entry["card_sha"], d) else 0, "rate": self._rate(entry["card_sha"], d),
                      "updated": "2026-11-02T10:00:00" if self._rate(entry["card_sha"], d) else None,
                      "not_meaningful": (entry["card_sha"], d) in self.not_meaningful,
                      "source": {"kind": "forge"}} for d in chosen["decks"]]
        played = [o for o in opponents if o["rate"]]
        overall = None
        if played:
            mean = round(sum(o["rate"]["value"] for o in played) / len(played), 4)
            overall = {"key": "all", "rate": mean, "low": round(mean - 0.08, 4), "high": round(mean + 0.08, 4)}
        return {"opponents": opponents, "groups": {}, "overall": overall, "played": len(played),
                "of": len(opponents), "games": 100 * len(played), "tally": None,
                "updated": "2026-11-02T10:00:00" if played else None, "note": None, "notes": []}

    def compare(self, entry, before, chosen, keep_now=None, keep_before=None, cat=None):
        self.compared += 1
        ids = [d for d in chosen["decks"] if self._rate(entry["card_sha"], d) and self._rate(before["card_sha"], d)]
        if not ids:
            return None

        def mean(sha):
            value = round(sum(self.per[sha][d] for d in ids) / len(ids), 4)
            return {"rate": value, "low": round(value - 0.08, 4), "high": round(value + 0.08, 4)}
        return {"same": len(ids), "ids": ids, "before": mean(before["card_sha"]), "now": mean(entry["card_sha"])}

    def has_notes(self, entry, space):
        self.noted.append((entry["card_sha"], space))
        return entry["card_sha"] in self.per

    def older(self, entry, chosen, keep=None, cat=None, today_keys=(), space="home", limit=300, played=()):
        self.olders.append((list(today_keys), space, limit))
        return self.older_by.get(entry["card_sha"], self.older_answer)


class ApiCase(GauntletApiTestCase):

    def setUp(self):
        super().setUp()
        self.g = ByListGauntlet(self.forge, self.g.results)
        self.forge.gauntlet = self.g
        self.ids = [p[0] for p in POPULAR]
        self.history({GRUUL: [revision(GRUUL, 1, _text(10), op="A", actor="user1", message="Secret words"),
                              revision(GRUUL, 2, _text(8), actor="user1", message="Secret words"),
                              revision(GRUUL, 3, _text(9), actor="matt", message="Secret words")]})

    def history(self, revisions):
        self.backend = WithHistory(inventory.backend(), revisions)
        self.addCleanup(inventory.use(self.backend))

    def sha(self, forests):
        from decklab.lib import decks
        parsed = decks.parse_deck(_text(forests).encode("utf-8"), "gruul-test", "casual", None, "home")
        return self.forge.card_sha(parsed.target, "constructed")

    def summary(self, who="matt", deck_id=GRUUL):
        return self.call(who, gauntlet_page.gauntlet_summary, deck_id, "target")

    def view(self, who="matt", deck_id=GRUUL, **choices):
        return self.call(who, gauntlet_page.gauntlet_view, deck_id, "target", **choices)


class PreviousListTests(ApiCase):

    def test_the_list_changed_since_its_last_test(self):
        self.assertEqual(self.sha(9), gauntlet_page.field_page._field_entry(self.forge, GRUUL, "target")[1]["card_sha"])
        self.g.per = {self.sha(8): {i: 0.41 for i in self.ids}}
        found = self.summary()
        self.assertEqual(found["state"], "stale_list")
        self.assertEqual(found["before"], {"rate": 0.41, "low": 0.33, "high": 0.49, "played": 3, "of": 3,
                                           "games": 300, "updated": "2026-11-02T10:00:00"})
        self.assertIsNone(found["compare"])
        self.assertEqual(found["overall"], None)

    def test_after_a_retest_the_same_opponents_compare(self):
        self.g.per = {self.sha(8): {i: 0.41 for i in self.ids}, self.sha(9): {self.ids[0]: 0.6, self.ids[1]: 0.47}}
        found = self.summary()
        self.assertEqual(found["state"], "partial")
        self.assertEqual(found["compare"], {"same": 2, "before": {"rate": 0.41, "low": 0.33, "high": 0.49},
                                            "now": {"rate": 0.535, "low": 0.455, "high": 0.615}, "moved": 1})
        view = self.view()
        rows = {o["id"]: o for o in view["opponents"]}
        self.assertEqual(rows[self.ids[0]]["before"], {"rate": 0.41, "low": 0.36, "high": 0.46})
        self.assertTrue(rows[self.ids[0]]["moved"])             # 0.36-0.46 against 0.55-0.65
        self.assertFalse(rows[self.ids[1]]["moved"])            # 0.36-0.46 against 0.42-0.52 overlap
        self.assertFalse(rows[self.ids[2]]["moved"])            # no games for today's list
        self.assertEqual(view["compare"], found["compare"])
        self.assertEqual(view["before"], found["before"])

    def test_not_meaningful_rows_are_never_moved(self):
        self.g.per = {self.sha(8): {i: 0.41 for i in self.ids}, self.sha(9): {self.ids[0]: 0.8, self.ids[1]: 0.8}}
        self.g.not_meaningful = {(self.sha(9), self.ids[0]), (self.sha(8), self.ids[1])}
        rows = {o["id"]: o for o in self.view()["opponents"]}
        self.assertFalse(rows[self.ids[0]]["moved"])            # today's isn't meaningful
        self.assertFalse(rows[self.ids[1]]["moved"])            # nor the earlier one's
        self.assertIsNone(rows[self.ids[1]]["before"])
        self.assertEqual(rows[self.ids[0]]["before"]["rate"], 0.41)

    def test_a_reverted_list_is_skipped(self):
        # Revisions A, B, A: today's list is A again, so the previous one is B.
        self.history({GRUUL: [revision(GRUUL, 1, _text(9), op="A"), revision(GRUUL, 2, _text(8)),
                              revision(GRUUL, 3, _text(9))]})
        self.g.per = {self.sha(8): {self.ids[0]: 0.5}, self.sha(9): {self.ids[0]: 0.5}}
        found = self.summary()
        self.assertEqual(found["compare"]["same"], 1)
        self.assertEqual(self.g.views, [self.sha(9), self.sha(8)])

    def test_the_work_is_bounded(self):
        revisions = [revision(GRUUL, n, _text(10 + n), op="A" if n == 1 else "M") for n in range(1, 25)]
        revisions.append(revision(GRUUL, 25, _text(9)))
        self.history({GRUUL: revisions})
        asked = []
        real = inventory.deck_revisions_with_text

        def counted(deck_id, limit, before=None):
            asked.append((limit, before))
            return real(deck_id, limit, before)
        self.g.has_notes = lambda entry, space: True        # every list has notes, but none has games
        with mock.patch.object(inventory, "deck_revisions_with_text", counted):
            found = self.summary()
        self.assertEqual(asked, [(gauntlet_before.PAGE, None)])
        self.assertEqual(len(self.g.views), 1 + gauntlet_before.MAX_VIEWS)
        self.assertEqual(found["state"], "untested")
        self.assertIn(gauntlet_before.NOT_ALL, found["notes"])      # never silent about the lists left

    def test_table_only_revisions_dont_use_up_the_bound(self):
        # 60 table refreshes and reprices of today's list after the change: the earlier list is still found.
        today = [revision(GRUUL, n, _text(9) + f"\n| Table row {n} |\n") for n in range(3, 63)]
        self.history({GRUUL: [revision(GRUUL, 1, _text(8), op="A"), revision(GRUUL, 2, _text(9))] + today})
        self.g.per = {self.sha(8): {self.ids[0]: 0.5}}
        parsed = []
        real = gauntlet_before._sections
        with mock.patch.object(gauntlet_before, "_sections", lambda *a: parsed.append(1) or real(*a)):
            found = self.summary()
        self.assertEqual((found["state"], found["before"]["rate"]), ("stale_list", 0.5))
        self.assertLessEqual(len(parsed), 3)                # the same lists aren't parsed again

    def test_the_revisions_read_are_bounded_and_said(self):
        same = [revision(GRUUL, n, _text(9) + f"\n| Table row {n} |\n") for n in range(2, 260)]
        self.history({GRUUL: [revision(GRUUL, 1, _text(8), op="A")] + same})
        self.g.per = {self.sha(8): {self.ids[0]: 0.5}}
        asked = []
        real = inventory.deck_revisions_with_text

        def counted(deck_id, limit, before=None):
            asked.append(limit)
            return real(deck_id, limit, before)
        with mock.patch.object(inventory, "deck_revisions_with_text", counted):
            found = self.summary()
        self.assertEqual(sum(asked[:-1]), gauntlet_before.MAX_REVISIONS)
        self.assertEqual(asked[-1], 1)                      # only whether more are left
        self.assertIsNone(found["before"])
        self.assertIn(gauntlet_before.NOT_ALL, found["notes"])

    def test_the_lists_looked_at_are_bounded_and_said(self):
        lists = [revision(GRUUL, n, _text(10 + n), op="A" if n == 1 else "M") for n in range(1, 30)]
        self.history({GRUUL: lists + [revision(GRUUL, 30, _text(9))]})
        self.g.per = {self.sha(11): {self.ids[0]: 0.5}}      # the oldest list, past MAX_LISTS
        found = self.summary()
        self.assertIsNone(found["before"])
        self.assertIn(gauntlet_before.NOT_ALL, found["notes"])

    def test_the_kept_parts_are_cached_while_a_run_plays(self):
        self.g.per = {self.sha(8): {i: 0.41 for i in self.ids}, self.sha(9): {self.ids[0]: 0.6}}
        reads = []
        real = inventory.deck_revisions_with_text
        with mock.patch.object(inventory, "deck_revisions_with_text",
                               lambda *a: reads.append(1) or real(*a)):
            self.summary()
            views, olders, compared = len(self.g.views), len(self.g.olders), self.g.compared
            again = self.summary()                         # a poll: nothing new played
            self.assertEqual((len(reads), len(self.g.views), len(self.g.olders), self.g.compared),
                             (1, views + 1, olders, compared))
            self.g.per[self.sha(9)][self.ids[1]] = 0.5     # a game lands: compare and older again
            after = self.summary()
        self.assertEqual(len(reads), 1)
        self.assertEqual((again["compare"]["same"], after["compare"]["same"]), (1, 2))
        self.assertEqual(len(self.g.olders), olders + 1)

    def test_lists_without_notes_are_never_viewed(self):
        self.history({GRUUL: [revision(GRUUL, n, _text(10 + n), op="A" if n == 1 else "M") for n in range(1, 8)]
                      + [revision(GRUUL, 8, _text(9))]})
        self.g.per = {self.sha(11): {self.ids[0]: 0.5}}      # the oldest list only
        found = self.summary()
        self.assertEqual(found["before"]["played"], 1)
        self.assertEqual(self.g.views, [self.sha(9), self.sha(11)])
        self.assertTrue(all(space == "home" for _, space in self.g.noted))

    def test_unreadable_text_and_no_decklist_are_skipped(self):
        self.history({GRUUL: [revision(GRUUL, 1, _text(8), op="A"), revision(GRUUL, 2, None),
                              revision(GRUUL, 3, "# Gruul Test\n\nNo list.\n"), revision(GRUUL, 4, _text(9))]})
        self.g.per = {self.sha(8): {self.ids[0]: 0.5}}
        self.assertEqual(self.summary()["before"]["rate"], 0.5)

    def test_a_restore_goes_on_past_its_retirement(self):
        self.history({GRUUL: [revision(GRUUL, 1, _text(8), op="A"), revision(GRUUL, 2, _text(7)),
                              revision(GRUUL, 3, _text(7), op="D"), revision(GRUUL, 4, _text(7), op="A"),
                              revision(GRUUL, 5, _text(9))]})
        self.g.per = {self.sha(8): {self.ids[0]: 0.5}}
        self.assertEqual(self.summary()["before"]["rate"], 0.5)

    def test_a_deck_made_again_under_the_id_is_another_deck(self):
        # The old deck was deleted and a new one made under its id: its results are never "before".
        self.history({GRUUL: [revision(GRUUL, 1, _text(8), op="A"), revision(GRUUL, 2, _text(8), op="D"),
                              revision(GRUUL, 3, _text(7), op="A"), revision(GRUUL, 4, _text(9))]})
        self.g.per = {self.sha(8): {self.ids[0]: 0.5}}
        found = self.summary()
        self.assertEqual((found["before"], found["state"], found["notes"]), (None, "untested", []))

    def test_unreadable_revisions_leave_a_note(self):
        self.g.per = {self.sha(8): {self.ids[0]: 0.5}}
        with mock.patch.object(inventory, "deck_revisions_with_text", side_effect=inventory.Unavailable("down")):
            found = self.summary()
        self.assertIsNone(found["before"])
        self.assertIn("The list's earlier versions can't be read now.", found["notes"])
        self.assertEqual(found["state"], "untested")

    def test_the_files_backend_has_no_before(self):
        self.history({})
        self.g.per = {self.sha(8): {self.ids[0]: 0.5}}
        found = self.summary()
        self.assertEqual((found["before"], found["compare"], found["state"]), (None, None, "untested"))

    def test_another_sample_has_none_of_it(self):
        self.g.per = {self.sha(8): {i: 0.41 for i in self.ids}, self.sha(9): {self.ids[0]: 0.6}}
        self.g.older_answer = {"reason": "forge", "opponents": 1, "of": 3, "updated": None, "overall": None}
        found = self.view(styles="aggro")
        self.assertFalse(found["is_standard"])
        self.assertEqual((found["before"], found["compare"], found["older"]), (None, None, None))
        self.assertTrue(all(o["before"] is None and o["moved"] is False for o in found["opponents"]))
        self.assertEqual(self.g.olders, [])


class OlderApiTests(ApiCase):

    def test_stale_older_and_its_fields(self):
        self.history({})
        self.g.older_answer = {"reason": "forge", "opponents": 2, "of": 3, "updated": "2026-11-02T10:00:00",
                               "overall": {"rate": 0.41, "low": 0.33, "high": 0.49}, "extra": "dropped"}
        found = self.summary()
        self.assertEqual(found["state"], "stale_older")
        self.assertEqual(found["older"], {"reason": "forge", "opponents": 2, "of": 3, "updated": "2026-11-02T10:00:00",
                                          "overall": {"rate": 0.41, "low": 0.33, "high": 0.49}})
        today_keys, space, limit = self.g.olders[-1]
        self.assertEqual((len(today_keys), space, limit), (3, "home", 300))
        # With games for today's list it's a note beside the figure, not the state.
        self.g.per = {self.sha(9): {self.ids[0]: 0.5}}
        found = self.summary()
        self.assertEqual((found["state"], found["older"]["reason"]), ("partial", "forge"))
        self.assertEqual(self.view()["older"]["reason"], "forge")

    def test_a_stale_list_comes_first(self):
        self.g.per = {self.sha(8): {self.ids[0]: 0.5}}
        self.g.older_answer = {"reason": "pilot", "opponents": 1, "of": 3, "updated": None, "overall": None}
        self.assertEqual(self.summary()["state"], "stale_list")

    def test_an_earlier_list_under_an_older_forge_is_said(self):
        # The list changed and Forge too: the earlier list has notes, but no games under today's key.
        self.g.has_notes = lambda entry, space: entry["card_sha"] == self.sha(8)
        self.g.older_by = {self.sha(8): {"reason": "forge", "opponents": 3, "of": 3, "updated": "2026-11-01T10:00:00",
                                         "overall": {"rate": 0.41, "low": 0.33, "high": 0.49}}}
        found = self.summary()
        self.assertEqual(found["state"], "stale_older")
        self.assertEqual((found["older"]["reason"], found["older"]["earlier"]), ("forge", True))
        self.assertIsNone(found["before"])
        self.assertTrue(self.view()["older"]["earlier"])
        # Once today's list has games, an earlier list's older results aren't claimed.
        self.g.per = {self.sha(9): {self.ids[0]: 0.5}}
        self.assertIsNone(self.summary()["older"])

    def test_an_older_failure_is_logged_not_raised(self):
        def broken(*args, **kwargs):
            raise RuntimeError("boom")
        self.g.older = broken
        self.assertIsNone(self.summary()["older"])


class PrivacyTests(ApiCase):

    def test_a_hidden_deck_reads_no_revision(self):
        with mock.patch.object(inventory, "deck_revisions_with_text", side_effect=AssertionError("read")):
            self.assertEqual(self.summary("user2", GRUUL), 404)
            self.assertEqual(self.summary("matt", R_ELVES), 404)
            self.assertEqual(self.view("user2", GRUUL), 404)
            self.assertEqual(self.view("matt", R_ELVES), 404)

    def test_no_revision_actor_message_or_other_deck_in_the_answers(self):
        self.g.per = {self.sha(8): {i: 0.41 for i in self.ids}, self.sha(9): {self.ids[0]: 0.6}}
        for found in (self.summary(), self.view()):
            text = json.dumps(found)
            self.assertNotIn("Secret words", text)
            self.assertNotIn("user1", text)
            self.assertNotIn('"revision"', text)
            for other in (ELVES, R_ELVES, "Elf Commander"):
                self.assertNotIn(other, text)
            self.assertIsNotNone(found["before"])

    def test_the_new_fields_are_in_every_answer(self):
        self.g.built = False
        found = self.summary()
        self.assertEqual((found["before"], found["compare"], found["older"]), (None, None, None))
        view = self.view()
        self.assertEqual((view["before"], view["compare"], view["older"]), (None, None, None))


if __name__ == "__main__":
    import unittest
    unittest.main()
