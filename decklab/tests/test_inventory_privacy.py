"""Tests for E10-S29 (collections and tokens private to their space, no admin reads or writes in
another space on the page, home's records home-only, refusals that name no space) and E10-S43
(User1 changes home's collection and tokens as Matt can). HISTORY.md, "Collections and tokens
are seen only in their own space".

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_inventory_privacy
"""
import json
from collections import Counter
from unittest import mock

from decklab.lib import access, pool
from decklab.lib.api import collection, collection_edit as ce, editor, guard, library, saving
from decklab.lib.api import tokens as api_tokens
from decklab.tests.test_api import _write
from decklab.tests.test_collection_edit import USER2, CollectionEditTestCase

HIDDEN = "That collection isn't public."
CARD = {"name": "llanowar elves", "set": "M19", "collector_number": "314", "finish": "nonfoil", "quantity": 1,
        "condition": "", "language": ""}
R_BUILT = """# User2's Elves

- **Format:** casual
- **Played by:** either
- **Status:** built

## Decklist

```
Deck
2 Llanowar Elves (FDN) 227
```

## Owned vs needed

| Card | Need | Owned | Missing | ~AUD each | ~AUD missing | Notes |
|---|---|---|---|---|---|---|
"""


def hides_every_deck(profile=False):
    """guard.deck_reader as it will answer once a collection can be public but its decks aren't."""
    return lambda target: False


class AdminNarrowingTests(CollectionEditTestCase):
    """Matt, an admin, reads and writes only his own space's collection and tokens on the page."""

    def test_another_spaces_collection_and_tokens_answer_as_a_missing_space(self):
        with self.as_("matt"):
            for space in ("user2", "user3", "nobody"):       # a member's, an empty one's, none at all
                for call in (lambda: collection.collection_view(space=space), lambda: ce.rows_view(space),
                             lambda: ce.download_view(space), lambda: api_tokens.tokens_view(space)):
                    error = self.assertApiError(403, call)
                    self.assertEqual((error.message, error.extra), (HIDDEN, {}), space)
            self.assertEqual([s["id"] for s in collection.space_choices()], ["home"])

    def test_every_write_to_another_space_is_403_with_only_the_error(self):
        sha = self.rows("user2")["sha256"]            # read as a script: the real one, and a stale one
        before = self.box.magic.joinpath("people", "user2", "collection.csv").read_bytes()
        with self.as_("matt"):
            for given in (sha, "0" * 64):
                calls = (
                    lambda: self.call(ce.save_card, "matt", space="user2", action="add", sha256=given, row=CARD),
                    lambda: self.call(ce.import_preview, "matt", space="user2", filename="x.csv", text=USER2),
                    lambda: self.call(ce.import_apply, "matt", space="user2", token="0" * 32, sha256=given),
                    lambda: self.call(api_tokens.save_token, "matt", space="user2", action="add", sha256=None,
                                      row={"front": "Elf Warrior", "quantity": 1}),
                    lambda: self.call(ce.save_card, "matt", space="nobody", action="add", sha256=given, row=CARD),
                )
                for i, call in enumerate(calls):
                    with self.subTest(call=i, sha=given[:4]):
                        error = self.assertApiError(403, call)
                        self.assertEqual((error.message, error.extra), (HIDDEN, {}))
        self.assertEqual(self.box.magic.joinpath("people", "user2", "collection.csv").read_bytes(), before)
        self.assertEqual(self.writes, [])

    def test_his_own_space_is_as_before(self):
        with self.as_("matt"):
            answer = self.save("home", "matt", action="add", row=CARD)
        self.assertTrue(answer["ok"])
        self.assertEqual(self.last_write()[1], "Matt")

    def test_the_command_lines_script_still_reads_every_space(self):
        # Outside any request: a script naming nobody sees and changes every space (the command line
        # doesn't go through these rules at all).
        self.assertEqual(ce.rows_view("user2")["rows"][0]["name"], "Llanowar Elves")
        self.assertApiError(404, ce.rows_view, "nobody")


