"""Tests for decklab.lib.precons (MTGJSON's deck lists, cached) and
decklab.lib.api.precons (the Collection page's "Add a precon").

MTGJSON is never reached: the lists are written into the sandbox's cache as
fresh copies, and precons._fetch raises if anything asks for it (tests that
are about fetching patch it themselves). Runs in test_collection_edit's
sandbox (roles and the user2 and user3 spaces).

Run from the repo root: python -m unittest decklab.tests.test_precons
"""
import http.client
import json
import os
import time
from unittest import mock

from decklab.lib import precons
from decklab.lib.api import precons as api
from decklab.tests.test_api import _write
from decklab.tests.test_collection_edit import CollectionEditTestCase


def card(name, code, number, count=1, foil=False, **extra):
    return {"name": name, "setCode": code, "number": number, "count": count, "isFoil": foil, **extra}


DECK_LIST = {"meta": {"date": "2026-10-08", "version": "5.3.0"}, "data": [
    {"code": "TST", "fileName": "TestDinos_TST", "name": "Test Dinos", "releaseDate": "2026-10-02",
     "source": "https://magic.wizards.com/en/news/test", "type": "Commander Deck"},
    {"code": "TST", "fileName": "ElfTheme_TST", "name": "Elf Theme", "releaseDate": "2025-01-01",
     "source": "https://mtg.wiki/page/Elf_Theme", "type": "Theme Deck"},
    {"code": "TST", "fileName": "Unfinished_TST", "name": "Unfinished", "releaseDate": "2026-11-13",
     "source": "", "type": "Commander Deck"},
    {"code": "SLD", "fileName": "SomeDrop_SLD", "name": "Some Drop", "releaseDate": "2026-09-01",
     "source": "", "type": "Secret Lair Drop"},
    {"code": "TST", "fileName": "OnlineOnly_TST", "name": "Online Only", "releaseDate": "2026-09-01",
     "source": "", "type": "MTGO Theme Deck"},
    {"code": "TST", "fileName": "../escape", "name": "Bad", "releaseDate": "2026-09-01",
     "source": "", "type": "Theme Deck"},
    {"code": "WC00", "fileName": "Finkel_WC00", "name": "Finkel", "releaseDate": "2000-08-01",
     "source": "", "type": "World Championship Deck"},
]}
SET_LIST = {"meta": {}, "data": [{"code": "TST", "name": "Test Commander"}]}
DINOS = {"data": {
    "name": "Test Dinos", "code": "TST", "type": "Commander Deck",
    "commander": [card("Ghalta, Primal Hunger", "RIX", "130", foil=True)],
    # An oversized display card: not one the card data has to play with, so only counted.
    "displayCommander": [card("Ghalta, Primal Hunger", "ORIX", "1", foil=True)],
    "mainBoard": [card("Llanowar Elves", "FDN", "227", 2), card("Elvish Mystic", "CMM", "648"),
                  card("Sol Ring", "ECC", "57"), card("Forest", "FDN", "280", 20)],
    "sideBoard": [], "tokens": [{"name": "Dinosaur", "count": 3}, {"name": "Dinosaur", "count": 1}],
}}
ELVES = {"data": {
    "name": "Elf Theme", "code": "TST", "type": "Theme Deck",
    "mainBoard": [card("Llanowar Elves", "FDN", "227", 4), card("Elvish Mystic", "CMM", "648", 4)],
    "sideBoard": [card("Pick Your Poison", "MKM", "170", 2)],
}}
UNFINISHED = {"data": {
    "name": "Unfinished", "code": "TST", "type": "Commander Deck",
    "commander": [card("Ghalta, Primal Hunger", "RIX", "130", foil=True)],
    "mainBoard": [card("Some New Card", "TST", "999"), card("Sol Ring", "ECC", "57", "x"),
                  card("Forest", "FDN", "281", 10, isFullArt=True)],
}}


