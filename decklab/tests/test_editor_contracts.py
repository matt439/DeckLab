"""Editor contracts tests; shared fixtures remain in test_editor."""
import unittest
import json
from unittest import mock
from decklab.lib import api, cards, pool
from decklab.tests.test_api import _write
from decklab.tests.test_editor import (
    EditorTestCase, TABLE_DECK, lines,
)
from decklab.tests.test_web import NODE, _run_page


class ReviewFixTests(EditorTestCase):
    """The save side's review findings of 2026-09-30 (each test names its finding)."""

    def test_an_empty_target_list_needs_confirming(self):             # finding 4
        before = self.path("casual/table-test").read_bytes()
        for lists in ({"target": {}}, {"target": {"Deck": [], "Sideboard": []}}):
            with self.subTest(lists=lists):
                error = self.assertApiError(400, api.save_deck, self.body(
                    id="casual/table-test", sha256=self.sha("casual/table-test"), lists=lists),
                    contains="The planned list is empty")
                block = error.extra["blocks"][0]
                self.assertEqual((block["list"], block["confirm"]), ("target", "confirm_empty"))
        self.assertEqual(self.path("casual/table-test").read_bytes(), before)
        check = api.check_draft(self.body(id="casual/table-test", lists={"target": {}}))
        self.assertEqual([b.get("confirm") for b in check["blocks"]], ["confirm_empty"])
        self.assertApiError(400, api.save_deck, self.body(id="casual/table-test", sha256=self.sha("casual/table-test"),
                                                          lists={"target": {}}, confirm_empty="yes"))
        answer = api.save_deck(self.body(id="casual/table-test", sha256=self.sha("casual/table-test"),
                                         lists={"target": {}}, confirm_empty=True))
        self.assertEqual(answer["changed"], True)
        self.assertTrue(any("The planned list is empty" in w for w in answer["warnings"]))
        self.assertIn("## Decklist\n\n```\n```\n", self.text("casual/table-test"))
        # A deck that's empty already needs no confirming, and a blocked line isn't "empty".
        again = self.save("casual/table-test", {"target": {}})
        self.assertEqual(again["changed"], False)
        error = self.assertApiError(400, api.save_deck, self.body(
            id="casual/gruul-test", sha256=self.sha("casual/gruul-test"),
            lists={"target": {"Deck": [{"qty": 1, "name": "Llanowar Elfs"}]}}))
        self.assertEqual([b.get("confirm") for b in error.extra["blocks"]], [None])

    def add_second_table(self):
        _write(self.path("casual/table-two"), TABLE_DECK.replace("# Table Test", "# Table Two"))
        stale = api.stale_view()["stale"]
        self.assertEqual([s["id"] for s in stale], ["casual/table-test", "casual/table-two"])
        return [{"id": s["id"], "sha256": s["sha256"]} for s in stale]

    def test_a_table_that_cant_be_saved_saves_none(self):  # finding 17
        # One change saves every table, so a refusal leaves them all as they were.
        wanted = self.add_second_table()
        before = {d["id"]: self.path(d["id"]).read_bytes() for d in wanted}
        inventory = api.saving.inventory
        for error, status in ((inventory.Conflict("Another inventory operation is under way"), 409),
                              (inventory.Unavailable("down"), 503), (inventory.Invalid("no"), 400)):
            with self.subTest(error=type(error).__name__):
                with mock.patch.object(inventory, "apply", side_effect=error):
                    self.assertApiError(status, api.update_tables, self.body(decks=wanted))
                self.assertEqual({d["id"]: self.path(d["id"]).read_bytes() for d in wanted}, before)
                self.assertEqual(len(api.stale_view()["stale"]), 2)

    def test_suggestions_are_capped_and_the_draft_is_read_outside_the_lock(self):    # finding 12
        names = [{"qty": 1, "name": f"Llanowar Elfz {n}"} for n in range(30)]
        with mock.patch.object(cards, "close_names", wraps=cards.close_names) as close:
            answer = api.check_draft(self.body(kind="casual", lists={"target": {"Deck": names}}))
        self.assertEqual((len(answer["blocks"]), close.call_count), (30, api.MAX_SUGGESTED))
        self.assertEqual(answer["blocks"][-1]["suggestions"], [])
        real = api.drafts._read_draft

        def read_draft(*args, **kwargs):
            self.assertFalse(api._save_lock.locked())
            return real(*args, **kwargs)
        with mock.patch.object(api.drafts, "_read_draft", side_effect=read_draft) as spy:
            self.save("casual/table-test", fields={"status": "built"})
        self.assertEqual(spy.call_count, 1)

    def test_a_deck_that_never_existed_is_404(self):                    # finding 15
        self.assertApiError(404, api.save_deck, self.body(id="casual/aux-1", sha256="0" * 64),
                            contains="No deck 'casual/aux-1'")
        error = self.assertApiError(404, api.update_tables, self.body(decks=[{"id": "casual/aux-1",
                                                                              "sha256": "0" * 64}]))
        self.assertIn("aux-1", error.message)

    def test_a_new_commander_decks_check_uses_the_default_bracket(self):   # finding 25
        lists = {"target": {"Commander": [{"qty": 1, "name": "Ghalta, Primal Hunger"}],
                            "Deck": [{"qty": 1, "name": "Sol Ring"}]}}
        check = api.check_draft(self.body(kind="commander", lists=lists))
        self.assertEqual(check["bracket"]["target"], 2)
        chosen = api.check_draft(self.body(kind="commander", lists=lists, fields={"target_bracket": 4}))
        self.assertEqual(chosen["bracket"]["target"], 4)
        created = api.create_deck(self.body(title="Ghalta Check", kind="commander", lists=lists))
        self.assertEqual(created["bracket"], check["bracket"])
        self.assertEqual(created["warnings"], check["warnings"])

    def test_an_empty_commander_section_is_dropped(self):               # finding 26
        answer = api.check_draft(self.body(kind="casual", lists={"target": {
            "Commander": [], "Deck": [{"qty": 20, "name": "Forest"}]}}))
        self.assertEqual((answer["ok"], answer["blocks"]), (True, []))
        self.assertEqual(list(answer["lists"]["target"]), ["Deck"])

    def test_the_warnings_are_the_pools_after_the_save(self):           # finding 29
        self.save("casual/gruul-test", fields={"status": "built"})
        answer = self.save("casual/gruul-test", fields={"built_version": "target"})
        self.assertIn("- **Built version:** target\n", self.text("casual/gruul-test"))
        self.assertFalse([w for w in answer["warnings"] if "has no 'Built version'" in w], answer["warnings"])

    def test_the_default_printing_is_non_foil_even_without_a_price(self):    # finding 30
        real_card, real_printing = cards.card, cards.printing
        fake = {"purl": {"2026-2": {"finishes": ["foil"], "usd": None, "usd_foil": 13.66, "set_type": "promo",
                                    "released_at": "2026-01-01"}},
                "trc": {"198": {"finishes": ["nonfoil"], "usd": None, "usd_foil": None, "set_type": "expansion",
                                "released_at": "2021-01-01"}}}

        def printing(set_code, number):
            p = fake.get(set_code, {}).get(number)
            if p is None:
                return real_printing(set_code, number)
            return dict(p, set=set_code, collector_number=number, digital=False, games=["paper"], oversized=False,
                        name="Kirk Test", usd_etched=None)

        def card(name):
            return {"name": "Kirk Test", "printings": [("purl", "2026-2"), ("trc", "198")]} if name == "Kirk Test" \
                else real_card(name)
        with mock.patch.object(cards, "card", side_effect=card), \
                mock.patch.object(cards, "printing", side_effect=printing), \
                mock.patch.object(cards, "cheapest_usd", return_value=(13.66, "purl", "2026-2", "foil")):
            chosen = api._default_printing("Kirk Test", {})
        self.assertEqual(chosen, {"set": "trc", "number": "198", "finish": "nonfoil", "why": "newest"})
        self.assertEqual(api._default_printing("Llanowar Elves", {})["finish"], "nonfoil")

    def test_printings_that_arent_paper_cards_are_refused(self):         # finding 31
        view = api.edit_view("casual/table-test")
        lists = self.edit_lists(view)
        lists["target"]["Deck"] += [{"qty": 1, "name": "Llanowar Elves", "set": "pana", "number": "4"},
                                    {"qty": 1, "name": "Llanowar Elves", "set": "wc00"},
                                    {"qty": 1, "name": "Black Lotus", "set": "ced", "number": "233"}]
        answer = api.check_draft(self.body(id="casual/table-test", lists=lists))
        self.assertEqual([b["index"] for b in answer["blocks"]], [4, 5, 6])
        self.assertIn("Llanowar Elves (PANA) 4 is an online-only printing", answer["blocks"][0]["problem"])
        self.assertIn("Llanowar Elves's WC00 printing is a collectors' or memorabilia printing",
                      answer["blocks"][1]["problem"])
        pasted = api.parse_list(self.body(text="1 Llanowar Elves (PANA) 4\n1 Llanowar Elves (WC00)\n"))
        self.assertEqual(lines(pasted["sections"]), [(2, "Llanowar Elves", "fdn", "227", "nonfoil")])
        self.assertIn("Llanowar Elves (PANA) 4 is an online-only printing; using FDN 227 instead",
                      pasted["warnings"])

    def test_digital_only_names_cannot_be_pasted_or_saved_without_a_set(self):
        # This frozen index intentionally has only the digital printing of this name.
        name = "Oracle of the Alpha"
        for printed in (name, f"{name} (YDMU) 4"):
            with self.subTest(printed=printed):
                pasted = api.parse_list(self.body(text=f"Deck\n4 {printed}\n56 Forest"))
                self.assertEqual(pasted["unknown"], [])
                self.assertEqual(len(pasted["errors"]), 1)
                self.assertEqual(pasted["errors"][0]["line"], 2)
                self.assertIn("no playable paper printing", pasted["errors"][0]["error"])
                self.assertEqual([line["name"] for line in pasted["sections"]["Deck"]], ["Forest"])
        lists = {"target": {"Deck": [{"qty": 4, "name": name}, {"qty": 56, "name": "Forest"}]}}
        checked = api.check_draft(self.body(kind="casual", lists=lists))
        self.assertFalse(checked["ok"])
        self.assertIn("no playable paper printing", checked["blocks"][0]["problem"])
        before = self.path("casual/table-test").read_bytes()
        self.assertApiError(400, api.save_deck, self.body(id="casual/table-test",
                            sha256=self.sha("casual/table-test"), lists=lists),
                            contains="no playable paper printing")
        self.assertApiError(400, api.create_deck, self.body(kind="casual", title="Digital deck", lists=lists),
                            contains="no playable paper printing")
        self.assertEqual(self.path("casual/table-test").read_bytes(), before)
        self.assertFalse(self.path("casual/digital-deck").exists())

    def test_missing_default_printing_does_not_reject_a_paper_card(self):
        # A paper card without a price or usable image can have no default printing.
        with mock.patch.object(api.drafts, "_default_printing", return_value=None), \
                mock.patch.object(api.editor, "_default_printing", return_value=None):
            pasted = api.parse_list(self.body(text="Deck\n4 Llanowar Elves\n56 Forest"))
            self.assertEqual(pasted["errors"], [])
            checked = api.check_draft(self.body(kind="casual", lists={"target": pasted["sections"]}))
        self.assertTrue(checked["ok"])

    def test_existing_digital_only_lines_are_preserved(self):
        path = self.path("casual/table-test")
        _write(path, self.text("casual/table-test").replace("20 Forest", "1 Oracle of the Alpha\n20 Forest"))
        view = api.edit_view("casual/table-test")
        checked = api.check_draft(self.body(id=view["id"], lists=self.edit_lists(view)))
        self.assertTrue(checked["ok"])
        self.assertIn("Oracle of the Alpha", [line["name"] for line in checked["lists"]["target"]["Deck"]])

    def test_taking_a_built_deck_apart_removes_its_built_version(self):  # finding 32
        self.save("casual/gruul-test", fields={"status": "built", "built_version": "owned"})
        self.assertIn("- **Built version:** owned-only\n", self.text("casual/gruul-test"))
        view = api.edit_view("casual/gruul-test")
        answer = self.save("casual/gruul-test", fields=view["fields"] | {"status": "building"})
        self.assertNotIn("Built version", self.text("casual/gruul-test"))
        self.assertIn("- **Status:** building\n", self.text("casual/gruul-test"))
        self.assertEqual(answer["deck"]["fields"]["built_version"], None)
        # A Built version left on a deck that isn't built is offered, so it can be removed.
        _write(self.path("casual/gruul-test"), self.text("casual/gruul-test").replace(
            "- **Status:** building\n", "- **Status:** building\n- **Built version:** target\n"))
        self.assertIn("built_version", api.edit_view("casual/gruul-test")["editable_fields"])



