"""E10-S46: the owner-only preview of what a Public switch would show (lib/api/visibility_preview.py)."""
import csv
import io
import types
from unittest import mock

from decklab.lib import access, accessories, inventory, server_http, state, visibility
from decklab.lib.api import visibility_preview as preview
from decklab.lib.api.visibility import NOT_READY, OWNER_ONLY
from decklab.lib.state import visibility as values
from decklab.tests.test_activity import _game
from decklab.tests.test_api import _write
from decklab.tests.test_api_permissions import PermissionTestCase, R_DECK

HEADER = "name,set,collector_number,finish,quantity,condition,language,notes\n"
ORDERED = R_DECK.replace("# User2 Elves", "# Shop Elves") + "\n## Notes\n\nTwo more Elves ordered from the shop.\n"
INNOCENT = R_DECK.replace("# User2 Elves", "# Quiet Elves") + (
    "\n## Owned vs needed\n\n| Card | Need | Owned | Missing | ~AUD each | ~AUD missing | Notes |\n|---|---|---|---|---|---|---|\n"
    "| Llanowar Elves | 4 | 2 | 2 | 0.50 | 1.00 | 2 on the way (order 2026-10-01-shop) |\n"
    "\n## Notes\n\nCast elves in order to ramp; the order of plays matters.\n")