class PreconTestCase(CollectionEditTestCase):

    def setUp(self):
        super().setUp()
        self.cache = self.box.data / "mtgjson"
        self.seed("DeckList.json", DECK_LIST)
        self.seed("SetList.json", SET_LIST)
        for file, data in (("TestDinos_TST", DINOS), ("ElfTheme_TST", ELVES), ("Unfinished_TST", UNFINISHED)):
            self.seed(f"decks/{file}.json", data)
        for target, name, value in ((precons, "CACHE", self.cache), (api, "_added_on", lambda: "2026-10-10"),
                                    (precons, "_fetch", mock.Mock(side_effect=AssertionError("no network"))),
                                    (precons, "_failed", {}), (precons, "_kept", {})):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def listed(self, file, data, kind="Commander Deck"):
        """List one more deck (DECK_LIST's, plus it), with data as its file."""
        entry = {"code": "TST", "fileName": file, "name": data["data"]["name"], "releaseDate": "2026-01-01",
                 "source": "", "type": kind}
        self.seed("DeckList.json", dict(DECK_LIST, data=DECK_LIST["data"] + [entry]))
        self.seed(f"decks/{file}.json", data)

    def seed(self, name, data, age=0):
        path = self.cache / name
        _write(path, json.dumps(data))
        if age:
            when = time.time() - age
            os.utime(path, (when, when))
        return path

    def add(self, file="TestDinos_TST", space="user2", profile=None, title=None, **data):
        # By the space's own person by default: a deck is made only where its maker sees decks (E10-S30).
        profile = profile or ("matt" if space == "home" else space)
        data.setdefault("sha256", self.rows(space)["sha256"])
        return self.call(api.add_precon, profile, space=space, file=file,
                         title=title or api.precon_preview(file, space)["title"], **data)

    def writes_made(self):
        """How many writes the sandbox's inventory has recorded (a refusal adds none)."""
        return len(self.writes)


