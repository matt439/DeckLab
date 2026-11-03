"""Tests for the Testing page's Popular decks board (E3-S35): GET /api/gauntlet/board
(api/gauntlet_board.board_view), and forge.gauntlet's stamps and noted that its caches go by.

They run in test_gauntlet_api's sandbox (test_api_permissions' roles and spaces: home's casual Gruul Test,
Commander Elf Commander and products, User2's own R Elves), with a FakeGauntlet whose view gives each
list and opponent its own games and whose stamps change when a list's games do. The board reads saved
games only: it never plans, estimates, saves a sample or plays. No Forge game, network, database or real
catalogue is used.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_gauntlet_board
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import feature_routes
from decklab.lib.api import gauntlet_board, gauntlet_page, guard
from decklab.lib.forge import gauntlet as real_gauntlet       # before any sandbox stands in for forge
from decklab.tests.test_api import GRUUL as GRUUL_TEXT, _write
from decklab.tests.test_gauntlet_api import (ELVES, GRUUL, POPULAR, R_ELVES, SAMPLE, WAIT, FakeGauntlet,
                                             GauntletApiTestCase)

IDS = [p[0] for p in POPULAR]
TWO = "casual/gruul-two"
ROW_KEYS = {"deck", "state", "problem", "overall", "played", "of", "games", "updated", "hardest", "before",
            "older", "playing"}


class BoardGauntlet(FakeGauntlet):
    """FakeGauntlet whose view gives each list (card_sha) the games in self.per {card_sha: {opponent id:
    rate}} (100 games each), counting views; stamps follow self.per, has_notes self.notes, noted
    self.orphans; older gives self.older_answer to the lists in self.notes without games."""

    def __init__(self, forge, results):
        super().__init__(forge, results)
        self.per, self.notes, self.orphans, self.viewed, self.older_answer = {}, set(), {}, [], None

    def plan(self, *args, **kwargs):
        raise AssertionError("the board never plans")

    def view(self, entry, chosen, keep=None, cat=None):
        self.viewed.append(entry["id"])
        rates = self.per.get(entry["card_sha"], {})
        opponents = [{"id": d, "title": d.rsplit("/", 1)[1], "tier": "medium", "style": "aggro",
                      "games": 100 if d in rates else 0, "verdict": "behind",
                      "updated": "2026-11-03T10:00:00" if d in rates else None,
                      "rate": {"value": rates[d], "low": rates[d] - 0.1, "high": rates[d] + 0.1} if d in rates else None,
                      "source": {"kind": "forge", "url": None, "file": "C:/secret.dck"}}
                     for d in chosen["decks"]]
        opponents.sort(key=lambda o: (o["rate"] is None, (o["rate"] or {}).get("low") or 0))
        played = [o for o in opponents if o["games"]]
        overall = None
        if played:
            mean = round(sum(o["rate"]["value"] for o in played) / len(played), 4)
            overall = {"key": "all", "rate": mean, "low": round(mean - 0.1, 4), "high": round(mean + 0.1, 4),
                       "spread": [0.1, 0.9], "note": ""}
        return {"opponents": opponents, "groups": {}, "overall": overall, "played": len(played),
                "of": len(opponents), "tally": None, "updated": "2026-11-03T10:00:00" if played else None,
                "games": 100 * len(played), "note": "These sampled opponents only.", "notes": []}

    def stamps(self, entry, chosen, cat, space):
        return (tuple(sorted(self.per.get(entry["card_sha"], {}).items())), entry["card_sha"] in self.notes)

    def has_notes(self, entry, space):
        return entry["card_sha"] in self.notes

    def noted(self, fmt, space):
        return dict(self.orphans.get(space, {}))

    def older(self, entry, chosen, keep=None, cat=None, today_keys=(), space="home", limit=300, played=()):
        return self.older_answer if entry["card_sha"] in self.notes and not played else None


class BoardTestCase(GauntletApiTestCase):

    def setUp(self):
        super().setUp()
        gauntlet_board.clear_cache()
        self.addCleanup(gauntlet_board.clear_cache)
        _write(self.box.magic / "decks" / "casual" / "gruul-two.md",
               GRUUL_TEXT.replace("# Gruul Test", "# Gruul Two").replace("9 Forest", "8 Forest"))
        self.g = BoardGauntlet(self.forge, self.g.results)
        self.forge.gauntlet = self.g

        def never(*args, **kwargs):
            raise AssertionError("the board never estimates")
        self.forge.estimate.minutes = never

    def board(self, who="matt", fmt="constructed"):
        return self.call(who, gauntlet_board.board_view, fmt)

    def sha(self, deck_id):
        with self.as_("matt"):
            return gauntlet_page.field_page._field_entry(self.forge, deck_id, "target")[1]["card_sha"]

    def saved_game(self):
        """A game saved in the results folder (it moves the answer's stamp, as a real one does)."""
        self.saves = getattr(self, "saves", 0) + 1
        (self.g.results / f"game-{self.saves}.json").write_text("{}" * self.saves, encoding="utf-8")

    def ids(self, answer):
        return [row["deck"]["id"] for row in answer["rows"]]


class BoardPrivacyTests(BoardTestCase):

    def test_the_route_answers_200(self):
        handler = mock.Mock(command="GET")
        handler._query.return_value = {"format": "constructed"}
        with mock.patch.object(gauntlet_board, "board_view", return_value={"rows": []}) as called:
            self.assertTrue(feature_routes.dispatch(handler, ["gauntlet", "board"], {}))
        called.assert_called_once_with(format="constructed")
        handler._send_json.assert_called_once_with(200, {"rows": []})

    def test_another_format_is_refused(self):
        self.assertEqual(self.board("matt", "modern"), 400)

    def test_each_viewer_sees_only_their_own_decks(self):
        home, member = self.board("matt"), self.board("user2")
        self.assertIn(GRUUL, self.ids(home))
        self.assertNotIn(R_ELVES, self.ids(home))
        self.assertEqual(self.ids(member), [R_ELVES])
        text = json.dumps(member)
        for title in ("Gruul Test", "Elf Commander", "Test Precon", "Beginner Box", "gruul"):
            self.assertNotIn(title, text)
        self.assertNotIn("R Elves", json.dumps(self.board("user1")))

    def test_a_hidden_deck_is_never_read(self):
        read = []
        real = gauntlet_board.decks.load_deck
        with mock.patch.object(gauntlet_board.decks, "load_deck", side_effect=lambda i, v: read.append(i) or real(i, v)):
            self.board("user2")
        self.assertEqual(read, [R_ELVES])

    def test_a_public_space_shows_its_decks(self):
        with mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"user2"})):
            found = self.board("matt")
        self.assertIn(R_ELVES, self.ids(found))
        self.assertNotIn(R_ELVES, self.ids(self.board("matt")))     # not from the other viewer's answer

    def test_halves_and_the_other_format_are_left_out(self):
        found = self.ids(self.board("matt"))
        self.assertFalse(any(i.startswith("product/fdn-beginner-box/") for i in found))
        self.assertNotIn(ELVES, found)
        self.assertEqual(self.board("matt", "commander")["rows"], [])     # the fake has no Commander decks

    def test_build_command_is_for_admins_only(self):
        self.g.built = False
        admin, member = self.board("matt"), self.board("user1")
        self.assertEqual((admin["state"], member["state"]), ("no_catalogue", "no_catalogue"))
        self.assertEqual(admin["build_command"], "python -m decklab.lib.forge gauntlet build --format constructed")
        self.assertIsNone(member["build_command"])
        self.assertEqual(member["rows"], [])

    def test_no_inventory_fields_and_no_file_path(self):
        self.g.per = {self.sha(GRUUL): {i: 0.5 for i in IDS}}
        found = self.board("matt")
        self.assertEqual(set(found), {"format", "state", "build_command", "sample", "default_budget", "note",
                                      "notes", "rows"})
        for row in found["rows"]:
            self.assertEqual(set(row), ROW_KEYS)
            self.assertEqual(set(row["deck"]), {"id", "title", "kind", "version", "card_sha"})
        text = json.dumps(found, allow_nan=False)
        for word in ("owned", "missing", "status", "versions", "revision", "secret"):
            self.assertNotIn(f'"{word}"' if word != "secret" else word, text)

    def test_playing_never_names_who_started_it(self):
        self.set_mode("everyone")
        self.playing()
        self.assertIsInstance(self.run_as("matt", GRUUL), dict)
        self.assertTrue(self.g.started.wait(WAIT))
        row = next(r for r in self.board("user1")["rows"] if r["deck"]["id"] == GRUUL)
        self.assertEqual(row["playing"], {"status": "running", "done": 50, "total": 200, "standard": True})
        self.assertNotIn("Matt", json.dumps(self.board("user1")))
        self.finish()
        row = next(r for r in self.board("user1")["rows"] if r["deck"]["id"] == GRUUL)
        self.assertIsNone(row["playing"])
        self.assertEqual(self.g.runs[0][1], SAMPLE)