class CoreFixThroughTheApiTests(EditorTestCase):
    """The core modules' review fixes (decks), seen through the API."""

    def test_a_crlf_deck_saved_unchanged_changes_nothing(self):      # findings 2 and 8
        path = self.path("casual/table-test")
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        before = path.read_bytes()
        answer = self.save("casual/table-test")
        self.assertEqual(answer["changed"], False)
        self.assertEqual(path.read_bytes(), before)

    def test_a_rate_worded_another_way_isnt_repriced(self):             # findings 0 and 28
        path = self.path("casual/table-test")
        _write(path, TABLE_DECK.replace("converted at 1 USD = 1.5 AUD (ECB rate of 2026-09-20), pulled 2026-09-21",
                                        "converted at USD 1 = AUD 1.4224 (ECB, 2026-09-25), pulled 2026-09-28"))
        answer = self.save("casual/table-test", fields={"status": "built"})
        self.assertEqual(answer["table"]["repriced"], False)
        note = answer["table"]["note"]
        self.assertIn('starts "Prices are estimates, converted at USD 1 = AUD 1.4224 (ECB..."', note)
        self.assertIn('("converted at USD 1 = AUD 1.4224")', note)
        self.assertIn('reword that rate exactly as "1 USD = 2.0 AUD (ECB rate of 2026-09-28), pulled 2026-09-28"', note)
        self.assertEqual(self.text("casual/table-test").split("## Owned vs needed")[1].count("converted at"), 1)

    def test_a_second_rate_beside_the_stamp_is_named_in_the_note(self):
        path = self.path("casual/table-test")
        _write(path, TABLE_DECK.replace("pulled 2026-09-21", "pulled 2026-09-21; it was 1.41 AUD per USD last week"))
        answer = self.save("casual/table-test", fields={"status": "built"})
        self.assertEqual(answer["table"]["repriced"], False)
        self.assertIn("take the other rate out of that paragraph, leaving only "
                      '"1 USD = 1.5 AUD (ECB rate of 2026-09-20), pulled 2026-09-21"', answer["table"]["note"])

    def test_titles_and_archetypes_lose_invisible_characters(self):     # finding 14
        api.create_deck(self.body(title="Ajani's Pride", kind="casual"))
        error = self.assertApiError(409, api.create_deck, self.body(title="Ajani\u2019s Pride", kind="casual"))
        self.assertEqual(error.extra["conflict"], {"reason": "exists", "id": "casual/ajanis-pride"})
        evil = api.create_deck(self.body(title="Evil\u202eslived", kind="casual",
                                         fields={"archetype": "Zero\u200bwidth  ramp"}))
        self.assertEqual((evil["id"], evil["title"]), ("casual/evilslived", "Evilslived"))
        self.assertIn("- **Archetype:** Zerowidth ramp\n", self.text("casual/evilslived"))
        zero = api.create_deck(self.body(title="Zero\u200bWidth", kind="casual"))
        self.assertEqual((zero["id"], zero["title"]), ("casual/zerowidth", "ZeroWidth"))
        self.assertApiError(400, api.create_deck, self.body(title="\u200b\u200b", kind="casual"))
        # An archetype echoed back as the file has it is no change.
        self.save("casual/table-test", fields={"archetype": "Elves  and\u200b friends"})
        self.assertIn("- **Archetype:** Elves and friends\n", self.text("casual/table-test"))
        view = api.edit_view("casual/table-test")
        self.assertEqual(self.save("casual/table-test", fields=view["fields"])["changed"], False)



