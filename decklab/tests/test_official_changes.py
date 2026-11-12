"""Game Changer and Commander ban changes between card data updates (E9-S36): official_lists.diff_official, the
change kept beside the card index (save_changes, read_changes), cards update reading the old index before it's
overwritten, and GET /api/official-changes (lib/api/official_changes.py) with the deck privacy rules (E10-S30).

Fixture indexes only: no card data update, download or live data.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_official_changes
"""
import gzip
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import card_index, cards, feature_routes, official_lists
from decklab.lib.api import official_changes as oc
from decklab.tests.test_api import _write
from decklab.tests.test_cards import BULK_DATES, CARDS_FILE, TAGS_FILE
from decklab.tests.test_global_search import GlobalSearchTestCase
from decklab.tests.test_inventory_privacy import hides_every_deck


def card(oracle_id, changer=False, legality="legal"):
    return {"oracle_id": oracle_id, "game_changer": changer, "commander_legality": legality}


def index(cards_, when="2026-11-01T09:00:00.000+00:00"):
    return {"bulk": {"default_cards": when, "oracle_tags": when}, "cards": cards_}


OLD = index({"Sol Ring": card("sol", True), "Rhystic Study": card("rhy"), "Black Lotus": card("lotus"),
             "Wrath of God": card("wrath", legality="banned"), "Elvish Mystic": card("mystic")},
            "2026-10-25T09:00:00.000+00:00")
NEW = index({"Sol Ring": card("sol"), "Rhystic Study": card("rhy", True), "Black Lotus": card("lotus", legality="banned"),
             "Wrath of God": card("wrath"), "Elvish Mystic": card("mystic"),
             "Brand New Card": card("new", True, "banned")})
EXPECTED = [{"name": "Rhystic Study", "kind": "game_changer_added"},
            {"name": "Sol Ring", "kind": "game_changer_removed"},
            {"name": "Black Lotus", "kind": "banned"},
            {"name": "Wrath of God", "kind": "unbanned"}]