class ListTests(PreconTestCase):

    def test_paper_decks_newest_first(self):
        view = api.precons_view()
        self.assertEqual(view["date"], "2026-10-08")
        self.assertEqual([d["file"] for d in view["decks"]], ["Unfinished_TST", "TestDinos_TST", "ElfTheme_TST"])
        self.assertEqual(view["decks"][1], {
            "file": "TestDinos_TST", "name": "Test Dinos", "code": "tst", "set_name": "Test Commander",
            "type": "Commander Deck", "released": "2026-10-02", "source": "https://magic.wizards.com/en/news/test"})
        self.assertFalse(view["more"])

    def test_search_by_name_set_and_type(self):
        for q, files in (("dinos", ["TestDinos_TST"]), ("test commander", ["Unfinished_TST", "TestDinos_TST",
                                                                             "ElfTheme_TST"]),
                         ("theme", ["ElfTheme_TST"]), ("ELF tst", ["ElfTheme_TST"]), ("drop", [])):
            with self.subTest(q=q):
                self.assertEqual([d["file"] for d in api.precons_view(q)["decks"]], files)
        with mock.patch.object(api, "SEARCH_LIMIT", 2):
            view = api.precons_view()
        self.assertEqual((len(view["decks"]), view["more"]), (2, True))

    def test_a_stale_list_is_fetched_again(self):
        self.seed("DeckList.json", DECK_LIST, age=precons.TTL + 60)
        newer = dict(DECK_LIST, data=DECK_LIST["data"][:1])
        with mock.patch.object(precons, "_fetch", return_value=json.dumps(newer).encode()) as fetch:
            self.assertEqual([d["file"] for d in api.precons_view()["decks"]], ["TestDinos_TST"])
        fetch.assert_called_once_with(precons.LIST_URL, precons.MAX_LIST_BYTES)

    def test_mtgjson_down_uses_an_old_copy_else_502(self):
        self.seed("DeckList.json", DECK_LIST, age=precons.TTL + 60)
        with mock.patch.object(precons, "_fetch", side_effect=OSError("offline")) as fetch:
            self.assertEqual(len(api.precons_view()["decks"]), 3)
            (self.cache / "DeckList.json").unlink()
            self.assertApiError(502, api.precons_view, contains="couldn't be fetched")
        self.assertEqual(fetch.call_count, 1)       # not asked again for RETRY_AFTER

    def test_a_failed_fetch_is_tried_again_later(self):
        path = self.seed("DeckList.json", DECK_LIST, age=precons.TTL + 60)
        for error in (OSError("offline"), http.client.IncompleteRead(b"{")):
            with self.subTest(error=type(error).__name__):
                precons._failed.clear()
                with mock.patch.object(precons, "_fetch", side_effect=error) as fetch:
                    for _ in range(3):
                        self.assertEqual(len(api.precons_view()["decks"]), 3)     # the old copy
                self.assertEqual(fetch.call_count, 1)
        newer = json.dumps(dict(DECK_LIST, data=DECK_LIST["data"][:1])).encode()
        with mock.patch.object(precons.time, "monotonic", return_value=time.monotonic() + precons.RETRY_AFTER + 1), \
                mock.patch.object(precons, "_fetch", return_value=newer):
            self.assertEqual([d["file"] for d in api.precons_view()["decks"]], ["TestDinos_TST"])
        self.assertEqual(path.read_bytes(), newer)
        self.assertEqual(precons._failed, {})

    def test_a_fetch_that_cant_be_saved_is_still_used(self):
        self.seed("DeckList.json", DECK_LIST, age=precons.TTL + 60)
        newer = json.dumps(dict(DECK_LIST, data=DECK_LIST["data"][:1])).encode()
        with mock.patch.object(precons, "_fetch", return_value=newer), \
                mock.patch("pathlib.Path.replace", side_effect=PermissionError("in use")):
            self.assertEqual([d["file"] for d in api.precons_view()["decks"]], ["TestDinos_TST"])

    def test_the_lists_are_read_once_a_build(self):
        with mock.patch.object(precons, "_read_deck_list", wraps=precons._read_deck_list) as decks, \
                mock.patch.object(precons, "_read_set_names", wraps=precons._read_set_names) as sets:
            api.precons_view()
            api.precons_view("elf")
            api.precon_preview("ElfTheme_TST", "user3")
            self.assertEqual((decks.call_count, sets.call_count), (1, 1))
            self.seed("DeckList.json", dict(DECK_LIST, data=DECK_LIST["data"][:1]))      # a new build
            self.assertEqual(len(api.precons_view()["decks"]), 1)
            self.assertEqual((decks.call_count, sets.call_count), (2, 1))

    def test_the_set_list_has_its_own_size_cap(self):
        self.assertGreater(precons.MAX_SETS_BYTES, 11_711_332 * 4)    # SetList.json on 2026-10-10
        (self.cache / "SetList.json").unlink()
        with mock.patch.object(precons, "_fetch", return_value=json.dumps(SET_LIST).encode()) as fetch:
            api.precons_view()
        fetch.assert_called_once_with(precons.SETS_URL, precons.MAX_SETS_BYTES)

    def test_odd_boards_are_read_defensively(self):
        read = precons.cards_of({"mainBoard": [card("Sol Ring", "ECC", "57")], "planes": 1, "schemes": "x",
                                 "tokens": True, "displayCommander": {"name": "x"}})
        self.assertEqual((len(read["lines"]), read["display"], read["left_out"], read["tokens"], read["problems"]),
                         (1, [], {}, [], []))
        read = precons.cards_of({"mainBoard": [], "planes": [card("Some Plane", "OPCA", "1", 2), "x"],
                                 "tokens": [{"name": "Elf", "count": 2}, 3, {"name": "Elf", "count": True}]})
        self.assertEqual((read["left_out"], read["tokens"]), ({"plane": 2}, [{"name": "Elf", "count": 2}]))

    def test_bad_input(self):
        self.assertApiError(400, api.precons_view, "x" * 101)
        self.assertApiError(400, api.precon_preview, "../escape", "user2")
        self.assertApiError(404, api.precon_preview, "SomeDrop_SLD", "user2")     # not a paper deck
        self.assertApiError(404, api.precon_preview, "Finkel_WC00", "user2")      # gold-bordered
        self.assertApiError(404, api.precon_preview, "Nothing_TST", "user2")
        self.assertApiError(404, api.precon_preview, "TestDinos_TST", "nobody")