class ContractAdditionTests(EditorTestCase):
    """The final round's contract additions (B, C, D; A is in test_api's
    SearchTests) and fixes: each test names its item."""

    # ---- item 6: one Built version warning

    def test_a_built_deck_without_a_built_version_is_warned_about_once(self):
        answer = self.save("casual/gruul-test", fields={"status": "built"})
        about = [w for w in answer["warnings"] if "Built version" in w]
        self.assertEqual(about, ["This deck is built and has both lists: set Built version to say which one is put "
                                 "together (until then its play-now list counts as in use)"])
        check = api.check_draft(self.body(id="casual/gruul-test"))
        self.assertEqual([w for w in check["warnings"] if "Built version" in w], about)
        # Setting it: the pool's warning about the file as it is now isn't repeated either.
        check = api.check_draft(self.body(id="casual/gruul-test", fields={"built_version": "target"}))
        self.assertEqual([w for w in check["warnings"] if "Built version" in w], [])
        # Another deck's missing Built version is still the pool's to report (naming the deck by id).
        self.assertIn("casual/gruul-test is built but has no 'Built version' field",
                      " ".join(api.check_draft(self.body(id="casual/table-test"))["warnings"]))

    # ---- item 8, contract D: the check of a deck file that's gone

    def test_a_check_of_a_deleted_deck_answers_as_a_save_does(self):
        # The files backend keeps no revisions, so a deck that's gone is 404 for both (the database's
        # 409 "deleted" is in test_deck_saving_db.py).
        view = api.edit_view("casual/table-test")
        body = self.body(id="casual/table-test", sha256=view["sha256"], lists=self.edit_lists(view))
        self.path("casual/table-test").unlink()
        checked = self.assertApiError(404, api.check_draft, body)
        saved = self.assertApiError(404, api.save_deck, self.body(id="casual/table-test", sha256=view["sha256"]))
        self.assertEqual(checked.message, saved.message)
        self.assertApiError(404, api.check_draft, self.body(id="casual/never-was"), contains="No deck")

    def test_changes_are_reported_even_with_blocks(self):
        view = api.edit_view("casual/table-test")
        lists = self.edit_lists(view)
        emptied = api.check_draft(self.body(id="casual/table-test", lists={"target": {}}))
        self.assertEqual(([b.get("confirm") for b in emptied["blocks"]], emptied["changes"]),
                         (["confirm_empty"], {"decklist": True, "fields": [], "prose": [], "marker": False}))
        lists["target"]["Deck"].append({"qty": 1, "name": "Llanowar Elfs"})
        unknown = api.check_draft(self.body(id="casual/table-test", lists=lists, fields={"archetype": "Elves"}))
        self.assertEqual((len(unknown["blocks"]), unknown["changes"]), (1, {"decklist": True, "fields": ["archetype"], "prose": [], "marker": False}))
        field = api.check_draft(self.body(id="casual/table-test", fields={"status": "done", "player": "wife"}))
        self.assertEqual(field["changes"], {"decklist": False, "fields": ["status"], "prose": [], "marker": False})
        new = api.check_draft(self.body(kind="casual", lists={"target": {"Deck": [{"qty": 1, "name": "Nonsense"}]}}))
        self.assertTrue(new["changes"]["decklist"])
        view = api.edit_view("casual/table-test")          # (the lists above changed the old view's)
        unchanged = api.check_draft(self.body(id="casual/table-test", lists=self.edit_lists(view)))
        self.assertEqual(unchanged["changes"], {"decklist": False, "fields": [], "prose": [], "marker": False})

    # ---- item 10, contract B: the cards each warning is about

    def test_each_warning_names_its_cards(self):
        view = api.edit_view("casual/gruul-test")
        lists = self.edit_lists(view)
        lists["target"]["Deck"].append({"qty": 2, "name": "llanowar elves"})
        lists["owned"]["Deck"].append({"qty": 1, "name": "Llanowar Elves", "set": "fdn", "number": "227"})
        answer = api.check_draft(self.body(id="casual/gruul-test", lists=lists))
        about = dict(zip(answer["warnings"], answer["warning_cards"]))
        self.assertEqual(len(answer["warnings"]), len(answer["warning_cards"]))
        self.assertEqual(about["8 copies of Llanowar Elves; a deck can have at most 4."], ["Llanowar Elves"])
        self.assertEqual(about["Play-now list: 5 copies of Llanowar Elves; a deck can have at most 4."],
                         ["Llanowar Elves"])
        self.assertEqual(about["25 cards; a casual deck has at least 60."], [])
        self.assertEqual(about["'Opt' isn't a card name in the card data; it was already in the file, so it's kept "
                               "as written"], ["Opt"])
        saved = self.save("casual/gruul-test", lists)
        saved_about = dict(zip(saved["warnings"], saved["warning_cards"]))
        self.assertEqual(len(saved["warnings"]), len(saved["warning_cards"]))
        for warning, names in about.items():
            if names:
                self.assertEqual(saved_about[warning], names)
        # Commander: the colours in words, and the cards behind the bracket.
        view = api.edit_view("commander/elf-commander")
        lists = self.edit_lists(view)
        lists["target"]["Deck"] += [{"qty": 1, "name": "Rhystic Study"}, {"qty": 1, "name": "Fire // Ice"}]
        answer = api.check_draft(self.body(id="commander/elf-commander", lists=lists))
        about = dict(zip(answer["warnings"], answer["warning_cards"]))
        self.assertEqual(about["2 cards outside the commander's colour identity (green): Fire // Ice, Rhystic Study."],
                         ["Fire // Ice", "Rhystic Study"])
        bracket = [w for w in answer["warnings"] if w.startswith("The list needs at least Bracket 3")]
        self.assertEqual([about[w] for w in bracket], [["Rhystic Study"]])
        created = api.create_deck(self.body(title="Study Hall", kind="commander", lists={"target": lists["target"]}))
        self.assertEqual(dict(zip(created["warnings"], created["warning_cards"]))[bracket[0]], ["Rhystic Study"])


