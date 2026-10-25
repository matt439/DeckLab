"""Wishlists in the state store: card checks, concurrent phone operations, and
who made each change (the audit trail's actor, via and message)."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from decklab.lib import access, api
from decklab.lib.api import wishlists
from decklab.lib.state import rules
from decklab.tests.test_api import ApiTestCase


def body(action="add", name="Llanowar Elves", profile="user1", **extra):
    return json.dumps({"profile": profile, "action": action, "name": name, **extra}).encode()


def entry(name="Llanowar Elves", **extra):
    return {"name": name, "set": "fdn", "number": "227", "notes": "Suggested for Elves.",
            "source": "magic/buylists/suggestions.md", **extra}


class WishlistTests(ApiTestCase):
    def seed(self, entries=None, profile="user1"):
        self.box.state.seed_wishlist(profile, [entry()] if entries is None else entries)

    def changes(self):
        return self.box.state.changes()

    @staticmethod
    def get(profile="user1"):
        """GET a wishlist as its owner, chosen on the page (a wishlist is its owner's only)."""
        with access.viewing(profile):
            return api.get_wishlist(profile)

    def test_empty_list_is_personal_and_never_seeds(self):
        answer = self.get("user1")
        self.assertEqual(answer["profile"], "user1")
        self.assertEqual(answer["entries"], [])
        self.seed()
        self.assertEqual(self.get("matt")["entries"], [])
        self.assertEqual(api.change_wishlist("matt", body("remove", profile="matt"))["entries"], [])
        self.assertEqual(len(self.get("user1")["entries"]), 1)
        self.assertEqual(self.changes(), [])

    def test_seed_metadata_card_image_and_shared_availability(self):
        self.seed([entry(), entry("Sol Ring", set="ecc", number="57")])
        answer = self.get("user1")
        found = answer["entries"]
        self.assertEqual(found[0]["source"], "magic/buylists/suggestions.md")
        self.assertEqual(found[0]["notes"], "Suggested for Elves.")
        self.assertEqual(found[0]["card"]["img"], "/img/fdn/227/normal")
        self.assertIn("oracle_text", found[0]["card"])
        self.assertEqual(found[0]["have"], {"owned": 5, "on_the_way": 0})
        self.assertEqual(found[1]["have"], {"owned": 0, "on_the_way": 1})
        self.assertEqual(set(answer), {"profile", "entries", "warnings"})

    def test_add_is_canonical_and_duplicate_preserves_notes(self):
        first = api.change_wishlist("user1", body(name="llanowar elves", set="fdn", number="227"))
        self.assertTrue(first["saved"])
        self.assertTrue(first["changed"])
        self.assertEqual(first["entries"][0]["name"], "Llanowar Elves")
        self.assertEqual(set(first), {"profile", "entries", "warnings", "saved", "changed"})
        self.seed()
        duplicate = api.change_wishlist("user1", body(name="LLANOWAR ELVES"))
        self.assertFalse(duplicate["changed"])
        self.assertEqual(duplicate["entries"][0]["notes"], "Suggested for Elves.")
        self.assertEqual(len(self.changes()), 1)

    def test_undo_puts_a_removed_card_back_at_its_place(self):
        # The page's Undo sends the removed card's index as "at".
        self.seed([entry("Sol Ring", set="ecc", number="57"), entry(), entry("Elvish Mystic", set="", number="")])
        api.change_wishlist("user1", body("remove"))
        back = api.change_wishlist("user1", body(name="Llanowar Elves", set="fdn", number="227",
                                                  notes="Suggested for Elves.", at=1))
        self.assertTrue(back["changed"])
        self.assertEqual([e["name"] for e in back["entries"]], ["Sol Ring", "Llanowar Elves", "Elvish Mystic"])
        self.assertEqual([e["name"] for e in self.get()["entries"]], ["Sol Ring", "Llanowar Elves", "Elvish Mystic"])
        for bad in (-1, "1", True, 1.5, rules.MAX_ENTRIES + 1):
            with self.subTest(at=bad):
                self.assertApiError(400, api.change_wishlist, "user1", body(name="Sol Ring", at=bad))
        self.assertApiError(400, api.change_wishlist, "user1", body("remove", at=0))

    def test_each_change_records_who_from_where_and_what(self):
        api.change_wishlist("user1", body(name="llanowar elves"))
        api.change_wishlist("user1", body("remove", name="LLANOWAR ELVES"))
        with access.using({"profile": "user1", "email": "user1@example.com", "remote": True}):
            api.change_wishlist("user1", body(name="Elvish Mystic"))
        added, removed, remote = self.changes()
        self.assertEqual((added["actor"], added["source"], added["via"], added["message"], added["reason"]),
                         ("user1", "web", "home", "Add Llanowar Elves to User1's wishlist", None))
        self.assertEqual(added["rows"][0]["after"]["name"], "Llanowar Elves")
        self.assertEqual((removed["via"], removed["message"]),
                         ("home", "Remove Llanowar Elves from User1's wishlist"))
        self.assertEqual(removed["rows"][0]["op"], "DELETE")
        self.assertEqual((remote["actor"], remote["via"], remote["message"]),
                         ("user1", "tunnel", "Add Elvish Mystic to User1's wishlist"))

    def test_profiles_actions_and_printings_are_validated_before_write(self):
        # A profile id that isn't one is refused as someone else's list is, before it's looked up (E10-S38).
        self.assertApiError(403, api.change_wishlist, "../user1", body())
        self.assertApiError(403, api.change_wishlist, "user1", body(profile="matt"))
        self.assertApiError(404, api.change_wishlist, "user1", body(name="Invented Card"))
        self.assertApiError(400, api.change_wishlist, "user1", body(set="mkm", number="170"))
        self.assertApiError(400, api.change_wishlist, "user1", body(set="fdn"))
        self.assertApiError(400, api.change_wishlist, "user1", body(number="../227", set="fdn"))
        self.assertApiError(400, api.change_wishlist, "user1", body(name="Llanowar\nElves"))
        self.assertApiError(400, api.change_wishlist, "user1", body(unknown=True))
        self.assertApiError(400, api.change_wishlist, "user1", body("remove", set="fdn", number="227"))
        self.assertApiError(400, api.change_wishlist, "user1", body("retry"), contains="action must be add, remove or set")
        # Who may write comes before what the write is: another's list is a 403 whatever the action.
        self.assertApiError(403, api.change_wishlist, "user1", body("retry", profile="matt"))
        self.assertApiError(400, api.change_wishlist, "user1", json.dumps({"profile": "user1", "action": "add"}).encode())
        self.assertEqual(self.box.state.wishlist("user1"), [])
        self.assertEqual(self.changes(), [])

    def test_digital_printing_and_digital_only_card_are_refused(self):
        from decklab.lib import cards
        actual = cards.printing("fdn", "227")
        with mock.patch.object(cards, "printing", return_value=dict(actual, digital=True, games=["arena"])):
            self.assertApiError(400, api.change_wishlist, "user1", body(set="fdn", number="227"))
            self.assertApiError(400, api.change_wishlist, "user1", body())
        self.assertEqual(self.box.state.wishlist("user1"), [])

    def test_offline_list_and_removal_work_but_new_names_wait(self):
        self.seed()
        with self.box.no_index():
            found = self.get("user1")
            self.assertEqual(found["entries"][0]["name"], "Llanowar Elves")
            self.assertIsNone(found["entries"][0]["card"])
            self.assertEqual(found["entries"][0]["have"], {"owned": None, "on_the_way": None})
            self.assertTrue(found["warnings"])
            self.assertApiError(503, api.change_wishlist, "user1", body(name="Elvish Mystic"))
            removed = api.change_wishlist("user1", body("remove"))
            self.assertEqual(removed["entries"], [])
            self.assertTrue(removed["changed"])
            self.assertFalse(api.change_wishlist("user1", body("remove"))["changed"])

    def test_unknown_stored_card_remains_removable(self):
        self.seed([entry("No Longer In Index", set="", number="")])
        answer = self.get("user1")
        self.assertEqual(len(answer["entries"]), 1)
        self.assertIsNone(answer["entries"][0]["card"])
        self.assertTrue(any("No card details" in warning for warning in answer["warnings"]))
        self.assertEqual(api.change_wishlist("user1", body("remove", "No Longer In Index"))["entries"], [])

    def test_a_database_that_is_down_answers_503_and_changes_nothing(self):
        self.seed()
        self.box.state.down = True
        for call, args in ((self.get, ("user1",)),
                           (api.change_wishlist, ("user1", body(name="Elvish Mystic"))),
                           (api.change_wishlist, ("user1", body("remove")))):
            with self.subTest(call=call.__name__):
                error = self.assertApiError(503, call, *args)
                self.assertEqual(error.extra, {"reason": "database"})
        self.box.state.down = False
        self.assertEqual([e["name"] for e in self.box.state.wishlist("user1")], ["Llanowar Elves"])
        self.assertEqual(self.changes(), [])

    def test_a_full_list_refuses_another_card(self):
        self.seed([{"name": f"Card {i}", "set": "", "number": ""} for i in range(rules.MAX_ENTRIES)])
        self.assertApiError(400, api.change_wishlist, "user1", body(), contains=rules.FULL_MESSAGE)
        self.assertEqual(self.changes(), [])

    def test_two_phones_add_without_losing_either_change(self):
        gate = threading.Barrier(2)

        def add(name):
            gate.wait(timeout=5)
            return api.change_wishlist("user1", body(name=name))

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(add, ["Llanowar Elves", "Elvish Mystic"]))
        self.assertTrue(all(result["changed"] for result in results))
        self.assertEqual({e["name"] for e in self.get("user1")["entries"]},
                         {"Llanowar Elves", "Elvish Mystic"})

    # The page's edit sheet ("set") and Remove's Undo (an add with the notes and source put back).
    def test_set_changes_notes_source_and_printing_in_one_audited_change(self):
        self.seed()
        answer = api.change_wishlist("user1", body("set", name="llanowar elves", notes="For Elves", source="",
                                                    set="m19", number="314"))
        self.assertTrue(answer["changed"])
        saved = self.box.state.wishlist("user1")[0]
        self.assertEqual((saved["notes"], saved["source"], saved["set"], saved["number"]),
                         ("For Elves", "", "m19", "314"))
        change, = self.changes()
        self.assertEqual((change["actor"], change["message"]), ("user1", "Change Llanowar Elves on User1's wishlist"))
        # Both printing fields "" removes the printing; nothing else changes.
        api.change_wishlist("user1", body("set", set="", number=""))
        saved = self.box.state.wishlist("user1")[0]
        self.assertEqual((saved["set"], saved["number"], saved["notes"]), ("", "", "For Elves"))
        # Nothing to change: not written.
        self.assertFalse(api.change_wishlist("user1", body("set", notes="For Elves"))["changed"])
        self.assertEqual(len(self.changes()), 2)

    def test_set_is_checked_before_writing(self):
        self.seed()
        self.assertApiError(404, api.change_wishlist, "user1", body("set", name="Sol Ring", notes="x"))
        self.assertApiError(400, api.change_wishlist, "user1", body("set"))
        self.assertApiError(400, api.change_wishlist, "user1", body("set", set="fdn"))
        self.assertApiError(400, api.change_wishlist, "user1", body("set", set="ecc", number="57"))   # another card
        self.assertApiError(400, api.change_wishlist, "user1", body("set", notes=5))
        self.assertApiError(400, api.change_wishlist, "user1", body("set", reason="x"))
        self.assertApiError(403, api.change_wishlist, "user1", body("set", profile="matt", notes="x"))
        self.assertEqual(self.changes(), [])

    def test_undo_adds_the_card_back_with_its_notes_and_source(self):
        answer = api.change_wishlist("user1", body(set="fdn", number="227", notes="Suggested for Elves.",
                                                    source="magic/buylists/suggestions.md"))
        self.assertEqual({k: answer["entries"][0][k] for k in ("notes", "source", "set")},
                         {"notes": "Suggested for Elves.", "source": "magic/buylists/suggestions.md", "set": "fdn"})

    def test_a_deck_source_is_named_by_its_title(self):
        from decklab.lib import inventory
        found = [d for d in inventory.current().decks.values() if d.space == "home" and d.text]
        if not found:
            self.skipTest("the test inventory has no home deck")
        deck = found[0]
        self.seed([entry(source=f"magic/decks/{deck.kind}/{deck.slug}.md"), entry("Sol Ring", set="ecc", number="57"),
                   entry("Elvish Mystic", set="", number="", source="magic/decks/casual/no-such-deck.md")])
        got = {e["name"]: e["source_deck"] for e in self.get("user1")["entries"]}
        self.assertEqual(got["Llanowar Elves"]["id"], deck.id)
        self.assertTrue(got["Llanowar Elves"]["title"])
        self.assertIsNone(got["Sol Ring"])                  # a buylist
        self.assertIsNone(got["Elvish Mystic"])             # a deck that isn't there