class VisibilityPreviewTests(PermissionTestCase):
    def setUp(self):
        super().setUp()
        ready = mock.patch.object(visibility, "READY_THINGS", frozenset(values.THINGS))
        ready.start()
        self.addCleanup(ready.stop)
        magic = self.box.magic
        _write(magic / "collection.csv", HEADER + "Llanowar Elves,fdn,227,nonfoil,3,,,\nSol Ring,cmm,410,nonfoil,4,,,\n")
        _write(magic / "decks" / "casual" / "shop-elves.md", ORDERED)
        _write(magic / "decks" / "casual" / "quiet-elves.md", INNOCENT)
        _write(magic / "people" / "user2" / "collection.csv", HEADER + "Llanowar Elves,fdn,227,nonfoil,9,,,\n")
        _write(magic / "people" / "user2" / "decks" / "casual" / "bought-elves.md",
               R_DECK.replace("# User2 Elves", "# Bought Elves") + "\nBought these at the shop.\n")
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=accessories.FIELDS)
        writer.writeheader()
        for row_id, owner, image in (("a-mat", "user1", "a-mat.jpg"), ("b-box", "user1", ""), ("c-sleeves", "shared", ""),
                                     ("user2-mat", "user2", "")):
            writer.writerow({**dict.fromkeys(accessories.FIELDS, ""), "id": row_id, "kind": "playmat", "owner": owner,
                             "name": "Fixture", "quantity": "1", "image": image})
        _write(magic / "accessories.csv", out.getvalue())

    def ask(self, profile, owner, thing):
        with access.answering(False), access.viewing(profile):
            return preview.preview(owner, thing)

    def test_collection_counts_come_from_the_owners_own_space_only(self):
        home = self.ask("user1", "home", "collection")
        self.assertTrue(home["available"])
        self.assertEqual(home["counts"], {"collection_rows": 2, "collection_cards": 7, "token_rows": 0, "token_cards": 0})
        self.assertFalse(home["public"])
        mine = self.ask("user2", "user2", "collection")
        self.assertEqual(mine["counts"]["collection_cards"], 9)
        self.assertEqual(mine["mentions"], [])

    def test_decks_name_only_own_write_ups_that_mention_orders_or_purchases(self):
        answer = self.ask("matt", "home", "decks")
        ids = [d["id"] for d in answer["mentions"]]
        self.assertIn("casual/shop-elves", ids)
        self.assertIn({"id": "casual/shop-elves", "title": "Shop Elves"}, answer["mentions"])
        self.assertNotIn("casual/quiet-elves", ids, "lists, the table's labels and 'in order to' aren't purchases")
        self.assertFalse(any(i.startswith("user2/") for i in ids))
        home_decks = sum(1 for d in inventory.current().decks.values() if d.space == "home")
        self.assertEqual(answer["counts"]["decks"], home_decks)
        member = self.ask("user2", "user2", "decks")
        self.assertEqual(member["counts"]["decks"], 2)
        self.assertEqual(member["mentions"], [{"id": "user2/casual/bought-elves", "title": "Bought Elves"}])

    def test_mention_rules(self):
        self.assertTrue(preview.mentions_purchases("# T\n\nPreordered the precon.\n"))
        self.assertTrue(preview.mentions_purchases("# T\n\nWorth buying a second copy.\n"))
        # A purchase written as "the order" or "in order ..." is still one.
        self.assertTrue(preview.mentions_purchases("# T\n\nTwo Elves came with the order from the shop.\n"))
        self.assertTrue(preview.mentions_purchases("# T\n\nSwap in once the order arrives.\n"))
        self.assertTrue(preview.mentions_purchases("# T\n\nWaiting on the order.\n"))
        self.assertTrue(preview.mentions_purchases("# T\n\nThe Forest came in order 2026-10-01-shop-a.\n"))
        # Play sequencing isn't.
        self.assertFalse(preview.mentions_purchases("# T\n\nMind the turn order and casting order.\n"))
        self.assertFalse(preview.mentions_purchases("# T\n\nMana order matters; the order of plays too.\n"))
        self.assertFalse(preview.mentions_purchases("# T\n\n```\nDeck\n4 Shop Card (X) 1\n```\n"))
        self.assertFalse(preview.mentions_purchases(None))

    def test_mention_list_is_capped(self):
        for n in range(preview.MENTION_LIMIT + 3):
            _write(self.box.magic / "people" / "user2" / "decks" / "casual" / f"o{n}.md",
                   R_DECK.replace("# User2 Elves", f"# O{n}") + "\nOrdered.\n")
        answer = self.ask("user2", "user2", "decks")
        self.assertEqual(len(answer["mentions"]), preview.MENTION_LIMIT)
        self.assertEqual(answer["more_mentions"], 4)

    def test_games_count_only_records_naming_a_deck_of_the_space(self):
        store = self.box.state
        actor = state.Actor("matt", "Matt", "home")
        store.play_put("games", _game("a" * 32, ("casual/gruul-test", "G"), ("user2/casual/r-elves", "E")), None, actor, "x")
        store.play_put("games", _game("b" * 32, ("user2/casual/r-elves", "E"), ("user2/casual/r-elves", "E")),
                       None, actor, "x")
        self.assertEqual(self.ask("matt", "home", "games")["counts"], {"games": 1})
        self.assertEqual(self.ask("user2", "user2", "games")["counts"], {"games": 2})

    def test_kit_counts_only_that_owners_rows(self):
        self.assertEqual(self.ask("user1", "user1", "accessories")["counts"], {"kit_rows": 2, "kit_pictures": 1})
        self.assertEqual(self.ask("matt", "shared", "accessories")["counts"], {"kit_rows": 1, "kit_pictures": 0})
        self.assertEqual(self.ask("user2", "user2", "accessories")["counts"], {"kit_rows": 1, "kit_pictures": 0})

    def test_anyone_but_the_owner_is_refused_before_anything_is_read(self):
        reads = mock.patch.object(inventory, "current", side_effect=AssertionError("read before refusal"))
        plays = mock.patch.object(self.box.state, "play_list", side_effect=AssertionError("read before refusal"))
        cases = (("matt", "user2", "collection"), ("matt", "user1", "accessories"), ("user1", "matt", "accessories"),
                 ("user2", "home", "decks"), ("user2", "user1", "accessories"), ("user2", "shared", "accessories"),
                 ("matt", "no-such-space", "decks"), ("matt", "home", "nonsense"), ("matt", None, None),
                 (None, "home", "decks"))
        with reads, plays:
            for profile, owner, thing in cases:
                with self.subTest(profile=profile, owner=owner, thing=thing):
                    error = self.assertApiError(403, self.ask, profile, owner, thing)
                    self.assertEqual(error.message, OWNER_ONLY)
            # A script naming nobody owns no switch either.
            with access.using(None):
                self.assertApiError(403, preview.preview, "home", "decks")
            with access.using({"profile": "user2", "email": "", "remote": True}):
                self.assertApiError(403, preview.preview, "home", "games")

    def test_not_ready_is_refused_after_ownership(self):
        with mock.patch.object(visibility, "READY_THINGS", frozenset({"collection"})):
            self.assertEqual(self.assertApiError(409, self.ask, "matt", "home", "decks").message, NOT_READY)
            self.assertApiError(403, self.ask, "matt", "user2", "decks")

    def test_an_unworkable_preview_says_so_and_never_leaks_the_error(self):
        with mock.patch.object(inventory, "current", side_effect=RuntimeError("secret path C:/x")):
            answer = self.ask("matt", "home", "collection")
        self.assertEqual((answer["available"], answer["message"], answer["counts"]),
                         (False, preview.UNAVAILABLE, {}))
        self.assertNotIn("secret", str(answer))
        self.box.state.down = True
        answer = self.ask("user2", "user2", "games")
        self.assertFalse(answer["available"])

    def test_preview_writes_nothing_and_reports_the_current_value(self):
        with access.viewing("matt"):
            from decklab.lib.api import visibility as api
            api.change(self.body("matt", owner="home", thing="decks", public=True))
        before = len(self.box.state.changes())
        self.assertTrue(self.ask("matt", "home", "decks")["public"])
        self.assertEqual(len(self.box.state.changes()), before)

    def test_http_get_only_with_owner_and_thing(self):
        handler = object.__new__(server_http.Handler)
        handler.identity = None
        handler.server = types.SimpleNamespace(remote=False)
        handler._send_json = mock.Mock()
        with access.answering(False), access.viewing("matt"):
            handler.command = "GET"
            handler.path = "/api/visibility/preview?owner=home&thing=collection"
            handler._route()
            status, answer = handler._send_json.call_args.args
            self.assertEqual((status, answer["counts"]["collection_cards"]), (200, 7))
            handler.path = "/api/visibility/preview?owner=home&thing=collection&space=user2"
            self.assertApiError(400, handler._route)
            handler.path = "/api/visibility/preview?owner=user2&thing=collection"
            self.assertApiError(403, handler._route)
            handler.command = "POST"
            handler.path = "/api/visibility/preview?owner=home&thing=collection"
            self.assertApiError(405, handler._route)


if __name__ == "__main__":
    import unittest
    unittest.main()