class SleevesTests(EditorTestCase):
    """The Sleeves header field: a built deck's sleeve colour, edited like Built version."""

    NO_SLEEVES = "This deck is built: set Sleeves to the colour of its sleeves"

    def sleeve_warnings(self, answer):
        return [w for w in answer["warnings"] if "Sleeves" in w or "sleeves too" in w]

    def test_set_change_and_remove(self):
        self.assertNotIn("sleeves", api.edit_view("casual/gruul-test")["editable_fields"])
        answer = self.save("casual/gruul-test", fields={"status": "built", "built_version": "target",
                                                        "sleeves": "  Dragon  Shield red "})
        self.assertIn("- **Status:** built\n- **Built version:** target\n- **Sleeves:** Dragon Shield red\n\n",
                      self.text("casual/gruul-test"))
        self.assertEqual(answer["deck"]["fields"]["sleeves"], "Dragon Shield red")
        self.assertIn("sleeves", answer["deck"]["editable_fields"])
        self.assertEqual(self.sleeve_warnings(answer), [])
        # The file's own value echoed back (spaces aside) is no change.
        for same in ("Dragon Shield red", " Dragon Shield red "):
            check = api.check_draft(self.body(id="casual/gruul-test", fields={"sleeves": same}))
            self.assertEqual((check["ok"], check["changes"]["fields"]), (True, []))
        self.save("casual/gruul-test", fields={"sleeves": "Blue"})
        self.assertIn("- **Sleeves:** Blue\n", self.text("casual/gruul-test"))
        answer = self.save("casual/gruul-test", fields={"sleeves": None})
        self.assertNotIn("Sleeves", self.text("casual/gruul-test"))
        self.assertTrue(any(w.startswith(self.NO_SLEEVES) for w in answer["warnings"]), answer["warnings"])

    def test_a_bad_colour_blocks_the_save(self):
        self.save("casual/gruul-test", fields={"status": "built"})
        before = self.text("casual/gruul-test")
        for bad in ("x" * 41, "Red\nBlue", "Red\x07", "", "   ", 7, ["Red"]):
            with self.subTest(bad=bad):
                error = self.assertApiError(400, api.save_deck, self.body(
                    id="casual/gruul-test", sha256=self.sha("casual/gruul-test"), fields={"sleeves": bad}))
                self.assertEqual(error.extra["blocks"][0]["field"], "sleeves")
        self.assertEqual(self.text("casual/gruul-test"), before)
        self.assertTrue(api.check_draft(self.body(id="casual/gruul-test", fields={"sleeves": "x" * 40}))["ok"])
        # A blank Sleeves line written by hand: a blank value echoed back is still no colour, so it blocks.
        _write(self.path("casual/gruul-test"), before.replace("- **Status:** built\n",
                                                              "- **Status:** built\n- **Sleeves:**\n"))
        for blank in ("", "  "):
            with self.subTest(blank=blank):
                check = api.check_draft(self.body(id="casual/gruul-test", fields={"sleeves": blank}))
                self.assertEqual([b["field"] for b in check["blocks"]], ["sleeves"])
                error = self.assertApiError(400, api.save_deck, self.body(
                    id="casual/gruul-test", sha256=self.sha("casual/gruul-test"), fields={"sleeves": blank}))
                self.assertEqual(error.extra["blocks"][0]["field"], "sleeves")
        _write(self.path("casual/gruul-test"), before)
        # Only a built deck has sleeves.
        check = api.check_draft(self.body(id="casual/table-test", fields={"sleeves": "Red"}))
        self.assertEqual([b["field"] for b in check["blocks"]], ["sleeves"])
        # Other unknown fields are still refused.
        self.assertApiError(400, api.check_draft, self.body(id="casual/gruul-test", fields={"colour": "Red"}))

    def test_taking_a_built_deck_apart_removes_its_sleeves(self):
        self.save("casual/gruul-test", fields={"status": "built", "built_version": "owned", "sleeves": "Green"})
        view = api.edit_view("casual/gruul-test")
        answer = self.save("casual/gruul-test", fields=view["fields"] | {"status": "idea"})
        text = self.text("casual/gruul-test")
        self.assertNotIn("Sleeves", text)
        self.assertNotIn("Built version", text)
        self.assertEqual(answer["deck"]["fields"]["sleeves"], None)
        self.assertNotIn("sleeves", answer["deck"]["editable_fields"])
        # A Sleeves line left on a deck that isn't built is offered, so it can be removed; kept, it stays.
        _write(self.path("casual/gruul-test"), text.replace("- **Status:** idea\n",
                                                            "- **Status:** idea\n- **Sleeves:** Green\n"))
        view = api.edit_view("casual/gruul-test")
        self.assertIn("sleeves", view["editable_fields"])
        check = api.check_draft(self.body(id="casual/gruul-test", fields={"sleeves": "Green"}))
        self.assertEqual((check["ok"], check["changes"]["fields"]), (True, []))
        self.assertEqual(api.check_draft(self.body(id="casual/gruul-test", fields={"sleeves": "Red"}))["blocks"][0]
                         ["field"], "sleeves")
        self.save("casual/gruul-test", fields={"sleeves": None})
        self.assertNotIn("Sleeves", self.text("casual/gruul-test"))

    def test_warnings_for_no_colour_and_a_colour_another_built_deck_has(self):
        answer = self.save("casual/table-test", fields={"status": "built"})
        self.assertTrue(any(w.startswith(self.NO_SLEEVES) for w in answer["warnings"]), answer["warnings"])
        self.assertTrue(any(w.startswith(self.NO_SLEEVES) for w in api.check_draft(
            self.body(id="casual/table-test"))["warnings"]))
        self.save("casual/table-test", fields={"sleeves": "Matte  Red"}, profile="user1")    # her deck: hers to choose
        self.assertEqual(api.edit_view("casual/gruul-test")["other_sleeves"],
                         [{"id": "casual/table-test", "title": "Table Test", "sleeves": "Matte Red"}])
        self.assertEqual(api.edit_view("casual/table-test")["other_sleeves"], [])
        # A colour another built deck has is fine (E8-S20): no warning.
        check = api.check_draft(self.body(id="casual/gruul-test", fields={"status": "built", "sleeves": " matte RED "}))
        self.assertTrue(check["ok"])
        self.assertEqual(self.sleeve_warnings(check), [])
        check = api.check_draft(self.body(id="casual/gruul-test", fields={"status": "built", "sleeves": "Blue"}))
        self.assertEqual(self.sleeve_warnings(check), [])
        # A deck that isn't built doesn't count.
        self.save("casual/table-test", fields={"status": "building"})
        check = api.check_draft(self.body(id="casual/gruul-test", fields={"status": "built", "sleeves": "Matte Red"}))
        self.assertEqual(self.sleeve_warnings(check), [])

    def test_a_new_deck(self):
        answer = api.create_deck(self.body(title="Sleeved", kind="casual",
                                           fields={"status": "built", "sleeves": " Purple "}))
        self.assertIn("- **Status:** built\n- **Sleeves:** Purple\n", self.text("casual/sleeved"))
        self.assertEqual(self.sleeve_warnings(answer), [])
        answer = api.create_deck(self.body(title="Bare", kind="casual", fields={"status": "built"}))
        self.assertTrue(any(w.startswith(self.NO_SLEEVES) for w in answer["warnings"]), answer["warnings"])
        check = api.check_draft(self.body(kind="casual", fields={"status": "built", "sleeves": "purple"}))
        self.assertEqual(self.sleeve_warnings(check), [])          # Sleeved's colour too: fine (E8-S20)
        error = self.assertApiError(400, api.create_deck, self.body(title="Unbuilt", kind="casual",
                                                                    fields={"sleeves": "Purple"}))
        self.assertEqual(error.extra["blocks"][0]["field"], "sleeves")