class BoardRowTests(BoardTestCase):

    def test_rows_untested_partial_and_done_and_their_order(self):
        sha = self.sha(GRUUL)
        found = self.board("matt")
        row = next(r for r in found["rows"] if r["deck"]["id"] == GRUUL)
        self.assertEqual((row["state"], row["played"], row["of"], row["overall"]), ("untested", 0, 3, None))
        self.assertEqual(found["sample"], {"id": SAMPLE, "size": 24, "tiers": ["medium", "hard"]})
        self.assertEqual(found["default_budget"], "fixed:100")
        self.assertIn("not a rating", found["note"])
        self.g.per = {sha: {IDS[0]: 0.4}}
        self.saved_game()
        row = next(r for r in self.board("matt")["rows"] if r["deck"]["id"] == GRUUL)
        self.assertEqual((row["state"], row["played"], row["games"]), ("partial", 1, 100))
        self.assertEqual(row["overall"], {"rate": 0.4, "low": 0.3, "high": 0.5})
        self.assertEqual(row["hardest"]["title"], IDS[0].rsplit("/", 1)[1])
        self.assertNotIn("file", row["hardest"]["source"])
        self.g.per = {sha: {i: 0.6 for i in IDS}}
        self.saved_game()
        found = self.board("matt")
        self.assertEqual(found["rows"][0]["deck"]["id"], GRUUL)        # a figure comes first
        self.assertEqual((found["rows"][0]["state"], found["rows"][0]["deck"]["card_sha"]), ("done", sha))

    def test_the_order_by_rate_then_low_then_title_and_untested_last(self):
        def row(i, state, rate=None, low=None, title=None):
            return {"deck": {"id": i, "title": title or i}, "state": state,
                    "overall": None if rate is None else {"rate": rate, "low": low}}
        rows = [row("e", "unreadable"), row("d", "untested"), row("c", "stale_list"), row("b", "partial", 0.5, 0.2),
                row("a", "done", 0.5, 0.4), row("f", "done", 0.7, 0.1), row("g", "stale_older"), row("h", "untested")]
        self.assertEqual([r["deck"]["id"] for r in sorted(rows, key=gauntlet_board._order)],
                         ["f", "a", "b", "c", "g", "d", "h", "e"])

    def test_an_unreadable_list_says_so(self):
        with mock.patch.object(self.forge, "entry", side_effect=self.forge.ForgeError("no")):
            found = self.board("matt")
        row = next(r for r in found["rows"] if r["deck"]["id"] == GRUUL)
        self.assertEqual((row["state"], row["problem"], row["deck"]["card_sha"]),
                         ("unreadable", "Forge can't read this list.", None))
        self.assertIsNone(row["playing"])

    def test_older_results_only_for_a_list_with_notes(self):
        sha = self.sha(GRUUL)
        self.g.notes = {sha}
        self.g.older_answer = {"reason": "forge", "opponents": 2, "of": 3, "updated": "2026-10-01T10:00:00",
                               "overall": {"rate": 0.45, "low": 0.3, "high": 0.6, "spread": [0, 1]}}
        with mock.patch.object(gauntlet_board.gauntlet_page.gauntlet_before, "_earlier",
                               side_effect=AssertionError("no history walk")):
            row = next(r for r in self.board("matt")["rows"] if r["deck"]["id"] == GRUUL)
        self.assertEqual(row["state"], "stale_older")
        self.assertEqual(row["older"], {"reason": "forge", "overall": {"rate": 0.45, "low": 0.3, "high": 0.6},
                                        "updated": "2026-10-01T10:00:00", "earlier": False})

    def test_no_history_walk_without_orphan_notes(self):
        with mock.patch.object(gauntlet_board.gauntlet_page.gauntlet_before, "_earlier",
                               side_effect=AssertionError("no history walk")):
            found = self.board("matt")
        self.assertTrue(all(r["state"] in ("untested", "unreadable") for r in found["rows"]))
        self.assertEqual(found["notes"], [])

    def test_a_stale_list_from_the_history_walk(self):
        self.g.orphans = {"home": {"d" * 64: (1, 2)}}
        before = {"rate": 0.55, "low": 0.45, "high": 0.65, "played": 3, "of": 3, "games": 300,
                  "updated": "2026-10-20T10:00:00"}
        fields = {"before": before, "compare": None, "older": None, "notes": [], "rows": {}}
        with mock.patch.object(gauntlet_board.gauntlet_page.gauntlet_before, "fields", return_value=fields) as walked:
            row = next(r for r in self.board("matt")["rows"] if r["deck"]["id"] == GRUUL)
        self.assertTrue(walked.called)
        self.assertEqual(row["state"], "stale_list")
        self.assertEqual(row["before"], {"rate": 0.55, "low": 0.45, "high": 0.65, "updated": "2026-10-20T10:00:00"})

    def test_the_history_walks_are_bounded(self):
        self.g.orphans = {"home": {"d" * 64: (1, 2)}}
        empty = {"before": None, "compare": None, "older": None, "notes": [], "rows": {}}
        with mock.patch.object(gauntlet_board, "MAX_WALKS", 1), \
                mock.patch.object(gauntlet_board.gauntlet_page.gauntlet_before, "fields", return_value=empty) as walked:
            found = self.board("matt")
            walkable = sum(1 for r in found["rows"] if r["state"] == "untested")
            self.assertGreater(walkable, 1)          # the sandbox has more than one untested home list
            self.assertEqual(walked.call_count, 1)
            self.assertEqual(found["notes"], ["Some lists' earlier results are still being looked at."])
            again = self.board("matt")              # the rest are filled in on later reads
            self.assertEqual(walked.call_count, 2)
            while again["notes"]:
                again = self.board("matt")
            self.assertEqual(walked.call_count, walkable)
            self.board("matt")
            self.assertEqual(walked.call_count, walkable)     # kept now

    def test_it_never_plans_estimates_saves_or_plays(self):
        self.g.per = {self.sha(GRUUL): {i: 0.5 for i in IDS}}
        self.board("matt")
        self.assertEqual((self.g.saved, self.g.runs, self.g.plans), ({}, [], []))


