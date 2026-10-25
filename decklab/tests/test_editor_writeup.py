"""The editor's write-up (the Notes tab: prose in GET /api/deck/edit, POST /api/deck/check and
/api/deck/save, and "Mark write-up as current") and its card finder (GET /api/deck/find).

Runs in test_editor's EditorTestCase (test_api's Sandbox with the files backend, today fixed at
2026-10-05), so a save's stored text is read back from the deck's file.
"""
import json

from decklab.lib import access, api, decks
from decklab.lib.api import drafts
from decklab.tests.test_api import _write
from decklab.tests.test_editor import MARKER, TODAY, EditorTestCase


class ProseTests(EditorTestCase):

    def test_the_edit_view_has_the_write_up(self):
        view = api.edit_view("casual/table-test")
        self.assertEqual(view["prose"], {"substitutes": "", "notes": "Keep this prose."})

    def test_saving_the_notes_changes_only_them(self):
        before = self.text("casual/table-test")
        answer = api.save_deck(self.body(id="casual/table-test", sha256=self.sha("casual/table-test"),
                                         prose={"notes": "### Plan\n\nAttack with elves.\n"}))
        self.assertEqual((answer["changed"], answer["marked"], answer["unmarked"]), (True, None, False))
        self.assertEqual(answer["table"]["rewritten"], False)        # the write-up alone doesn't touch the table
        text = self.text("casual/table-test")
        self.assertTrue(text.endswith("## Notes\n\n### Plan\n\nAttack with elves.\n"), text[-80:])
        self.assertEqual(text.split("## Notes")[0], before.split("## Notes")[0])
        self.assertEqual(answer["deck"]["prose"]["notes"], "### Plan\n\nAttack with elves.")
        # The same text again saves nothing.
        again = api.save_deck(self.body(id="casual/table-test", sha256=answer["sha256"],
                                        prose={"notes": "### Plan\n\nAttack with elves."}))
        self.assertEqual(again["changed"], False)

    def test_substitutes_keep_the_play_now_list(self):
        view = api.edit_view("casual/table-test")
        target = view["lists"]["target"]
        started = api.save_deck(self.body(id="casual/table-test", sha256=view["sha256"],
                                          lists={"target": target, "owned": target}))
        saved = api.save_deck(self.body(id="casual/table-test", sha256=started["sha256"],
                                        prose={"substitutes": "Swap the Lotus for a Forest."}))
        text = self.text("casual/table-test")
        self.assertIn("## Substitutes\n\nSwap the Lotus for a Forest.\n\n### Substitute version", text)
        deck = decks.parse_deck(text.encode("utf-8"), "table-test", "casual")
        self.assertEqual(api.edit_view("casual/table-test")["lists"]["owned"], started["deck"]["lists"]["owned"])
        self.assertTrue(deck.owned)
        self.assertEqual(saved["deck"]["prose"]["substitutes"], "Swap the Lotus for a Forest.")

    def test_mark_write_up_as_current(self):
        view = api.edit_view("casual/table-test")
        lists = self.edit_lists(view)
        lists["target"]["Deck"][0]["qty"] = 3
        marked = self.save("casual/table-test", lists)
        self.assertIn(MARKER, self.text("casual/table-test"))
        self.assertEqual(api.edit_view("casual/table-test")["changed_on"], TODAY)
        check = api.check_draft(self.body(id="casual/table-test", sha256=marked["sha256"], mark_current=True))
        self.assertEqual(check["changes"]["marker"], True)
        cleared = api.save_deck(self.body(id="casual/table-test", sha256=marked["sha256"], mark_current=True))
        self.assertEqual((cleared["changed"], cleared["unmarked"], cleared["marked"]), (True, True, None))
        text = self.text("casual/table-test")
        self.assertNotIn("Decklist changed", text)
        self.assertIn("- **Status:** building\n\nSome prose about the deck.", text)
        # A list change and the mark in one save: the line isn't added.
        lists["target"]["Deck"][0]["qty"] = 2
        both = api.save_deck(self.body(id="casual/table-test", sha256=cleared["sha256"], lists=lists,
                                       mark_current=True))
        self.assertEqual(both["marked"], None)
        self.assertNotIn("Decklist changed", self.text("casual/table-test"))
        self.assertIn("2 Llanowar Elves (FDN) 227\n", self.text("casual/table-test"))

    def test_the_check_reports_write_up_changes(self):
        sha = self.sha("casual/table-test")
        answer = api.check_draft(self.body(id="casual/table-test", sha256=sha,
                                           prose={"notes": "Keep this prose.", "substitutes": "New."}))
        self.assertEqual((answer["changes"]["prose"], answer["changes"]["marker"]), (["substitutes"], False))
        self.assertApiError(400, api.check_draft, self.body(kind="casual", prose={"notes": "x"}))

    def test_write_up_that_would_move_the_decks_parts_is_refused(self):
        sha = self.sha("casual/table-test")
        before = self.text("casual/table-test")
        for prose in ({"notes": "## Another section"}, {"notes": "# Title"}, {"notes": "### Decklist\n"},
                      {"substitutes": "### Substitute version (owned and incoming cards)"},
                      {"notes": "```\nDeck\n1 Forest"}, {"notes": 3}, {"other": "x"}, {"notes": "a\x00b"}):
            with self.subTest(prose=prose):
                self.assertApiError(400, api.save_deck, self.body(id="casual/table-test", sha256=sha, prose=prose))
        self.assertApiError(413, api.save_deck, self.body(id="casual/table-test", sha256=sha,
                                                          prose={"notes": "x" * (drafts.MAX_PROSE + 1)}))
        self.assertApiError(400, api.save_deck, self.body(id="casual/table-test", sha256=sha, mark_current="yes"))
        self.assertEqual(self.text("casual/table-test"), before)

    def test_a_deck_without_the_sections_gets_them(self):
        text = drafts.with_prose("# T\n- **Format:** x\n\n## Decklist\n\n```\nDeck\n1 Forest\n```\n",
                                 {"substitutes": "S", "notes": "N"})
        self.assertTrue(text.endswith("```\n\n## Substitutes\n\nS\n\n## Notes\n\nN\n"), text)
        self.assertEqual(drafts.prose_of(text), {"substitutes": "S", "notes": "N"})
        crlf = drafts.with_prose("# T\r\n\r\n## Notes\r\n\r\nOld\r\n", {"notes": "New\nlines"}, "\r\n")
        self.assertEqual(crlf, "# T\r\n\r\n## Notes\r\n\r\nNew\r\nlines\r\n")

    def test_someone_who_may_not_edit_the_deck_cant_save_its_write_up(self):
        self.assertApiError(403, api.save_deck, self.body("guest", id="casual/table-test",
                                                          sha256=self.sha("casual/table-test"),
                                                          prose={"notes": "Mine now."}))