class HomeMemberTests(CollectionEditTestCase):
    """E10-S43: User1 changes home's collection and tokens as Matt can; other spaces stay closed."""

    def test_user1_saves_and_imports_home_s_collection(self):
        with self.as_("user1"):
            self.assertTrue(collection.collection_view()["editable"])
            answer = self.save("home", "user1", action="add", row=CARD)
            self.assertTrue(answer["ok"])
            self.assertEqual(self.last_write(),
                             ("add card Llanowar Elves (M19 314) in the home collection", "User1"))
            preview = self.call(ce.import_preview, "user1", space="home", filename="mine.csv", text=USER2)
            applied = self.call(ce.import_apply, "user1", space="home", token=preview["token"],
                                sha256=self.rows("home")["sha256"])
        self.assertTrue(applied["ok"])
        self.assertEqual(self.last_write()[1], "User1")
        self.assertEqual(len(self.writes), 2)               # one change each

    def test_user1_saves_home_s_tokens(self):
        sha = api_tokens.tokens_view()["sha256"]
        with self.as_("user1"), mock.patch.object(api_tokens.tokens, "check_names", lambda row: (row, [])):
            answer = self.call(api_tokens.save_token, "user1", space="home", action="add", sha256=sha,
                               row={"front": "Treasure", "back": "", "quantity": 2,
                                    "notes": "single-sided verified"})
        self.assertTrue(answer["saved"])
        self.assertEqual(self.last_write()[1], "User1")

    def test_user1_still_cant_touch_another_space_or_home_s_records(self):
        with self.as_("user1"):
            error = self.assertApiError(403, self.call, ce.save_card, "user1", space="user2", action="add",
                                        sha256="0" * 64, row=CARD)
            self.assertEqual(error.message, HIDDEN)
        from decklab.lib import permissions
        user1 = {"id": "user1", "role": "member", "space": "home", "plays_as": "wife"}
        for action in ("receipts.apply", "orders.edit", "products.edit"):
            self.assertFalse(permissions.can(user1, action))

    def test_a_member_of_another_space_cant_change_home_s(self):
        with self.as_("user2"):
            error = self.assertApiError(403, self.call, ce.save_card, "user2", space="home", action="add",
                                        sha256="0" * 64, row=CARD)
        self.assertEqual(error.extra, {})
        self.assertEqual(self.writes, [])