class DeckBoxTests(EditorTestCase):
    """The Deck box header field: kept like Sleeves (built decks only, gone when taken apart)."""

    def test_set_after_sleeves_changed_and_removed(self):
        self.assertNotIn("deck_box", api.edit_view("casual/gruul-test")["editable_fields"])
        answer = self.save("casual/gruul-test", fields={"status": "built", "built_version": "target",
                                                        "sleeves": "Red", "deck_box": " Green  box "})
        self.assertIn("- **Sleeves:** Red\n- **Deck box:** Green box\n\n", self.text("casual/gruul-test"))
        self.assertEqual(answer["deck"]["fields"]["deck_box"], "Green box")
        self.assertIn("deck_box", answer["deck"]["editable_fields"])
        check = api.check_draft(self.body(id="casual/gruul-test", fields={"deck_box": " Green box"}))
        self.assertEqual((check["ok"], check["changes"]["fields"]), (True, []))
        self.save("casual/gruul-test", fields={"deck_box": None})
        self.assertNotIn("Deck box", self.text("casual/gruul-test"))
        self.assertIn("- **Sleeves:** Red\n", self.text("casual/gruul-test"))

    def test_bad_values_and_decks_that_arent_built(self):
        self.save("casual/gruul-test", fields={"status": "built"})
        for bad in ("x" * 41, "Box\nTwo", "", 7):
            with self.subTest(bad=bad):
                check = api.check_draft(self.body(id="casual/gruul-test", fields={"deck_box": bad}))
                self.assertEqual([b["field"] for b in check["blocks"]], ["deck_box"])
        self.assertTrue(api.check_draft(self.body(id="casual/gruul-test", fields={"deck_box": "x" * 40}))["ok"])
        check = api.check_draft(self.body(id="casual/table-test", fields={"deck_box": "Box"}))
        self.assertEqual([(b["field"], b["problem"]) for b in check["blocks"]],
                         [("deck_box", "Deck box is the box a built deck is kept in, so it's only for a built deck")])

    def test_taking_a_built_deck_apart_removes_its_deck_box(self):
        self.save("casual/gruul-test", fields={"status": "built", "built_version": "target", "sleeves": "Red",
                                               "deck_box": "Box"})
        view = api.edit_view("casual/gruul-test")
        answer = self.save("casual/gruul-test", fields=view["fields"] | {"status": "idea"})
        self.assertNotIn("Deck box", self.text("casual/gruul-test"))
        self.assertNotIn("deck_box", answer["deck"]["editable_fields"])
        # A stray line on a deck that isn't built is offered, so it can be removed.
        _write(self.path("casual/gruul-test"), self.text("casual/gruul-test").replace(
            "- **Status:** idea\n", "- **Status:** idea\n- **Deck box:** Box\n"))
        self.assertIn("deck_box", api.edit_view("casual/gruul-test")["editable_fields"])
        self.save("casual/gruul-test", fields={"deck_box": None})
        self.assertNotIn("Deck box", self.text("casual/gruul-test"))

    def test_a_new_deck(self):
        api.create_deck(self.body(title="Boxed", kind="casual",
                                  fields={"status": "built", "sleeves": "Pink", "deck_box": "Pink box"}))
        self.assertIn("- **Status:** built\n- **Sleeves:** Pink\n- **Deck box:** Pink box\n", self.text("casual/boxed"))
        error = self.assertApiError(400, api.create_deck, self.body(title="Unbuilt", kind="casual",
                                                                    fields={"deck_box": "Box"}))
        self.assertEqual(error.extra["blocks"][0]["field"], "deck_box")