class WishlistPrivacyTests(ApiTestCase):
    """A wishlist is its owner's only (permissions.sees_wishlist): GET answers 403 to anyone else."""

    PROFILES = [{"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin", "space": "home"},
                {"id": "user1", "name": "User1", "plays_as": "wife", "role": "member", "space": "home"},
                {"id": "user2", "name": "User2", "plays_as": None, "role": "member", "space": "user2"}]

    def setUp(self):
        super().setUp()
        from decklab.lib.api import settings
        patcher = mock.patch.object(settings, "_config_profiles", return_value=[dict(p) for p in self.PROFILES])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.box.state.seed_wishlist("user1", [entry()])

    def test_only_the_owner_sees_a_wishlist(self):
        def at_home(who):
            with access.viewing(who):
                return api.get_wishlist("user1")

        def tunnel(who):
            with access.using({"profile": who, "email": f"{who}@example.com", "remote": True}):
                return api.get_wishlist("user1")

        self.assertEqual([e["name"] for e in at_home("user1")["entries"]], ["Llanowar Elves"])   # the owner
        self.assertEqual([e["name"] for e in tunnel("user1")["entries"]], ["Llanowar Elves"])    # her login
        for call, who in ((at_home, "matt"), (tunnel, "matt"),          # an admin
                          (at_home, "user2"), (tunnel, "user2"),    # a person with their own space
                          (at_home, None),                              # home, naming nobody
                          (at_home, "nobody-known")):                   # a chooser config.json doesn't list
            with self.subTest(call=call.__name__, who=who):
                error = self.assertApiError(403, call, who)
                self.assertEqual(error.message, wishlists.guard.WISHLIST_HIDDEN)
                self.assertNotIn("Llanowar", error.message)

    def test_an_unknown_profile_answers_as_someone_elses_list(self):
        # E10-S38: the permission is asked before the id is looked up, so a missing profile and a hidden
        # list answer alike; only a reader who may see that list would learn it doesn't exist.
        with access.viewing("user1"):
            error = self.assertApiError(403, api.get_wishlist, "nobody")
            self.assertEqual(error.message, wishlists.guard.WISHLIST_HIDDEN)


class ValidatedEntryTests(ApiTestCase):
    def test_a_checked_entry_carries_notes_and_source(self):
        self.assertEqual(wishlists.validated_entry("llanowar elves", "fdn", "227", "For Elves.", "magic/x.md"),
                         {"name": "Llanowar Elves", "set": "fdn", "number": "227", "notes": "For Elves.",
                          "source": "magic/x.md"})

    def test_without_the_card_check_only_the_forms_are_checked(self):
        self.assertEqual(wishlists.validated_entry(" Invented Card ", check_cards=False)["name"], "Invented Card")
        with self.box.no_index():
            self.assertEqual(wishlists.validated_entry("Elvish Mystic", check_cards=False)["set"], "")
            self.assertApiError(503, wishlists.validated_entry, "Elvish Mystic")
        for args in (("Invented Card", "fdn", ""), ("Invented\tCard",), ("Card", "", "", "", "x" * 301),
                     ("Card", "", "", "bad\x00note")):
            with self.subTest(args=args):
                self.assertApiError(400, lambda *a: wishlists.validated_entry(*a, check_cards=False), *args)
        self.assertEqual(wishlists.validated_entry("Card", notes="line one\nline two", check_cards=False)["notes"],
                         "line one\nline two")