class DeckNamesTests(CollectionEditTestCase):
    """Inside the answers, a deck is named only to a viewer who may see it: for when a collection can be
    public while its decks aren't (E10-S28's switches), worked out now with the deck rule patched."""

    def setUp(self):
        super().setUp()
        _write(self.box.magic / "people" / "user2" / "decks" / "casual" / "r-elves.md", R_BUILT)

    def holders(self):
        view = collection.collection_view(space="user2")
        elves = next(c for c in view["cards"] if c["name"] == "Llanowar Elves")
        return elves["holders"]

    def test_the_collection_pages_holders(self):
        self.assertEqual(self.holders(), [{"id": "user2/casual/r-elves", "title": "User2's Elves", "quantity": 2}])
        with mock.patch.object(guard, "deck_reader", hides_every_deck):
            self.assertEqual(self.holders(), [{"id": None, "title": "one of User2's decks", "quantity": 2}])

    def test_hidden_holders_are_merged_so_their_count_isnt_told(self):
        p = pool.Pool(Counter({"Opt": 3}), {}, [pool.InUse("casual/a", "A", "built", Counter({"Opt": 1})),
                                                  pool.InUse("casual/b", "B", "built", Counter({"Opt": 2}))])
        shown = collection._holders(p, "Opt", lambda deck_id: False)
        self.assertEqual(shown, [{"id": None, "title": "one of the home decks", "quantity": 3}])

    def test_tokens_uses_and_missing_decks(self):
        use = {"deck": "casual/a", "title": "A", "link": "casual/a", "token": "Elf", "side": "front",
               "state": "ready"}
        self.assertEqual(api_tokens._seen_use(use, lambda d: True), use)
        self.assertEqual(api_tokens._seen_use(use, lambda d: False),
                         {**use, "deck": None, "title": "one of the home decks", "link": None})
        two = [use, {**use, "deck": "casual/b", "title": "B", "link": "casual/b"}]
        self.assertEqual(api_tokens._seen_uses(two, lambda d: False),       # merged: their number isn't told
                         [{**use, "deck": None, "title": "one of the home decks", "link": None}])
        self.assertEqual(api_tokens._seen_uses(two, lambda d: True), two)
        gap = {"key": "k", "name": "Elf", "decks": [{"id": "casual/a", "title": "A", "link": "casual/a"},
                                                   {"id": "casual/b", "title": "B", "link": None},
                                                   {"id": "user2/casual/c", "title": "C", "link": None}]}
        seen = api_tokens._seen_gap(gap, lambda d: d == "casual/a")
        self.assertEqual(seen["decks"], [{"id": "casual/a", "title": "A", "link": "casual/a"},
                                         {"id": None, "title": "one of the home decks", "link": None},
                                         {"id": None, "title": "one of User2's decks", "link": None}])

    def test_the_tokens_page_answer(self):
        use = {"deck": "casual/a", "title": "Secret", "link": "casual/a", "token": "Elf", "side": "front",
               "state": "ready"}
        gap = {"key": "k", "name": "Elf", "kind": "token", "image": None, "state": "none", "on_the_way": 0,
               "decks": [{"id": "casual/a", "title": "Secret", "link": "casual/a"}]}
        incoming = [{"order": "2026-10-01-shop", "component": "tokens", "path": "magic/orders/x.csv", "rows": []}]
        with mock.patch.object(api_tokens.tokens, "row_uses", lambda *a: {0: [use]}), \
                mock.patch.object(api_tokens.tokens, "gaps", lambda *a: [gap]), \
                mock.patch.object(api_tokens.tokens, "incoming", lambda: (incoming, ["magic/orders/x.csv: odd"])):
            seen = api_tokens.tokens_view()
            with mock.patch.object(guard, "deck_reader", hides_every_deck), \
                    mock.patch.object(guard, "sees_home_records", lambda profile=False: False):
                hidden = api_tokens.tokens_view()
        self.assertEqual(seen["incoming"][0]["order"], "2026-10-01-shop")
        self.assertEqual(hidden["incoming"], [])            # pending token orders: home's records only
        text = json.dumps(hidden)
        for secret in ("Secret", "casual/a", "2026-10-01-shop", "magic/orders"):
            self.assertNotIn(secret, text)
        self.assertEqual(hidden["missing"][0]["decks"], [{"id": None, "title": "one of the home decks",
                                                          "link": None}])

    def test_pool_warnings_and_unknown_cards(self):
        p = pool.Pool(Counter(), {}, [], unresolved={"Grizly Bears": {"casual/a"}, "Opt?": {"magic/collection.csv"},
                                                     "Shok": {"magic/orders/2026-10-01-shop.csv"}},
                      warnings=["casual/a can't be read: bad", "every card in magic/orders/x.csv is owned",
                                "casual/b: installed stand-ins can't be read"],
                      warning_decks={"casual/a can't be read: bad": "casual/a",
                                     "casual/b: installed stand-ins can't be read": "casual/b"})
        with mock.patch.object(guard, "deck_reader", lambda profile=False: (lambda d: d == "casual/b")), \
                mock.patch.object(guard, "sees_home_records", lambda profile=False: False):
            self.assertEqual(library.visible_warnings(p), ["casual/b: installed stand-ins can't be read"])
            self.assertEqual(library.visible_unresolved(p.unresolved), {"Opt?": ["the home collection"]})
        self.assertEqual(library.visible_warnings(p), p.warnings)        # a script: every one

    def test_the_pool_says_which_deck_a_warning_is_about(self):
        _write(self.box.magic / "people" / "user2" / "decks" / "casual" / "r-elves.md",
               R_BUILT.replace("- **Status:** built", "- **Status:** built\n- **Built version:** owned-only"))
        p = pool.load_pool("user2")
        about = [text for text in p.warnings if text.startswith("user2/casual/r-elves")]
        self.assertTrue(about, p.warnings)
        self.assertEqual({p.warning_decks[text] for text in about}, {"user2/casual/r-elves"})

    def test_the_tables_out_of_date_lists_held_spaces(self):
        held = {"decks": [], "spaces": [{
            "space": "home", "why": "home's pool is incomplete",
            "warnings": ["casual/secret can't be read: x", "every card in magic/orders/o.csv is owned", "plain"],
            "unknown": [{"name": "Grizly Bears", "where": ["casual/secret"]},
                        {"name": "Opt?", "where": ["casual/secret", "magic/collection.csv"]},
                        {"name": "Shok", "where": ["magic/orders/o.csv"]}]}]}
        with mock.patch.object(saving.pool, "table_blockers", lambda p=None, only=None: held), \
                mock.patch.object(guard, "deck_reader", hides_every_deck), \
                mock.patch.object(guard, "sees_home_records", lambda profile=False: False):
            view = saving.stale_view()
        entry = view["held"][0]
        self.assertEqual(entry["unknown"], [{"name": "Opt?", "where": ["the home collection"]}])
        self.assertEqual(entry["warnings"], [])         # neither the deck's nor home's records' words
        self.assertNotIn("secret", json.dumps(view))

    def test_the_card_finder_ignores_a_hidden_decks_id(self):
        refused = mock.patch.object(pool, "self_ids", side_effect=AssertionError("read for a hidden deck"))
        with refused, self.assertRaises(AssertionError):           # a deck it sees: its copies count
            editor.find_cards("elves", "owned", deck_id="user2/casual/r-elves")
        with refused, mock.patch.object(guard, "sees_deck", lambda target, profile=False: False):
            answer = editor.find_cards("elves", "owned", deck_id="user2/casual/r-elves")
        self.assertIn("cards", answer)

    def test_the_card_finder_answers_a_hidden_space_as_a_missing_one(self):
        with self.as_("matt"):
            for space in ("user2", "user3", "nosuch"):
                for scope in ("all", "owned"):
                    with self.subTest(space=space, scope=scope):
                        error = self.assertApiError(403, lambda: editor.find_cards("elves", scope, space=space))
                        self.assertEqual((error.message, error.extra), (HIDDEN, {}))
            self.assertIn("cards", editor.find_cards("elves", "all", space="home"))
            self.assertIn("cards", editor.find_cards("elves", "all"))