class PreviewTests(PreconTestCase):

    def test_a_line_naming_another_cards_printing_shows_the_cards_own_picture(self):
        # fdn 227 is Llanowar Elves: a Sol Ring line naming it (a shifted number in the list) mustn't show it.
        from decklab.lib.api import precons as api_precons
        lists = api_precons._lists_with_cards({"Deck": [{"name": "Sol Ring", "qty": 1, "set": "fdn", "number": "227"},
                                                    {"name": "Llanowar Elves", "qty": 1, "set": "fdn", "number": "227"}]})
        wrong, right = (line["card"] for line in lists["Deck"])
        self.assertEqual(wrong["name"], "Sol Ring")
        self.assertNotEqual(wrong["img_small"], "/img/fdn/227/small")
        self.assertEqual(right["img_small"], "/img/fdn/227/small")

    def test_a_commander_precon(self):
        view = api.precon_preview("TestDinos_TST", "user2")
        self.assertEqual((view["kind"], view["title"], view["exists"]), ("commander", "Ghalta: Test Dinos", None))
        # Each line carries its card (with that printing's picture) for the page; the rest is the list as saved.
        ghalta_card = view["lists"]["Commander"][0]["card"]
        self.assertEqual((ghalta_card["name"], ghalta_card["img_small"]), ("Ghalta, Primal Hunger", "/img/rix/130/small"))
        lists = {section: [{k: v for k, v in line.items() if k != "card"} for line in lines]
                 for section, lines in view["lists"].items()}
        self.assertEqual(lists, {
            "Commander": [{"name": "Ghalta, Primal Hunger", "qty": 1, "set": "rix", "number": "130",
                           "finish": "foil"}],
            "Deck": [{"name": "Llanowar Elves", "qty": 2, "set": "fdn", "number": "227", "finish": "nonfoil"},
                     {"name": "Elvish Mystic", "qty": 1, "set": "cmm", "number": "648", "finish": "nonfoil"},
                     {"name": "Sol Ring", "qty": 1, "set": "ecc", "number": "57", "finish": "nonfoil"},
                     {"name": "Forest", "qty": 20}]})
        self.assertEqual(view["counts"], {"Commander": 1, "Deck": 24})
        self.assertEqual(view["dropped_basics"], 20)
        self.assertEqual(view["left_out"], {"display commander": 1})
        self.assertEqual(view["tokens"], [{"name": "Dinosaur", "count": 4}])
        self.assertEqual((view["problems"], view["deck_problems"], view["ready"], view["editable"]),
                         ([], [], True, True))
        self.assertEqual(view["sha256"], self.rows("user2")["sha256"])
        ghalta = view["rows"][0]
        self.assertEqual({k: ghalta[k] for k in ("name", "set", "finish", "condition", "language", "notes")},
                         {"name": "Ghalta, Primal Hunger", "set": "rix", "finish": "foil", "condition": "",
                          "language": "", "notes": "Test Dinos precon (Test Commander)"})

    def test_a_casual_deck_with_a_sideboard(self):
        view = api.precon_preview("ElfTheme_TST", "user3")
        self.assertEqual((view["kind"], view["title"]), ("casual", "Elf Theme"))
        self.assertEqual(view["counts"], {"Deck": 8, "Sideboard": 2})
        self.assertEqual(view["adds"], {"rows": 3, "cards": 10})

    def test_cards_scryfall_lacks_are_problems(self):
        view = api.precon_preview("Unfinished_TST", "user2")
        self.assertFalse(view["ready"])
        messages = [p["message"] for p in view["problems"]]
        self.assertTrue(any("Sol Ring" in m and "can't be read" in m for m in messages), messages)
        self.assertTrue(any("Some New Card" in m for m in messages), messages)
        # A full-art basic is kept (the fixture's card data has no Forest to match it to), with its printing.
        self.assertEqual(view["dropped_basics"], 0)
        self.assertTrue(any("Forest" in m for m in messages), messages)
        self.assertIn({"name": "Forest", "qty": 10, "set": "fdn", "number": "281", "finish": "nonfoil", "card": None},
                      view["lists"]["Deck"])
        forest = next(r for r in view["rows"] if r["name"] == "Forest")
        self.assertEqual(forest["notes"], "Unfinished precon (Test Commander); full art")

    def test_a_display_commander_to_play_with_goes_into_the_collection(self):
        # Precons from 2022 to mid-2024: a foil-etched copy of the commander, a real card (here the fixture's RIX 130).
        etched = {"data": dict(DINOS["data"], name="Etched Dinos",
                               displayCommander=[card("Ghalta, Primal Hunger", "RIX", "130", foil=True)])}
        self.listed("EtchedDinos_TST", etched)
        view = api.precon_preview("EtchedDinos_TST", "user2")
        self.assertEqual(view["left_out"], {})
        self.assertEqual(view["counts"], {"Commander": 1, "Deck": 24})          # not in the deck
        self.assertEqual(view["adds"], {"rows": 4, "cards": 6})
        self.assertIn("Etched Dinos precon (Test Commander); display commander", [r["notes"] for r in view["rows"]])
        self.add("EtchedDinos_TST")
        rows = {(r["set"], r["collector_number"], r["finish"]): r for r in self.rows("user2")["rows"]}
        self.assertEqual(rows[("rix", "130", "foil")]["quantity"], "2")

    def test_a_list_a_deck_cant_have_isnt_ready(self):
        # Gold-bordered (memorabilia) printings match the collection's import rules, but no deck line may name them.
        gilded = {"data": {"name": "Gilded", "code": "TST", "type": "Theme Deck",
                           "mainBoard": [card("Llanowar Elves", "WC00", "nl239", 4)]}}
        self.listed("Gilded_TST", gilded, kind="Theme Deck")
        view = api.precon_preview("Gilded_TST", "user2")
        self.assertEqual(view["problems"], [])
        self.assertFalse(view["ready"])
        self.assertIn("memorabilia", view["deck_problems"][0]["message"])
        before = self.writes_made()
        error = self.assertApiError(400, self.add, "Gilded_TST", title="Gilded")
        self.assertIn("can't be made into a deck", error.message)
        self.assertEqual(error.extra["problems"], view["deck_problems"])
        self.assertEqual(self.writes_made(), before)

    def test_an_existing_title_is_named(self):
        self.add()
        self.assertEqual(api.precon_preview("TestDinos_TST", "user2")["exists"],
                         "user2/commander/ghalta-test-dinos")

    def test_editable_follows_the_visitor(self):
        with self.as_("user2"):
            self.assertTrue(api.precon_preview("TestDinos_TST", "user2")["editable"])
            # Another space's collection isn't his to see at all.
            self.assertApiError(403, api.precon_preview, "TestDinos_TST", "user3")
            self.assertApiError(403, api.precon_preview, "TestDinos_TST", "home")
        with self.as_("matt"):
            self.assertTrue(api.precon_preview("TestDinos_TST", "home")["editable"])
            # An admin's role opens no other space (E10-S29): User3's preview is the hidden
            # collection's 403, naming no one, as a missing space's is.
            error = self.assertApiError(403, api.precon_preview, "TestDinos_TST", "user3")
            self.assertEqual((error.message, error.extra), ("That collection isn't public.", {}))
            missing = self.assertApiError(403, api.precon_preview, "TestDinos_TST", "nobody")
            self.assertEqual(missing.message, error.message)
        with self.as_("user1"):        # home's collection is hers to add to (E10-S43)
            self.assertTrue(api.precon_preview("TestDinos_TST", "home")["editable"])

    def test_a_hidden_space_never_names_its_decks(self):
        # E10-S29: the admin sees neither User2's collection nor his decks, so the preview is
        # refused before any deck id there is probed, and an add there is refused before the name
        # is looked up (403 with only the error, not 409), with nothing saved.
        self.add()
        self.assertEqual(api.precon_preview("TestDinos_TST", "user2")["exists"],
                         "user2/commander/ghalta-test-dinos")        # a script sees it
        sha = self.rows("user2")["sha256"]                         # read as a script
        with self.as_("matt"):
            error = self.assertApiError(403, api.precon_preview, "TestDinos_TST", "user2")
            self.assertEqual(error.extra, {})
            before = self.writes_made()
            for file, title, given in (("TestDinos_TST", "Ghalta: Test Dinos", sha),
                                       ("ElfTheme_TST", "Fresh Elves", sha),
                                       ("ElfTheme_TST", "Fresh Elves", "0" * 64)):    # a stale sha256 too
                error = self.assertApiError(403, self.add, file, title=title, profile="matt", sha256=given)
                self.assertEqual((error.message, error.extra), ("That collection isn't public.", {}))
            self.assertEqual(self.writes_made(), before)
        with self.as_("user2"):
            self.assertEqual(api.precon_preview("TestDinos_TST", "user2")["exists"],
                             "user2/commander/ghalta-test-dinos")