class FindCardsTests(EditorTestCase):

    def test_search_puts_owned_cards_first_with_prices(self):
        answer = api.find_cards("elv", deck_id="casual/table-test")
        names = [c["name"] for c in answer["cards"]]
        self.assertIn("Llanowar Elves", names)
        owned = [bool(c["have"]["owned"] or c["have"]["on_the_way"]) for c in answer["cards"]]
        self.assertEqual(owned, sorted(owned, reverse=True))        # owned cards come first
        elves = next(c for c in answer["cards"] if c["name"] == "Llanowar Elves")
        self.assertGreater(elves["have"]["owned"], 0)
        self.assertIn("oracle_text", elves)
        self.assertIn("aud", elves)
        self.assertEqual(answer["rate"], 2.0)
        self.assertEqual(api.find_cards("", deck_id="casual/table-test")["cards"], [])

    def test_filters(self):
        creatures = api.find_cards("l", type="creature", limit="60")["cards"]
        self.assertTrue(creatures and all("Creature" in c["type_line"] for c in creatures))
        green = api.find_cards("l", colors="G", limit="60")["cards"]
        self.assertTrue(all(set(c["color_identity"]) <= {"G"} for c in green))
        one = api.find_cards("l", mv="1", limit="60")["cards"]
        self.assertTrue(all(c["cmc"] == 1 for c in one))
        for bad in ({"scope": "mine"}, {"colors": "X"}, {"colors": "GG"}, {"type": "goblin"}, {"mv": "8"},
                    {"limit": "0"}, {"limit": "61"}, {"page": "x"}, {"q": "a\x01"}):
            with self.subTest(bad=bad):
                self.assertApiError(400, lambda: api.find_cards(**{"q": "elf", **bad}))
        self.assertApiError(404, lambda: api.find_cards("elf", space="nobody"))

    def test_my_collection_lists_free_copies_in_the_decks_colours(self):
        answer = api.find_cards(scope="owned", deck_id="casual/table-test", colors="G", limit="60")
        free = {c["name"]: c["free"] for c in answer["cards"]}
        self.assertTrue(free)
        self.assertTrue(all(n > 0 for n in free.values()))
        self.assertNotIn("Forest", free)                          # basics are left out
        self.assertTrue(all(set(c["color_identity"]) <= {"G"} for c in answer["cards"]))
        paged = api.find_cards(scope="owned", deck_id="casual/table-test", limit="1", page="2")
        self.assertEqual((len(paged["cards"]), paged["page"]), (1, 2))
        self.assertEqual(paged["total"], api.find_cards(scope="owned", deck_id="casual/table-test")["total"])
        words = api.find_cards("llan elv", scope="owned", deck_id="casual/table-test")
        self.assertEqual([c["name"] for c in words["cards"]], ["Llanowar Elves"])