class BoardCacheTests(BoardTestCase):

    def test_a_second_read_is_kept(self):
        self.board("matt")
        views = len(self.g.viewed)
        self.board("matt")
        self.assertEqual(len(self.g.viewed), views)

    def test_only_the_changed_row_is_worked_out_again(self):
        self.board("matt")
        first = list(self.g.viewed)
        self.assertIn(GRUUL, first)
        self.g.per = {self.sha(GRUUL): {IDS[0]: 0.4}}
        self.saved_game()
        found = self.board("matt")
        self.assertEqual(self.g.viewed[len(first):], [GRUUL])
        row = next(r for r in found["rows"] if r["deck"]["id"] == GRUUL)
        self.assertEqual(row["state"], "partial")

    def test_rows_are_shared_but_answers_are_per_viewer(self):
        self.board("matt")
        views = len(self.g.viewed)
        self.board("user1")                         # another viewer of home: its rows are kept
        self.assertEqual(len(self.g.viewed), views)
        self.assertEqual(self.ids(self.board("user2")), [R_ELVES])


class StampsTests(unittest.TestCase):
    """forge.gauntlet.stamps and noted over a results folder of their own (matchup keys stubbed)."""

    def setUp(self):
        real = self.real = real_gauntlet
        tmp = tempfile.TemporaryDirectory(prefix="decklab-gauntlet-stamps-")
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        patcher = mock.patch.object(real, "RESULTS_DIR", self.folder)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _entry(self, sha="a" * 64):
        return {"id": GRUUL, "version": "target", "title": "Gruul Test", "kind": "constructed", "card_sha": sha}

    def test_stamps_are_the_keys_field_reads(self):
        cat = {"decks": [{"id": i, "title": t, "kind": "constructed", "cards": [], "playable": True}
                         for i, t, *_ in POPULAR]}
        entries = {d["id"]: {"id": d["id"], "kind": "constructed", "card_sha": str(n) * 64}
                   for n, d in enumerate(cat["decks"], 1)}
        keys = {i: f"{n:064x}" for n, i in enumerate(IDS, 1)}
        with mock.patch.object(self.real, "_to_entry", side_effect=lambda d: entries[d["id"]]), \
                mock.patch.object(self.real.lists, "matchup_key", side_effect=lambda a, b: keys[b["id"]]):
            chosen = {"decks": IDS + ["gauntlet:gone"]}
            first = self.real.stamps(self._entry(), chosen, cat)
            self.assertEqual([k for k, _ in first[:-1]], [keys[i] for i in IDS])     # the gone deck left out
            self.assertTrue(all(stat is None for _, stat in first))
            (self.folder / f"{keys[IDS[1]]}.json").write_text("{}", encoding="utf-8")
            second = self.real.stamps(self._entry(), chosen, cat)
            self.assertIsNotNone(second[1][1])
            self.assertNotEqual(first, second)
            # field._pair_state reads exactly these keys' files.
            loaded = []
            with mock.patch.object(self.real.field.saved, "load", side_effect=lambda k, d: loaded.append(k)):
                for opponent in entries.values():
                    self.real.field._pair_state(self._entry(), opponent, self.folder)
            self.assertEqual(loaded, [k for k, _ in second[:-1]])

    def test_noted_lists_only_the_spaces_format_notes(self):
        notes = self.folder / "field"
        notes.mkdir()
        for name in (f"{'a' * 64}-Constructed-home.json", f"{'b' * 64}-Constructed-user2.json",
                     f"{'c' * 64}-Commander-home.json", f"{'d' * 64}-Constructed.json", "junk-Constructed-home.json"):
            (notes / name).write_text("{}", encoding="utf-8")
        self.assertEqual(set(self.real.noted("constructed", "home")), {"a" * 64})
        self.assertEqual(set(self.real.noted("commander", "home")), {"c" * 64})
        self.assertEqual(set(self.real.noted("constructed", "user2")), {"b" * 64})


if __name__ == "__main__":
    unittest.main()