class DiffTests(unittest.TestCase):

    def test_each_kind_of_change_with_both_data_dates(self):
        change = official_lists.diff_official(OLD, NEW)
        self.assertEqual(change, {"old_date": "2026-10-25", "new_date": "2026-11-01", "changes": EXPECTED})

    def test_a_card_new_to_the_data_changes_nothing(self):
        names = [c["name"] for c in official_lists.diff_official(OLD, NEW)["changes"]]
        self.assertNotIn("Brand New Card", names)

    def test_the_same_data_is_no_change(self):
        self.assertEqual(official_lists.diff_official(NEW, NEW)["changes"], [])

    def test_a_renamed_card_is_matched_by_its_oracle_id(self):
        old = index({"Old Name": card("x")})
        new = index({"New Name": card("x", True)})
        self.assertEqual(official_lists.diff_official(old, new)["changes"],
                         [{"name": "New Name", "kind": "game_changer_added"}])

    def test_restricted_and_not_legal_are_not_bans(self):
        old = index({"A": card("a", legality="not_legal"), "B": card("b", legality="banned")})
        new = index({"A": card("a", legality="legal"), "B": card("b", legality="banned")})
        self.assertEqual(official_lists.diff_official(old, new)["changes"], [])

    def test_flags_that_dont_read_as_flags_are_left_out(self):
        old = index({"A": {"oracle_id": "a", "commander_legality": "legal"},        # no game_changer: older data
                     "B": {"oracle_id": "b", "game_changer": "yes", "commander_legality": "legal"}, "C": "x"})
        new = index({"A": card("a", True), "B": card("b", True), "C": card("c", True)})
        self.assertEqual(official_lists.diff_official(old, new)["changes"], [])

    def test_data_that_isnt_an_index_raises(self):
        for bad in (None, {}, {"cards": []}, "index"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                official_lists.diff_official(bad, NEW)

    def test_far_more_changes_than_a_list_makes_claims_nothing(self):
        old = index({f"C{i}": card(f"c{i}") for i in range(official_lists.MAX_CHANGES + 1)})
        new = index({f"C{i}": card(f"c{i}", True) for i in range(official_lists.MAX_CHANGES + 1)})
        with self.assertRaisesRegex(ValueError, "more than a list change"):
            official_lists.diff_official(old, new)

    def test_unknown_dates_are_none(self):
        change = official_lists.diff_official({"cards": OLD["cards"]}, index(NEW["cards"], "soon"))
        self.assertEqual((change["old_date"], change["new_date"]), (None, None))

    def test_a_snapshot_diffs_as_its_index_does(self):
        self.assertEqual(official_lists.diff_official(official_lists.snapshot(OLD), NEW),
                         official_lists.diff_official(OLD, NEW))


class KeptTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = self.tmp / "official_changes.json"

    def test_a_change_is_kept_and_read_back(self):
        with mock.patch.object(official_lists, "_now", return_value=card_index._now()):
            self.assertTrue(official_lists.save_changes(official_lists.diff_official(OLD, NEW), self.path))
        kept = official_lists.read_changes(self.path)
        self.assertEqual((kept["old_date"], kept["new_date"], kept["changes"]), ("2026-10-25", "2026-11-01", EXPECTED))
        self.assertIsNotNone(kept["recorded_at"])
        self.assertEqual(list(self.tmp.iterdir()), [self.path])         # written whole: no temporary file left

    def test_an_empty_change_keeps_the_last_one(self):
        official_lists.save_changes(official_lists.diff_official(OLD, NEW), self.path)
        before = self.path.read_bytes()
        self.assertFalse(official_lists.save_changes(official_lists.diff_official(NEW, NEW), self.path))
        self.assertEqual(self.path.read_bytes(), before)
        log = []
        self.assertIsNone(official_lists.record_changes(NEW, NEW, log.append, self.path))
        self.assertIn("no change", log[0])
        self.assertEqual(self.path.read_bytes(), before)

    def test_record_changes_logs_the_counts(self):
        log = []
        change = official_lists.record_changes(OLD, NEW, log.append, self.path)
        self.assertEqual(change["changes"], EXPECTED)
        self.assertIn("since the card data of 2026-10-25", log[0])
        self.assertIn("became a game changer: 1", log[0])

    def test_missing_damaged_or_foreign_files_read_as_nothing_kept(self):
        self.assertIsNone(official_lists.read_changes(self.path))
        for text in ("{not json", json.dumps({"format": 99, "changes": EXPECTED}), json.dumps([1]),
                     json.dumps({"format": 1, "changes": [{"name": "X", "kind": "made-up"}]})):
            with self.subTest(text=text):
                self.path.write_text(text, encoding="utf-8")
                self.assertIsNone(official_lists.read_changes(self.path))

    def test_the_default_file_sits_beside_the_card_index(self):
        with mock.patch.object(cards, "INDEX_FILE", self.tmp / "index.json.gz"):
            self.assertEqual(official_lists.changes_path(), self.path)


class UpdateTests(unittest.TestCase):
    """cards update reads the old index's flags before it's overwritten and keeps the change."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for kind, source in (("default_cards", CARDS_FILE), ("oracle_tags", TAGS_FILE)):
            with gzip.open(self.tmp / f"{kind}.jsonl.gz", "wb") as out:
                out.write(source.read_bytes())
        now = card_index._now().isoformat(timespec="seconds")
        cards._write_json(self.tmp / "bulk.json", {
            kind: {"updated_at": BULK_DATES[kind], "uri": "fixture", "downloaded_at": now} for kind in cards.BULK_TYPES})
        self.index_file = self.tmp / "index.json.gz"
        self.changes = self.tmp / "official_changes.json"
        for patcher in (mock.patch.object(cards, "SCRYFALL_DIR", self.tmp),
                        mock.patch.object(cards, "INDEX_FILE", self.index_file),
                        mock.patch.object(cards, "BULK_META_FILE", self.tmp / "bulk.json"),
                        mock.patch.object(cards, "_get_json", side_effect=AssertionError("no network")),
                        mock.patch.object(cards, "_download", side_effect=AssertionError("no network")),
                        mock.patch.object(cards, "_update_combos"),
                        mock.patch.object(cards, "_update_official_lists"),
                        mock.patch.object(cards, "_update_rulings"),
                        mock.patch.object(official_lists, "CHANGES_FILE", None),
                        mock.patch.object(cards, "_index", None)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.log = []

    def old_index(self):
        """The fixture's index as it was a week earlier: other flags on four cards."""
        old = cards.build_index(CARDS_FILE, TAGS_FILE, {**BULK_DATES, "default_cards": "2026-09-21T21:00:00.000+00:00"},
                                log=lambda *a: None)
        old["cards"]["Sol Ring"]["game_changer"] = True
        old["cards"]["Rhystic Study"]["game_changer"] = False
        old["cards"]["Wrath of God"]["commander_legality"] = "banned"
        old["cards"]["Black Lotus"]["commander_legality"] = "legal"
        cards.write_index(old, self.index_file)

    def test_an_update_keeps_the_change_with_both_data_dates(self):
        self.old_index()
        self.assertTrue(cards.update(log=self.log.append))
        kept = official_lists.read_changes(self.changes)
        self.assertEqual((kept["old_date"], kept["new_date"]), ("2026-09-21", BULK_DATES["default_cards"][:10]))
        self.assertEqual(kept["changes"], EXPECTED)
        self.assertTrue(any("changed since the card data of 2026-09-21" in line for line in self.log), self.log)
        self.assertTrue(cards.card("Rhystic Study")["game_changer"])     # the new index is the one in use

    def test_a_first_build_claims_nothing(self):
        self.assertTrue(cards.update(log=self.log.append))
        self.assertFalse(self.changes.exists())

    def test_an_unreadable_old_index_claims_nothing_and_the_update_succeeds(self):
        self.old_index()
        official_lists.save_changes({"old_date": "2026-01-01", "new_date": "2026-01-08",
                                     "changes": [{"name": "Sol Ring", "kind": "banned"}]}, self.changes)
        before = self.changes.read_bytes()
        damaged = bytearray(self.index_file.read_bytes())
        for i in range(20, 84):
            damaged[i] ^= 0xFF
        self.index_file.write_bytes(bytes(damaged))
        self.assertTrue(cards.update(log=self.log.append))
        self.assertEqual(self.changes.read_bytes(), before)              # the last kept change stands
        self.assertTrue(any("can't be read" in line and "no change is claimed" in line for line in self.log), self.log)
        self.assertTrue(cards.card("Rhystic Study")["game_changer"])      # the rebuilt index is in use

    def test_a_failed_save_never_fails_the_update(self):
        self.old_index()
        with mock.patch.object(official_lists, "save_changes", side_effect=OSError("disk full")):
            self.assertTrue(cards.update(log=self.log.append))
        self.assertFalse(self.changes.exists())
        self.assertTrue(any("wasn't kept" in line and "still succeeded" in line for line in self.log), self.log)
        self.assertTrue(cards.card("Rhystic Study")["game_changer"])

    def test_the_old_index_is_read_before_it_is_overwritten(self):
        self.old_index()
        order = []
        real_read, real_write = official_lists.read_snapshot, cards.write_index
        with mock.patch.object(official_lists, "read_snapshot", side_effect=lambda p: order.append("read") or real_read(p)), \
                mock.patch.object(cards, "write_index", side_effect=lambda *a: order.append("write") or real_write(*a)):
            cards.update(log=self.log.append)
        self.assertEqual(order, ["read", "write"])

    def test_an_up_to_date_index_reads_nothing(self):
        self.assertTrue(cards.update(log=self.log.append))
        with mock.patch.object(official_lists, "read_snapshot", side_effect=AssertionError("not rebuilt")):
            self.assertFalse(cards.update(log=self.log.append))


STUDY = """# Study Hall

- **Format:** Commander
- **Played by:** user
- **Status:** building
- **Target bracket:** 2

## Decklist

```
Commander
1 Ghalta, Primal Hunger (RIX) 130

Deck
1 Rhystic Study
1 Sol Ring (ECC) 57
```
"""

TRIAL = STUDY.replace("# Study Hall", "# A Trial").replace("- **Status:** building", "- **Status:** idea\n- **Trial:** precon TestDinos_TST")
MEMBER = STUDY.replace("# Study Hall", "# Member Study").replace("- **Played by:** user\n", "")
KEPT = {"format": 1, "recorded_at": "2026-11-10T09:00:00+00:00", "old_date": "2026-11-03", "new_date": "2026-11-10",
        "changes": [{"name": "Rhystic Study", "kind": "game_changer_added"},
                    {"name": "Sol Ring", "kind": "game_changer_removed"},
                    {"name": "Black Lotus", "kind": "banned"}]}


class ViewTests(GlobalSearchTestCase):

    def setUp(self):
        super().setUp()
        _write(self.box.magic / "decks" / "commander" / "study-hall.md", STUDY)
        _write(self.box.magic / "decks" / "commander" / "a-trial.md", TRIAL)
        _write(self.box.magic / "people" / "user2" / "decks" / "commander" / "member-study.md", MEMBER)
        self.kept = self.box.data / "scryfall" / "official_changes.json"
        _write(self.kept, json.dumps(KEPT))

    def ask(self, profile):
        with self.as_(profile):
            return oc.view()

    @staticmethod
    def decks(answer, name):
        return [d["id"] for d in next(c for c in answer["cards"] if c["name"] == name)["decks"]]

    def test_the_cards_and_the_commander_decks_holding_them_with_today_s_minimum(self):
        answer = self.ask("matt")
        self.assertEqual(answer["change"], {"recorded_at": "2026-11-10T09:00:00+00:00", "old_date": "2026-11-03",
                                            "new_date": "2026-11-10"})
        self.assertEqual([(c["name"], c["kind"], c["words"]) for c in answer["cards"]],
                         [("Rhystic Study", "game_changer_added", "Became a Game Changer"),
                          ("Sol Ring", "game_changer_removed", "No longer a Game Changer"),
                          ("Black Lotus", "banned", "Banned in Commander")])
        self.assertEqual(self.decks(answer, "Rhystic Study"), ["commander/study-hall"])
        # A Commander product's decks are home's Commander decks too (the intact precon holds a Sol Ring).
        self.assertEqual(self.decks(answer, "Sol Ring"),
                         ["commander/elf-commander", "product/fdc-test-precon", "commander/study-hall"])
        self.assertEqual(self.decks(answer, "Black Lotus"), [])
        study = next(c for c in answer["cards"] if c["name"] == "Rhystic Study")["decks"][0]
        # Today's flags: Rhystic Study is a Game Changer in the fixture's data, so Bracket 3 at least.
        self.assertEqual((study["title"], study["status"], study["version"], study["target_bracket"], study["minimum"]),
                         ("Study Hall", "building", "target", 2, 3))
        self.assertEqual(study["label"], "Bracket 3 or higher")
        elf = next(c for c in answer["cards"] if c["name"] == "Sol Ring")["decks"][0]
        self.assertEqual(elf["minimum"], 1)
        self.assertEqual(next(c for c in answer["cards"] if c["name"] == "Rhystic Study")["now"],
                         {"game_changer": True, "banned": False})
        self.assertEqual(answer["unread"], 0)

    def test_a_trial_is_not_one_of_ours(self):
        self.assertNotIn("commander/a-trial", json.dumps(self.ask("matt")))

    def test_a_member_sees_only_their_own_decks(self):
        answer = self.ask("user2")
        self.assertEqual(self.decks(answer, "Rhystic Study"), ["user2/commander/member-study"])
        text = json.dumps(answer)
        for secret in ("study-hall", "elf-commander", "Study Hall", "Elf Commander", "product/", "one of"):
            self.assertNotIn(secret, text)

    def test_matt_has_no_admin_override(self):
        self.assertNotIn("member-study", json.dumps(self.ask("matt")))

    def test_hidden_decks_are_never_named_or_counted(self):
        with self.as_("matt"), mock.patch.object(oc.guard, "deck_reader", hides_every_deck):
            answer = oc.view()
        self.assertTrue(all(c["decks"] == [] for c in answer["cards"]))
        self.assertEqual(answer["unread"], 0)
        self.assertEqual([c["name"] for c in answer["cards"]], ["Rhystic Study", "Sol Ring", "Black Lotus"])

    def test_a_home_page_naming_nobody_gets_the_cards_but_no_decks(self):
        with self.at_home(None):
            answer = oc.view()
        self.assertTrue(all(c["decks"] == [] for c in answer["cards"]))

    def test_no_change_kept_or_an_unreadable_file_claims_none(self):
        self.kept.unlink()
        self.assertEqual(self.ask("matt"), {"change": None})
        self.kept.write_text("{damaged", encoding="utf-8")
        self.assertEqual(self.ask("matt"), {"change": None})

    def test_a_built_deck_is_checked_in_its_built_version(self):
        built = STUDY.replace("- **Status:** building", "- **Status:** built\n- **Built version:** owned-only") \
            + "\n### Substitute version (owned and incoming cards)\n\n```\nCommander\n1 Ghalta, Primal Hunger\n\nDeck\n1 Sol Ring\n```\n"
        _write(self.box.magic / "decks" / "commander" / "study-hall.md", built)
        answer = self.ask("matt")
        self.assertEqual(self.decks(answer, "Rhystic Study"), [])          # only its Planned list has it
        held = next(c for c in answer["cards"] if c["name"] == "Sol Ring")["decks"]
        study = next(d for d in held if d["id"] == "commander/study-hall")
        self.assertEqual((study["version"], study["minimum"]), ("owned", 1))

    def test_an_unreadable_deck_is_counted_not_named(self):
        with mock.patch.object(oc.decks, "load_deck", side_effect=oc.decks.DeckFileError("C:/secret/path")):
            answer = self.ask("matt")
        self.assertEqual(answer["unread"], 3)        # elf-commander, study-hall and the precon
        self.assertNotIn("secret", json.dumps(answer))

    def test_the_route_is_a_get_with_no_parameters(self):
        gets, _ = feature_routes.route_tables()
        self.assertEqual(gets[("official-changes",)], (oc.view, ()))
        self.assertEqual(feature_routes.ACCESS[("GET", "official-changes")], "viewer-filtered")


if __name__ == "__main__":
    unittest.main()