ACCESSORIES = """id,kind,brand,name,colour,quantity,image,link,image_source,notes
dragon-shield-matte-black,sleeves,Dragon Shield,Matte,black,100,,,,
katana-black,sleeves,KMC,Katana,Black,20,,,,
boulder-black,deck_box,Ultimate Guard,Boulder 100+,black,1,,https://shop.example/p/2,,
"""
DRAGON = "Dragon Shield Matte (black)"


class AccessoryRefTests(EditorTestCase):
    """Sleeves and Deck box lines that hold accessory ids (accessories.kit's warnings)."""

    def setUp(self):
        super().setUp()
        _write(self.box.magic / "accessories.csv", ACCESSORIES)

    def built(self, deck_id, **fields):
        return self.save(deck_id, fields={"status": "built", "built_version": "target"} | fields)

    def check(self, deck_id, **fields):
        return api.check_draft(self.body(id=deck_id, fields={"status": "built"} | fields))["warnings"]

    def test_an_id_round_trips_and_the_pickers_list_the_rows(self):
        answer = self.built("casual/gruul-test", sleeves="dragon-shield-matte-black", deck_box="boulder-black")
        self.assertIn("- **Sleeves:** dragon-shield-matte-black\n- **Deck box:** boulder-black\n",
                      self.text("casual/gruul-test"))
        self.assertEqual(answer["deck"]["fields"]["sleeves"], "dragon-shield-matte-black")
        self.assertEqual([w for w in answer["warnings"] if "sleeves" in w.lower() or "deck box" in w.lower()], [])
        view = api.edit_view("casual/table-test")
        self.assertEqual(view["other_sleeves"], [{"id": "casual/gruul-test", "title": "Gruul Test", "sleeves": DRAGON}])
        self.assertEqual(view["accessories"]["sleeves"], [
            {"id": "dragon-shield-matte-black", "label": DRAGON, "colour": "black", "quantity": 100, "capacity": None,
             "image_url": None, "used_by": [{"holder": "casual/gruul-test", "title": "Gruul Test", "kind": "deck",
                                             "need": 25}]},
            {"id": "katana-black", "label": "KMC Katana (Black)", "colour": "Black", "quantity": 20, "capacity": None,
             "image_url": None, "used_by": []}])
        self.assertEqual([r["id"] for r in view["accessories"]["deck_box"]], ["boulder-black"])
        self.assertEqual(view["accessories"]["deck_box"][0]["used_by"][0]["holder"], "casual/gruul-test")

    def test_too_few_sleeves_for_the_built_list(self):
        warnings = self.check("casual/gruul-test", built_version="target", sleeves="katana-black")
        self.assertIn("Not enough sleeves: this deck needs 25 (23 in the deck, 2 in the sideboard) and KMC Katana "
                      "(Black) has 20. Get 5 more of the same sleeves, or fix the count on the Accessories page.",
                      warnings)
        # Its owned-only version (4 cards) is the one put together: enough.
        warnings = self.check("casual/gruul-test", built_version="owned", sleeves="katana-black")
        self.assertEqual([w for w in warnings if w.startswith("Not enough sleeves")], [])

    def test_a_design_or_colour_another_holder_has_is_no_warning(self):
        # E8-S20: one design may sleeve several decks, and two designs may share a colour.
        self.built("casual/gruul-test", sleeves="dragon-shield-matte-black")
        for sleeves in ("dragon-shield-matte-black", "katana-black", " BLACK ", "Blue"):
            with self.subTest(sleeves=sleeves):
                self.assertEqual([w for w in self.check("casual/table-test", sleeves=sleeves)
                                  if "Gruul Test" in w or "share" in w or "also recorded" in w], [])

    def test_a_deck_box_used_more_often_than_recorded_and_the_wrong_kind(self):
        self.built("casual/gruul-test", sleeves="Red", deck_box="boulder-black")
        warnings = self.check("casual/table-test", sleeves="Blue", deck_box="boulder-black")
        self.assertIn("2 decks use Ultimate Guard Boulder 100+ (black) but 1 is recorded.", warnings)
        warnings = self.check("casual/table-test", sleeves="boulder-black")
        self.assertIn("Sleeves “boulder-black” is a deck box in the accessories list, not sleeves.", warnings)

    def test_products_kept_intact_hold_sleeves_too(self):
        _write(self.box.magic / "products" / "status.csv",
               "file,status,intact,sleeves,deck_box,notes\n"
               "fdn-beginner-box.csv,owned,yes,dragon-shield-matte-black,,kept as its decks\n"
               "fdc-test-precon.csv,preordered,,,,due soon\n")
        title = pool._product_name("fdn-beginner-box.csv")
        self.assertEqual(api.edit_view("casual/table-test")["other_sleeves"],
                         [{"id": "product/fdn-beginner-box", "title": title, "sleeves": DRAGON}])
        # A deck may share the product's design (E8-S20): nothing about it is a warning.
        self.assertEqual([w for w in self.check("casual/table-test", sleeves="dragon-shield-matte-black")
                          if title in w], [])