class FindCardsPrivacyTests(EditorTestCase):
    """A visitor sees "My collection" and owned counts only for a space whose inventory they may see."""

    def setUp(self):
        super().setUp()
        _write(self.box.root / "config.json", json.dumps({"profiles": [
            {"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin"},
            {"id": "user2", "name": "User2", "role": "member", "space": "user2"}]}))
        _write(self.box.magic / "people" / "user2" / "collection.csv",
               "name,set,collector_number,finish,quantity,condition,language,notes\n"
               "Llanowar Elves,fdn,227,nonfoil,1,NM,en,\n")

    def test_a_person_cant_browse_or_count_home(self):
        with access.using({"profile": "user2", "email": "", "remote": True}):
            self.assertApiError(403, lambda: api.find_cards(scope="owned", deck_id="casual/table-test"))
            answer = api.find_cards("llanowar", deck_id="casual/table-test")
            self.assertTrue(answer["cards"])
            self.assertTrue(all(c["have"] == {"owned": 0, "on_the_way": 0} for c in answer["cards"]))
            own = api.find_cards(scope="owned", space="user2")
            self.assertEqual([(c["name"], c["free"]) for c in own["cards"]], [("Llanowar Elves", 1)])


class WriteUpCheckTests(EditorTestCase):
    """The check reports what a save of the write-up would refuse, as blocks, before Save is pressed."""

    def test_a_heading_is_a_block_in_the_check(self):
        sha = self.sha("casual/table-test")
        answer = api.check_draft(self.body(id="casual/table-test", sha256=sha, prose={"notes": "## Another section"}))
        self.assertFalse(answer["ok"])
        self.assertEqual([b["field"] for b in answer["blocks"]], ["prose"])
        self.assertNotIn("prose", answer["changes"]["fields"])
        fine = api.check_draft(self.body(id="casual/table-test", sha256=sha, prose={"notes": "### Plan\n\nGo."}))
        self.assertTrue(fine["ok"])

    def test_headings_inside_a_fenced_block_are_text(self):
        sha = self.sha("casual/table-test")
        notes = "### Example\n\n```\n## not a heading\n# nor this\n```\n"
        self.assertTrue(api.check_draft(self.body(id="casual/table-test", sha256=sha, prose={"notes": notes}))["ok"])
        saved = api.save_deck(self.body(id="casual/table-test", sha256=sha, prose={"notes": notes}))
        self.assertEqual(saved["deck"]["prose"]["notes"], notes.strip("\n"))
        self.assertEqual(drafts._prose_problem(["```", "## x"]), "A ``` block in the write-up is never closed")


class FindCardsRankingTests(EditorTestCase):

    def test_the_name_typed_comes_first_with_no_did_you_mean(self):
        answer = api.find_cards("llanowar elves", deck_id="casual/table-test")
        self.assertEqual(answer["cards"][0]["name"], "Llanowar Elves")
        self.assertEqual(answer["did_you_mean"], [])

    def test_whole_words_rank_before_parts_of_words(self):
        from decklab.lib.api import editor
        self.assertEqual(editor._name_rank("Lightning Bolt", "bolt"), 1)
        self.assertEqual(editor._name_rank("Boltwing Marauder", "bolt"), 2)
        self.assertEqual(editor._name_rank("Lightning Bolt", "lightning bolt"), 0)

    def test_filters_alone_browse_every_card(self):
        creatures = api.find_cards(type="creature", limit="60")
        self.assertTrue(creatures["cards"])
        self.assertTrue(all("Creature" in c["type_line"] for c in creatures["cards"]))
        self.assertEqual(creatures["total"], len(creatures["cards"]) if creatures["pages"] == 1 else creatures["total"])
        green = api.find_cards(colors="G", mv="1", limit="60")["cards"]
        self.assertTrue(all(set(c["color_identity"]) <= {"G"} and c["cmc"] == 1 for c in green))