class ActivityTests(CollectionEditTestCase):
    """A member's Activity rows don't reach a named admin (E10-S29): their settings, games, collection,
    tokens and decks; a script naming nobody still sees them."""

    PROFILES = {"matt": {"id": "matt", "name": "Matt", "role": "admin", "space": "home"},
                "user2": {"id": "user2", "name": "User2", "role": "member", "space": "user2"}}

    def change(self, *rows):
        return {"id": 1, "at": "2026-10-18T00:00:00+00:00", "actor": "user2", "source": "web", "via": None,
                "message": "m", "reason": None, "rows": list(rows)}

    def test_a_members_rows(self):
        from decklab.lib import permissions
        from decklab.lib.api import activity
        setting = {"table": "profile_setting", "op": "UPDATE", "key": {"profile_id": "user2"},
                   "before": {"profile_id": "user2", "key": "theme", "value": "light"},
                   "after": {"profile_id": "user2", "key": "theme", "value": "dark"}}
        game = {"table": "play_record", "op": "INSERT", "key": {},
                "after": {"deck_ids": ["user2/casual/a", "user2/casual/b"], "kind": "games"}}
        card = {"table": "collection_card", "op": "INSERT", "key": {},
                "after": {"space_id": "user2", "name": "Opt", "set_code": "fdn", "collector_number": "60",
                          "finish": "nonfoil", "quantity": 1}}
        matt = self.PROFILES["matt"]
        for row in (setting, game, card):
            with self.subTest(table=row["table"]):
                named = activity.visible_change(self.change(row), "all", self.PROFILES, me="matt",
                                                spaces=permissions.inventory_spaces(matt))
                self.assertIsNone(named)
                script = activity.visible_change(self.change(row), "all", self.PROFILES, me=None, spaces=None)
                self.assertIsNotNone(script)

    def test_a_change_set_the_database_filtered_whole(self):
        """The database leaves out every row of another space's change set for him (raw == []):
        hidden whole, not shown as a change with its actor and message."""
        from decklab.lib import permissions
        from decklab.lib.api import activity
        change = dict(self.change(), message="import 40 cards into User2's collection from elves.csv",
                      source="cli", total=40)
        named = activity.visible_change(change, "all", self.PROFILES, me="matt",
                                        spaces=permissions.inventory_spaces(self.PROFILES["matt"]))
        self.assertIsNone(named)
        from decklab.tests.test_activity import _card_row
        # A script's store fetch isn't filtered: it receives the actual audit rows too.
        whole = dict(change, rows=[_card_row("user2", "Opt", n) for n in range(40)])
        script = activity.visible_change(whole, "all", self.PROFILES, me=None, spaces=None)
        self.assertEqual(script["message"], change["message"])

    def test_a_mixed_change_sets_words_need_every_row(self):
        from decklab.lib.api import activity
        home = {"table": "collection_card", "op": "INSERT", "key": {},
                "after": {"space_id": "home", "name": "Opt", "set_code": "fdn", "collector_number": "60",
                          "finish": "nonfoil", "quantity": 1}}
        change = dict(self.change(home), actor="claude", source="cli", message="User2's and home's", total=2)
        named = activity.visible_change(change, "all", self.PROFILES, me="matt", spaces=["home"])
        self.assertIsNotNone(named)
        self.assertIsNone(named["message"])
        whole = activity.visible_change(dict(change, total=1), "all", self.PROFILES, me="matt", spaces=["home"])
        self.assertEqual(whole["message"], "User2's and home's")
        own = activity.visible_change(dict(change, actor="matt"), "all", self.PROFILES, me="matt", spaces=["home"])
        self.assertIsNone(own["message"])       # the actor must see every row too (E10-S34)


class PoolCountsTests(CollectionEditTestCase):
    """The printing picker and a pasted list count the viewer's own space's cards, never another's,
    even once another space's collection can be public."""

    def test_a_member_counts_their_own_space(self):
        public = mock.patch.object(guard, "inventory_spaces",
                                   lambda profile=False: ["home", "user3"])       # home's made public
        with self.as_("user3"), public, mock.patch.object(pool, "printing_counts",
                                                            side_effect=lambda space="home": {space: 1}):
            from decklab.lib.api import card_lookup
            self.assertEqual(card_lookup._pool_counts(), {"user3": 1})
        with self.as_("matt"), mock.patch.object(pool, "printing_counts", side_effect=lambda space="home": {space: 1}):
            self.assertEqual(card_lookup._pool_counts(), {"home": 1})


if __name__ == "__main__":
    import unittest
    unittest.main()