@unittest.skipUnless(NODE, "needs Node.js")
class SleevesPageTests(unittest.TestCase):
    """The editor page's side of Sleeves (editor.js, editor-screen.js and editor-details.js under Node.js)."""

    def run_editor(self, base, calls):
        setup = (f"editor = {{ mode: 'edit', kind: 'casual', version: 'target', view: {{ lists: {{ owned: null }}, "
                 f"other_sleeves: [{{ id: 'casual/x', title: 'Gruul Ramp', sleeves: 'Red' }}] }}, "
                 f"base: {{ fields: {json.dumps(base)} }} }}; editor.fields = {{ ...editor.base.fields }}; ''")
        return _run_page([setup, *calls], ("core.js", "accessories.js", "editor.js", "editor-drafts.js", "editor-considering.js", "editor-screen.js", "editor-details.js"))[1:]

    def test_offered_changed_and_described(self):
        built = {"status": "built", "player": "user", "archetype": None, "built_version": None,
                 "target_bracket": None, "sleeves": "Blue"}
        self.assertEqual(self.run_editor(built, [
            "String(fieldOffered('sleeves'))", "JSON.stringify(changedFields())",
            "editor.fields.sleeves = '  Blue '; JSON.stringify(changedFields())",
            "editor.fields.sleeves = 'Green'; JSON.stringify(changedFields())", "fieldChangeWords('sleeves', 'Green')",
            # The words a reader gets: a tile's decorative thumb (aria-hidden: "None chosen", a letter) left out.
            "(function shown(n) { return n.data !== undefined ? n.data : n.getAttribute('aria-hidden') === 'true' ? ''"
            " : n.children.map(shown).join(''); })(sleevesField())",
            # Taken apart: the line goes too, whatever was typed.
            "editor.fields.status = 'idea'; String(fieldOffered('sleeves'))", "JSON.stringify(changedFields())",
            "fieldChangeWords('sleeves', null)"]),
            ["true", "{}", "{}", '{"sleeves":"Green"}', "Sleeves: “Blue” → “Green”",
             # Tiles: None, the older free text kept as "Keep" tiles (the file's and the draft's), "+ Add".
             "SleevesNoneNot recorded yetKeep “Blue”Not in the accessories listKeep “Green”"
             "Not in the accessories list+ Add new sleevesOther decks' sleeves: Red (Gruul Ramp).",
             "false", '{"status":"idea","sleeves":null}', "Sleeves: “Blue” → removed (only a built deck has one)"])
        stray = dict(built, status="building")
        self.assertEqual(self.run_editor(stray, [
            "String(fieldOffered('sleeves'))", "JSON.stringify(changedFields())",
            "editor.fields.sleeves = null; JSON.stringify(changedFields())"]),
            ["true", "{}", '{"sleeves":null}'])
        self.assertEqual(self.run_editor(dict(stray, sleeves=None), [
            "String(fieldOffered('sleeves'))", "editor.fields.status = 'built'; String(fieldOffered('sleeves'))"]),
            ["false", "true"])

    def test_a_deck_box_from_the_accessories_list(self):
        # A linked row reads as its name; taking the deck apart drops both kit lines.
        built = {"status": "built", "player": "user", "archetype": None, "built_version": None,
                 "target_bracket": None, "sleeves": "Blue", "deck_box": None}
        rows = {"sleeves": [
                    {"id": "free", "label": "Free (red)", "quantity": 100, "used_by": []},
                    {"id": "held", "label": "Held (blue)", "quantity": 100,
                     "used_by": [{"holder": "casual/x", "title": "Gruul Ramp", "kind": "deck", "need": 60}]}],
                "deck_box": [{"id": "boulder", "label": "Ultimate Guard Boulder 100+ (black)", "quantity": 1,
                              "used_by": []}]}
        self.assertEqual(self.run_editor(built, [
            f"editor.view.accessories = {json.dumps(rows)}; editor.id = 'casual/me'; ''",
            "String(fieldOffered('deck_box'))",
            "editor.fields.deck_box = 'boulder'; JSON.stringify(changedFields())",
            "fieldChangeWords('deck_box', 'boulder')",
            # Sleeves another deck has aren't taken (E8-S20): its tile is enabled and says who else uses them.
            "JSON.stringify(kitRows('sleeves').map((r) => kitTaken('sleeves', r).taken))",
            "(function (b) { return [String(b.disabled || null), b.textContent]; })("
            "kitTile('sleeves', { value: 'held', row: kitRows('sleeves')[1] }, false, false)).join('|')",
            "editor.lists = { Deck: [{ qty: 60 }], Sideboard: [{ qty: 15 }] }; String(kitNeed())",
            "editor.fields.status = 'idea'; String(fieldOffered('deck_box'))", "JSON.stringify(changedFields())"]),
            ["", "true", '{"deck_box":"boulder"}', "Deck box: not set → Ultimate Guard Boulder 100+ (black)",
             "[false,false]", "null|HHeld (blue)100 sleevesAlso used by Gruul Ramp", "75", "false",
             '{"status":"idea","sleeves":null}'])

    def test_sleeves_another_deck_uses_are_warned_about_before_they_are_chosen(self):
        # Matt, 2026-10-19: choosing sleeves already in use asks first; free sleeves are chosen at once.
        built = {"status": "built", "player": "user", "archetype": None, "built_version": None,
                 "target_bracket": None, "sleeves": None, "deck_box": None}
        rows = {"sleeves": [
                    {"id": "free", "label": "Free (red)", "quantity": 100, "used_by": []},
                    {"id": "held", "label": "Held (blue)", "quantity": 100,
                     "used_by": [{"holder": "casual/x", "title": "Gruul Ramp", "kind": "deck", "need": 60}]}],
                "deck_box": []}
        pick = "pickKitTile('sleeves', {{ value: '{0}', row: kitRows('sleeves')[{1}] }}, kitTaken('sleeves', kitRows('sleeves')[{1}]))"
        held, free = pick.format("held", 1), pick.format("free", 0)
        self.assertEqual(self.run_editor(built, [
            f"editor.view.accessories = {json.dumps(rows)}; editor.id = 'casual/me'; ''",
            "asked = null; set = null; answer = null; setField = (k, v) => { set = k + '=' + v; };"
            " askAccessoryChoice = (title, paragraphs) => { asked = title + ' ' + paragraphs.join('');"
            " return Promise.resolve(answer); }; ''",
            # Cancelled: asked, nothing set.
            f"await {held}.then(() => [asked, String(set)].join('|'))",
            # Confirmed: set.
            f"await (answer = 'share', {held}).then(() => String(set))",
            # Confirmed after the editor was left: nothing set.
            f"await (function () {{ set = null; const p = {held}; editor = {{ ...editor }}; return p; }})()"
            ".then(() => String(set))",
            # Free sleeves: no question.
            f"await (asked = null, {free}).then(() => [String(asked), set].join('|'))"]),
            ["", "", "Use Held (blue) here too? Gruul Ramp uses these sleeves already. Several decks can share one design: "
             "just don't play two of them against each other.|null", "sleeves=held", "null", "null|sleeves=free"])

    def test_none_on_a_deck_that_stays_built_is_just_removed(self):
        # Review finding: "(only a built deck has one)" only when the deck stops being built.
        built = {"status": "built", "player": "user", "archetype": None, "built_version": "target",
                 "target_bracket": None, "sleeves": "Blue", "deck_box": "boulder"}
        rows = {"sleeves": [], "deck_box": [{"id": "boulder", "label": "Ultimate Guard Boulder 100+ (black)",
                                             "quantity": 1, "used_by": []}]}
        self.assertEqual(self.run_editor(built, [
            f"editor.view.accessories = {json.dumps(rows)}; editor.id = 'casual/me'; ''",
            "editor.fields.deck_box = null; JSON.stringify(changedFields())",
            "fieldChangeWords('deck_box', null)", "fieldChangeWords('sleeves', null)",
            "fieldChangeWords('built_version', null)",
            "editor.fields.status = 'idea'; fieldChangeWords('deck_box', null)",
            "fieldChangeWords('built_version', null)"]),
            ["", '{"deck_box":null}', "Deck box: Ultimate Guard Boulder 100+ (black) → removed",
             "Sleeves: “Blue” → removed", "Built version: planned list → removed",
             "Deck box: Ultimate Guard Boulder 100+ (black) → removed (only a built deck has one)",
             "Built version: planned list → removed (only a built deck has one)"])

    def test_a_deck_box_with_quantity_0_says_none_left(self):
        built = {"status": "built", "player": "user", "archetype": None, "built_version": None,
                 "target_bracket": None, "sleeves": None, "deck_box": None}
        rows = {"sleeves": [], "deck_box": [{"id": "boulder", "label": "Boulder", "quantity": 0, "used_by": []}]}
        self.assertEqual(self.run_editor(built, [
            f"editor.view.accessories = {json.dumps(rows)}; editor.id = 'casual/me'; ''",
            "JSON.stringify(kitTaken('deck_box', kitRows('deck_box')[0]))",
            "kitTile('deck_box', { value: 'boulder', row: kitRows('deck_box')[0] }, false, false).textContent",
            "JSON.stringify(accTaken({ kind: 'deck_box', quantity: 0, used_by: [] }, 'casual/me'))",
            "accTakenWords(accTaken({ kind: 'deck_box', quantity: 0, used_by: [] }, 'casual/me'))",
            "accTakenWords(accTaken({ kind: 'deck_box', quantity: 1, used_by: [{ holder: 'casual/x', title: 'Gruul' }] }, "
            "'casual/me'))"]),
            ["", '{"others":[],"none":true,"taken":true}', "BBoulder0 boxesNone left (quantity 0)",
             '{"others":[],"none":true,"taken":true}', "None left (quantity 0)", "In use: Gruul"])

    def test_find_picture_keeps_an_edited_rows_saved_values(self):
        # Review finding: Replace picture on an edited row mustn't overwrite its kind, name or count.
        guess = {"kind": "deck_box", "brand": "Dragon Shield", "name": "Matte 100 pack", "quantity": 100}
        make = ("globalThis.mk = (editing, values, lockKind = false) => ({ editing, lockKind, touched: new Set(), "
                "packs: {}, quantityHint: {}, inputs: Object.fromEntries(['kind', 'brand', 'name', 'quantity']"
                ".map((k) => [k, { value: values[k] ?? '' }])) }); ''")
        show = "JSON.stringify([accApplyGuess(c, g), ['kind', 'brand', 'name', 'quantity'].map((k) => c.inputs[k].value)])"
        self.assertEqual(_run_page([
            make, f"globalThis.g = {json.dumps(guess)}; ''",
            "globalThis.c = mk(true, { kind: 'sleeves', brand: '', name: 'Matte (black)', quantity: '160' }); " + show,
            "globalThis.c = mk(false, { kind: 'sleeves' }); " + show,
            "globalThis.c = mk(false, { kind: 'sleeves' }, true); " + show],
            ("core.js", "accessories.js"))[2:],
            ['[["brand"],["sleeves","Dragon Shield","Matte (black)","160"]]',
             '[["kind","brand","name","quantity"],["deck_box","Dragon Shield","Matte 100 pack","100"]]',
             '[["brand","name","quantity"],["sleeves","Dragon Shield","Matte 100 pack","100"]]'])

    def test_a_crop_travels_in_the_picture_address(self):
        url = "/accessory-img/x.png?v=12345678"
        self.assertEqual(_run_page([
            f"JSON.stringify(accCropOf('{url}#crop=0.1,0.2,0.5,0.25'))",
            f"JSON.stringify([accCropOf('{url}'), accCropOf('{url}#crop=0,0,2,1'), accCropOf(null)])",
            f"accWithCrop('{url}#crop=0,0,1,1')",
            f"accWithCrop('{url}', '0.1,0.1,0.5,0.5')",
            "accCropText({ x: 0.123456, y: 0, w: 0.5, h: 1 / 3 })",
            "accCropText({ x: 0, y: 0, w: 1, h: 0.99999 })"],
            ("core.js", "accessories.js", "accessory-pictures.js")),
            ["[0.1,0.2,0.5,0.25]", "[null,null,null]", url, f"{url}#crop=0.1,0.1,0.5,0.5", "0.1235,0,0.5,0.3333", ""])

    def test_back_from_built_a_stray_line_goes_back_to_the_files_value(self):
        # A colour typed (or a list picked) while the status was Built isn't sent once it isn't: the
        # stray line is offered only as Keep / Remove, which wouldn't show the typed value.
        stray = {"status": "building", "player": "user", "archetype": None, "built_version": "target",
                 "target_bracket": None, "sleeves": "Red"}
        self.assertEqual(self.run_editor(stray, [
            "globalThis.changed = () => {}; ''",
            "setField('status', 'built', false); editor.fields.sleeves = 'Blue'; "
            "editor.fields.built_version = 'owned'; JSON.stringify(changedFields())",
            "setField('status', 'idea', false); JSON.stringify(changedFields())",
            # Remove it, picked before or after, stays picked.
            "editor.fields.sleeves = null; setField('status', 'built', false); setField('status', 'building', false); "
            "JSON.stringify(changedFields())"]),
            ["", '{"status":"built","sleeves":"Blue"}', '{"status":"idea"}', '{"sleeves":null}'])

    def test_a_new_deck(self):
        calls = ["editor = { mode: 'new', kind: 'casual', view: null, fields: { title: 'X', kind: 'casual', "
                 "archetype: '', player: 'user', status: 'idea', target_bracket: 2, sleeves: ' Pink ' } }; ''",
                 "String(fieldOffered('sleeves'))", "JSON.stringify(newDeckFields())",
                 "editor.fields.status = 'built'; String(fieldOffered('sleeves'))", "JSON.stringify(newDeckFields())"]
        self.assertEqual(_run_page(calls, ("core.js", "editor.js", "editor-drafts.js", "editor-considering.js", "editor-screen.js"))[1:],
                         ["false", '{"player":"user","status":"idea"}', "true",
                          '{"player":"user","status":"built","sleeves":"Pink"}'])

    def test_a_new_decks_review_lists_its_sleeves(self):
        calls = ["editor = { mode: 'new', kind: 'casual', view: null, fields: { title: 'X', kind: 'casual', "
                 "archetype: '', player: 'user', status: 'idea', target_bracket: 2, sleeves: ' Pink ' } }; "
                 "globalThis.playerWords = (p) => p; ''",     # app.js's
                 "JSON.stringify(newDeckFacts().map(([k]) => k))",
                 "editor.fields.status = 'built'; JSON.stringify(newDeckFacts().filter(([k]) => k === 'Sleeves'))",
                 "editor.fields.sleeves = ''; JSON.stringify(newDeckFacts().filter(([k]) => k === 'Sleeves'))"]
        self.assertEqual(_run_page(calls, ("core.js", "editor.js", "editor-drafts.js", "editor-considering.js", "editor-screen.js", "editor-details.js", "editor-save.js"))[1:],
                         ['["Title","Format","Played by","Status","Archetype"]', '[["Sleeves","Pink"]]',
                          '[["Sleeves","not set"]]'])



if __name__ == "__main__":
    unittest.main()