class AddTests(PreconTestCase):

    def test_adds_the_cards_and_the_deck_in_one_change(self):
        with self.as_("user2"):
            answer = self.add(profile="user2")
        self.assertEqual(answer["collection"]["added"], {"rows": 3, "cards": 5})    # Llanowar Elves was a row
        self.assertNotIn("rows", answer["collection"])
        self.assertEqual(answer["deck"]["id"], "user2/commander/ghalta-test-dinos")
        # One change (precon.add): the cards and the new deck.
        self.assertEqual(self.last_write(), ("import 5 cards into User2's collection from the Test Dinos "
                                             "precon; new deck Ghalta: Test Dinos", "User2"))
        self.assertNotIn("commit", answer["collection"])
        rows = {(r["set"], r["collector_number"], r["finish"]): r for r in self.rows("user2")["rows"]}
        self.assertEqual(rows[("fdn", "227", "nonfoil")]["quantity"], "4")         # 2 owned + 2
        self.assertEqual(rows[("rix", "130", "foil")]["notes"], "Test Dinos precon (Test Commander)")
        self.assertNotIn(("fdn", "280", "nonfoil"), rows)
        raw = self.box.magic / "people" / "user2" / "imports" / "2026-10-10-tst-test-dinos.csv"
        self.assertTrue(raw.exists())
        text = (self.box.magic / "people" / "user2" / "decks" / "commander" / "ghalta-test-dinos.md").read_text(
            encoding="utf-8")
        self.assertIn("- **Status:** built", text)
        self.assertIn("- **Target bracket:** 2", text)
        self.assertNotIn("Played by", text)
        self.assertIn("Commander\n1 Ghalta, Primal Hunger (RIX) 130 *F*\n", text)
        self.assertIn("\n20 Forest\n", text)
        self.assertIn("1 Sol Ring (ECC) 57", text)
        self.assertIn("Added in Deck Lab on 2026-10-10 by User2 from the Test Dinos precon (Test Commander, "
                      "Commander Deck, released 2026-10-02). The list is MTGJSON's, from Wizards' published list: "
                      "https://magic.wizards.com/en/news/test.", text)
        self.assertIn("4 Dinosaur.", text)

    def test_the_table_counts_the_cards_the_precon_just_added(self):
        with self.as_("user2"):
            answer = self.add(profile="user2")
        text = (self.box.magic / "people" / "user2" / "decks" / "commander" / "ghalta-test-dinos.md").read_text(
            encoding="utf-8")
        # Worked out after the import, as the same change saves it: nothing it just added is missing.
        self.assertIn("| Ghalta, Primal Hunger | 1 | 1 | 0 |", text)
        self.assertIn("| Sol Ring | 1 | 1 | 0 |", text)
        self.assertIn("| Elvish Mystic | 1 | 1 | 0 |", text)
        self.assertIn("| **Total to buy** | | | **0** |", text)
        self.assertEqual(answer["deck"]["stale_tables"], [])

    def test_home_takes_its_player_and_fields(self):
        answer = self.add("ElfTheme_TST", "home", title="My Elves", fields={"archetype": "Elves"})
        text = (self.box.magic / "decks" / "casual" / "my-elves.md").read_text(encoding="utf-8")
        self.assertIn("- **Played by:** user", text)
        self.assertIn("- **Archetype:** Elves", text)
        self.assertIn("The list is MTGJSON's, from https://mtg.wiki/page/Elf_Theme.", text)   # not Wizards'
        self.assertIn("This deck is built: set Sleeves", " ".join(answer["deck"]["warnings"]))
        self.assertIn("Sideboard\n2 Pick Your Poison (MKM) 170", text)
        self.assertEqual(answer["deck"]["id"], "casual/my-elves")
        self.assertEqual(self.last_write(), ("import 10 cards into the home collection from the Elf Theme "
                                             "precon; new deck My Elves", "Matt"))

    def test_permissions(self):
        # Only a space's own people add to it: not User2 to User3's or home's, not Matt (an admin) to
        # User2's (E10-S29). The collection's sha256 is read as a script, so each refusal is the add's own.
        for profile, space in (("user2", "user3"), ("user2", "home"), ("matt", "user2")):
            sha = self.rows(space)["sha256"]
            with self.subTest(profile=profile, space=space), self.as_(profile):
                before = self.writes_made()
                error = self.assertApiError(403, self.add, space=space, profile=profile, title="X", sha256=sha)
                self.assertEqual(error.extra, {})
                self.assertEqual(self.writes_made(), before)

    def test_user1_adds_a_precon_to_home(self):
        # E10-S43: home's collection is User1's as Matt's; the deck she makes is played by her.
        sha = self.rows("home")["sha256"]
        with self.as_("user1"):
            answer = self.add("ElfTheme_TST", "home", profile="user1", title="Her Elves", sha256=sha)
        self.assertEqual(answer["deck"]["id"], "casual/her-elves")
        text = (self.box.magic / "decks" / "casual" / "her-elves.md").read_text(encoding="utf-8")
        self.assertIn("- **Played by:** wife", text)
        self.assertEqual(self.last_write(), ("import 10 cards into the home collection from the Elf Theme "
                                             "precon; new deck Her Elves", "User1"))

    def test_refusals_change_nothing(self):
        before = self.writes_made()
        self.assertApiError(409, self.add, sha256="0" * 64)
        error = self.assertApiError(400, self.add, "Unfinished_TST", title="Unfinished")
        self.assertTrue(error.extra["problems"])
        self.assertApiError(400, self.add, title="​")
        self.assertEqual(self.writes_made(), before)
        self.add()
        after = self.writes_made()
        error = self.assertApiError(409, self.add)                 # the title's file is taken
        self.assertEqual(error.extra["conflict"]["id"], "user2/commander/ghalta-test-dinos")
        self.assertEqual(self.writes_made(), after)

    def test_a_deck_refused_in_the_change_adds_no_cards(self):
        # The title is taken after add_precon checked it: precon.add refuses as a whole, so the cards
        # aren't added either (one change: no "cards in, deck not made" any more).
        self.add()
        before, rows = self.writes_made(), self.rows("user2")["rows"]
        with mock.patch.object(api.saving.decks, "existing_deck_id", return_value=None):
            error = self.assertApiError(409, self.add)
        self.assertEqual(error.extra["conflict"], {"reason": "exists", "id": "user2/commander/ghalta-test-dinos"})
        self.assertNotIn("collection", error.extra)
        self.assertEqual((self.writes_made(), self.rows("user2")["rows"]), (before, rows))

    def test_an_upload_name_taken_on_disk_is_a_409(self):
        # The files backend refuses to write over a file that's there (ValueError): nothing is saved,
        # and the page is told so (a 409), not that the save may have gone in (a 500).
        before = self.writes_made()
        with mock.patch.object(api.saving.inventory, "apply",
                               side_effect=ValueError("magic/people/user2/imports/x.csv already exists")):
            self.assertApiError(409, self.add, contains="already exists")
        self.assertEqual(self.writes_made(), before)

    def test_a_failure_after_the_change_leaves_both_saved(self):
        with mock.patch.object(api.saving, "_stale_after", side_effect=RuntimeError("tables")):
            with self.assertRaises(RuntimeError):
                self.add()
        made = self.box.magic / "people" / "user2" / "decks" / "commander" / "ghalta-test-dinos.md"
        self.assertTrue(made.exists())
        rows = {(r["set"], r["collector_number"], r["finish"]): r for r in self.rows("user2")["rows"]}
        self.assertIn(("rix", "130", "foil"), rows)
