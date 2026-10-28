"""Who may use each write route (lib/api/guard.py over lib/permissions.py).

The shared route matrix calls endpoints as Matt (admin), User1 (a home
member who plays as "wife") and User2 (a member with his own space), using
access.using() to supply a tunnel identity. Its "local" and "script" aliases
clear that identity and name User1 and Matt respectively in write bodies;
the named profile's own rights still apply.

These are direct calls outside an HTTP request: without an explicit viewer,
those aliases retain access.script()'s test default for reads. They do not
model an anonymous home browser, which has no script access. Explicit
access.viewing() cases exercise the chooser's profile; HTTP script and
home-listener identity boundaries are covered by the server tests.
A forbidden route answers 403, or 404 for a hidden deck. An allowed route
may answer 400 or 409 because its body is deliberately incomplete; the
shared matrix checks permission boundaries rather than full valid writes.

Each test runs in test_api's Sandbox with a config.json
that has roles and a person space (user2, with one deck). The identity is
faked with access.using(), as the server sets it for a request through the
tunnel. Forge never runs: the run routes stop at their body check.

Run from the repo root: python -m unittest decklab.tests.test_api_permissions
"""
import contextlib
import hashlib
import json
import types
from unittest import mock

from decklab.lib import access, api, config, inventory, jobs, permissions, pool, spaces, state
from decklab.lib import accessories as lib_accessories
from decklab.lib import tokens as lib_tokens
from decklab.lib.api import (accessories, assembly, card_lookup, collection, collection_edit, guard, history,
                             play_records, precons, receipts, shopping, shopping_order_changes, shopping_orders, shopping_queue, tokens as api_tokens)
from decklab.lib.forge import slots
from decklab.lib.api import field_page, forge_runs, variant_page
from decklab.lib.inventory.files import FileInventory
from decklab.lib.state.memory import MemoryStore
from decklab.tests.test_api import ApiTestCase, _write
from decklab.tests.test_collection_edit import ROLES

R_DECK = """# User2 Elves

- **Format:** Casual 60-card, 1v1
- **Status:** idea

## Decklist

```
Deck
4 Llanowar Elves (FDN) 227
```
"""

WHO = ("matt", "user1", "user2", "local", "script")
HOME_WRITERS = {"local": "user1", "script": "matt"}    # body profiles of direct calls without a tunnel identity


class PermissionTestCase(ApiTestCase):

    def setUp(self):
        super().setUp()
        box = self.box
        _write(box.root / "config.json", json.dumps(ROLES))
        _write(box.magic / "people" / "user2" / "decks" / "casual" / "r-elves.md", R_DECK)
        _write(box.magic / "people" / "user2" / "collection.csv",
               "name,set,collector_number,finish,quantity,condition,language,notes\n")
        for target, name, value in ((config, "REPO", box.root), (config, "DATA", box.data),
                                    (collection_edit, "IMPORTS_DIR", box.data / "collection-imports")):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # The inventory writes plain files in the sandbox's repository (the files backend).
        self.addCleanup(inventory.use(FileInventory(box.root)))
        # No simulations mode saved, so the real default (admins) applies.
        box.state = MemoryStore(mode=None)
        self.addCleanup(state.use(box.state))

    def status(self, who, call):
        """The status call(profile) answers as who: 200, or its ApiError's."""
        profile = HOME_WRITERS.get(who, who)
        identity = None if who in HOME_WRITERS else {"profile": who, "email": "", "remote": True}
        with access.using(identity):
            try:
                call(profile)
            except api.ApiError as e:
                return e.status
        return 200

    def check(self, call, allowed, hidden=()):
        """call(profile) is refused (403) exactly for the profiles not in allowed, and for those in
        hidden answers 404 instead, as for a missing deck (a deck they may not see: E10-S30)."""
        # The refused first: an allowed call may change the file the others are checked against.
        got = {}
        for who in sorted(WHO, key=lambda who: who in allowed):
            status = self.status(who, call)
            got[who] = "hidden" if hidden and status == 404 else status != 403
        self.assertEqual(got, {who: "hidden" if who in hidden else who in allowed for who in WHO})

    def body(self, profile, **data):
        return json.dumps({"profile": profile, **data}).encode("utf-8")

    def sha(self, deck_id):
        """The deck text's sha256, read as a script (the fixture's read, whoever the call is made as:
        since E10-S30 a profile can't read another space's deck to get it)."""
        with access.using(None), access.viewing(None), access.answering(True):
            return api.edit_view(deck_id)["sha256"]


class DeckRouteTests(PermissionTestCase):

    def test_save_a_house_deck(self):
        sha = self.sha("casual/gruul-test")         # Played by: either, which counts as Matt's
        self.check(lambda p: api.save_deck(self.body(p, id="casual/gruul-test", sha256=sha)), {"matt", "script"},
                   hidden={"user2"})

    def test_user1_picked_at_home_is_refused_as_through_the_tunnel(self):
        # E10-S03: the chooser names User1 (the header) and the page's body names her too; a deck Played by
        # user (the house's "either" counts as Matt's as well) is refused with the tunnel's words.
        sha = self.sha("casual/gruul-test")
        body = self.body("user1", id="casual/gruul-test", sha256=sha)
        with access.using({"profile": "user1", "email": "", "remote": True}):
            with self.assertRaises(api.ApiError) as remote:
                api.save_deck(body)
        with access.using(None), access.viewing("user1"):
            with self.assertRaises(api.ApiError) as home:
                api.save_deck(body)
            self.assertFalse(api.edit_view("casual/gruul-test")["may_save"])
            self.assertTrue(api.edit_view("commander/elf-commander")["may_save"])
            self.assertFalse(history.deck_history("casual/gruul-test")["may_save"])
        self.assertEqual((home.exception.status, home.exception.message),
                         (403, "You can change the home decks played by you."))
        self.assertEqual(home.exception.message, remote.exception.message)
        with access.using(None):                    # no HTTP request or viewer: a script may
            self.assertTrue(api.edit_view("casual/gruul-test")["may_save"])

    def test_save_user1s_deck(self):
        sha = self.sha("commander/elf-commander")   # Played by: wife
        self.check(lambda p: api.save_deck(self.body(p, id="commander/elf-commander", sha256=sha)),
                   {"matt", "user1", "local", "script"}, hidden={"user2"})

    def test_a_member_cant_give_her_deck_away(self):
        sha = self.sha("commander/elf-commander")
        self.check(lambda p: api.save_deck(self.body(p, id="commander/elf-commander", sha256=sha,
                                                     fields={"player": "user"})), {"matt", "script"},
                   hidden={"user2"})

    def test_only_the_decks_owner_chooses_its_sleeves_and_deck_box(self):
        # User1's deck: hers to choose, not Matt's (his admin role doesn't reach another's accessories).
        # On the home network the writer is User1 too ("local" is her); a script naming Matt is Matt.
        for field in ("sleeves", "deck_box"):
            deck = "commander/elf-commander"
            self.check(lambda p: api.save_deck(self.body(p, id=deck, sha256=self.sha(deck),
                                                         fields={"status": "built", field: "red-sleeves"})),
                       {"user1", "local"}, hidden={"user2"})
            # Creating one with them too (the empty title is a block after the check): a new home deck
            # is played by its writer, so the sleeves are theirs to choose.
            self.check(lambda p: api.create_deck(self.body(p, title="", kind="casual", space="home",
                                                           fields={"status": "built", field: "red-sleeves"})),
                       {"matt", "user1", "local", "script"})

    def test_a_member_may_keep_or_free_her_decks_sleeves(self):
        path = self.box.magic / "decks" / "commander" / "elf-commander.md"
        text = path.read_text(encoding="utf-8").replace(
            "- **Status:** idea\n", "- **Status:** built\n- **Sleeves:** red\n- **Deck box:** blue box\n")
        _write(path, text)
        sha = self.sha("commander/elf-commander")
        deck = "commander/elf-commander"
        # The values as they are (echoed back by the editor): no change, so no admin needed.
        self.assertNotEqual(self.status("user1", lambda p: api.save_deck(self.body(
            p, id=deck, sha256=sha, fields={"sleeves": " red ", "deck_box": "blue box"}))), 403)
        # The same for Matt: an admin may save her deck while its sleeves stay as they are.
        self.assertNotEqual(self.status("matt", lambda p: api.save_deck(self.body(
            p, id=deck, sha256=self.sha(deck), fields={"sleeves": "red", "deck_box": "blue box"}))), 403)
        for fields in ({"sleeves": "green"}, {"deck_box": None}, {"sleeves": None, "status": "built"}):
            # Changing them is hers alone.
            self.assertEqual(self.status("matt", lambda p: api.save_deck(self.body(
                p, id=deck, sha256=self.sha(deck), fields=fields))), 403, fields)
            self.assertNotEqual(self.status("user1", lambda p: api.save_deck(self.body(
                p, id=deck, sha256=self.sha(deck), fields=fields))), 403, fields)
        sha = self.sha(deck)
        # Taking it apart frees both: that's hers to do.
        self.assertNotEqual(self.status("user1", lambda p: api.save_deck(self.body(
            p, id=deck, sha256=sha, fields={"status": "building", "sleeves": None}))), 403)
        self.assertNotIn("Sleeves", path.read_text(encoding="utf-8"))

    def test_save_a_persons_deck(self):
        # Only User2 sees his deck (E10-S30): to everyone else, Matt the admin included, it's a missing one.
        sha = self.sha("user2/casual/r-elves")
        self.check(lambda p: api.save_deck(self.body(p, id="user2/casual/r-elves", sha256=sha)),
                   {"user2"}, hidden={"matt", "user1", "local", "script"})

    def test_checking_a_draft_is_a_dry_run_for_anyone(self):
        # "Try a change": the editor opens without Save for a deck the visitor can't change, but sees.
        self.check(lambda p: api.check_draft(self.body(p, id="casual/gruul-test")), set(WHO) - {"user2"},
                   hidden={"user2"})
        self.check(lambda p: api.check_draft(self.body(p, id="user2/casual/r-elves")), {"user2"},
                   hidden={"matt", "user1", "local", "script"})
        # A new deck in a space whose decks the viewer can't see is refused as one in a space that
        # doesn't exist is (E10-S38): only User2 and scripts naming nobody check one in his.
        self.check(lambda p: api.check_draft(self.body(p, kind="casual", space="user2")),
                   {"user2", "local", "script"})
        for who in ("matt", "user2"):
            with access.using({"profile": who, "email": "", "remote": True}):
                with self.assertRaises(api.ApiError) as hidden:
                    api.check_draft(self.body(who, kind="casual", space="nobody"))
                self.assertEqual((hidden.exception.status, hidden.exception.message), (403, guard.HIDDEN_SPACE))
        with self.assertRaises(api.ApiError) as missing:
            api.check_draft(self.body("matt", kind="casual", space="nobody"))
        self.assertEqual(missing.exception.status, 404)                  # a script is told

    def test_the_history_offers_restoring_only_to_who_may_save(self):
        from decklab.lib.api import history
        for who, may_save in (("user1", False), ("matt", True)):
            with access.using({"profile": who, "email": "", "remote": True}):
                self.assertEqual(history.deck_history("casual/gruul-test")["may_save"], may_save, who)
        with access.using({"profile": "user2", "email": "", "remote": True}):
            self.assertTrue(history.deck_history("user2/casual/r-elves")["may_save"])
            # A home deck's history is as a missing deck's to him (E10-S30).
            self.assertApiError(404, history.deck_history, "casual/gruul-test", contains="No deck 'casual/gruul-test'")

    def test_the_editor_opens_without_save(self):
        with access.using({"profile": "user2", "email": "", "remote": True}):
            self.assertApiError(404, api.edit_view, "casual/gruul-test")       # a home deck: hidden (E10-S30)
        for who, may_save in (("user1", False), ("matt", True)):
            with access.using({"profile": who, "email": "", "remote": True}):
                view = api.edit_view("casual/gruul-test")
            self.assertTrue(view["editable"], who)                  # the file itself can be edited
            self.assertEqual(view["may_save"], may_save, who)
            if not may_save:
                self.assertTrue(view["why_not_save"])
        with access.using({"profile": "user2", "email": "", "remote": True}):
            self.assertTrue(api.edit_view("user2/casual/r-elves")["may_save"])
            # Not even "Try a change" of a home deck: he can't see it (E10-S30), so it answers 404.
            self.assertApiError(404, api.edit_view, "casual/gruul-test", contains="No deck 'casual/gruul-test'")
        with access.using({"profile": "matt", "email": "", "remote": True}):
            # The admin role doesn't open another space's decks either.
            self.assertApiError(404, api.edit_view, "user2/casual/r-elves")
        self.assertTrue(api.edit_view("casual/gruul-test")["may_save"])         # the home network

    def test_create(self):
        # An empty title is a block (400) after the permission check, so nothing is written.
        self.check(lambda p: api.create_deck(self.body(p, title="", kind="casual")), set(WHO))
        self.check(lambda p: api.create_deck(self.body(p, title="", kind="casual", space="home")),
                   {"matt", "user1", "local", "script"})
        # Only in a space whose decks the writer sees (E10-S30): not Matt (the admin) in User2's.
        self.check(lambda p: api.create_deck(self.body(p, title="", kind="casual", space="user2")),
                   {"user2"})
        self.check(lambda p: api.create_deck(self.body(p, title="", kind="casual", space="home",
                                                       fields={"player": "either"})), {"matt", "script"})

    def test_a_new_deck_in_a_hidden_space_never_probes_its_names(self):
        # E10-S30: Matt may not see User2's decks, so a new deck there is refused (403) before its name
        # is looked up: the same answer whether User2 has a deck of that name or not, and nothing saved.
        with access.using({"profile": "matt", "email": "", "remote": True}):
            taken = self.assertApiError(403, api.create_deck,
                                        self.body("matt", title="R Elves", kind="casual", space="user2"))
            free = self.assertApiError(403, api.create_deck,
                                       self.body("matt", title="Brand New", kind="casual", space="user2"))
        self.assertEqual((taken.message, taken.extra), (free.message, free.extra))
        self.assertNotIn("r-elves", json.dumps([taken.message, taken.extra]))
        self.assertFalse((self.box.magic / "people" / "user2" / "decks" / "casual" / "brand-new.md").exists())

    def test_a_persons_new_deck_goes_in_their_space(self):
        with access.using({"profile": "user2", "email": "", "remote": True}):
            answer = api.create_deck(self.body("user2", title="Mono Green", kind="casual"))
        self.assertEqual(answer["id"], "user2/casual/mono-green")

    def test_paste_a_list(self):
        self.check(lambda p: api.parse_list(self.body(p, text="1 Opt")), set(WHO))

    def test_update_tables(self):
        self.check(lambda p: api.update_tables(self.body(p, decks=[{"id": "casual/gruul-test",
                                                                    "sha256": self.sha("casual/gruul-test")}])),
                   {"matt", "script"}, hidden={"user2"})

    def test_update_tables_skips_decks_that_arent_yours(self):
        decks = [{"id": i, "sha256": self.sha(i)} for i in ("casual/gruul-test", "commander/elf-commander")]
        with access.using({"profile": "user1", "email": "", "remote": True}):
            answer = api.update_tables(self.body("user1", decks=decks))
        self.assertEqual(answer["skipped_not_allowed"], [{"id": "casual/gruul-test", "title": "Gruul Test"}])
        self.assertNotIn("casual/gruul-test", [u["id"] for u in answer["updated"]] + answer["unchanged"])

    def test_the_out_of_date_list_says_which_tables_you_may_update(self):
        listed = [{"id": deck_id, "title": deck_id, "sha256": "0" * 64, "count": 1, "changes": []}
                  for deck_id in ("casual/gruul-test", "commander/elf-commander", "user2/casual/r-elves")]
        # An admin sees neither another space's inventory nor its private decks (E10-S29/E10-S30).
        cases = {"matt": {"casual/gruul-test": True, "commander/elf-commander": True},
                 "user1": {"casual/gruul-test": False, "commander/elf-commander": True},
                 "user2": {"user2/casual/r-elves": True}}
        for who, expected in cases.items():
            with self.subTest(who=who), access.using({"profile": who, "email": "", "remote": True}), \
                    mock.patch.object(pool, "stale_tables", return_value=[dict(e) for e in listed]), \
                    mock.patch.object(pool, "table_blockers", return_value={"decks": [], "spaces": []}):
                stale = api.stale_view()["stale"]
            self.assertEqual({e["id"]: e["may_update"] for e in stale}, expected)
        # On the home network, User1's name on the chooser has her own rights; a script, every one.
        for viewer, expected in (("user1", [False, True]), (None, [True, True, True])):
            with self.subTest(viewer=viewer), access.viewing(viewer), \
                    mock.patch.object(pool, "stale_tables", return_value=[dict(e) for e in listed]):
                stale = api.saving._stale_list(object())
            self.assertEqual([e["may_update"] for e in stale], expected)


class PlayRouteTests(PermissionTestCase):

    def save(self, profile, sides):
        content = {"date": "2026-10-01", "sides": [{"id": side} for side in sides], "result": "a", "notes": ""}
        with mock.patch.object(play_records, "_game", return_value=content):
            return play_records.save_game(self.body(profile, id="", sha256=None, date="2026-10-01", sides=[],
                                                    result="a", notes="", preview=True))

    def test_a_game_needs_one_of_your_decks(self):
        self.check(lambda p: self.save(p, ["casual/gruul-test", "commander/elf-commander"]),
                   {"matt", "user1", "local", "script"})
        self.check(lambda p: self.save(p, ["casual/gruul-test", "casual/gruul-test"]), {"matt", "script"})
        self.check(lambda p: self.save(p, ["user2/casual/r-elves", "casual/gruul-test"]),
                   {"matt", "user2", "script"})

    def test_a_sideboard_plan_too(self):
        content = {"deck": {"id": "commander/elf-commander"}, "opponent": {"id": "casual/gruul-test"}}
        with mock.patch.object(play_records, "_sideboard", return_value=content):
            self.check(lambda p: play_records.save_sideboard(self.body(
                p, id="", sha256=None, deck={}, opponent={}, out=[], **{"in": []}, notes="", preview=True)),
                {"matt", "user1", "local", "script"})


class AdminRouteTests(PermissionTestCase):

    def test_receipts(self):
        full = {"order": "x", "fingerprint": "0", "received_on": "2026-10-01", "components": []}
        self.check(lambda p: receipts.preview_receipt(self.body(p, **full)), {"matt", "script"})
        self.check(lambda p: receipts.apply_receipt(self.body(p, preview="0")), {"matt", "script"})

    def test_shopping_checks(self):
        # Marking a received delivery's check done changes an order: an admin's (orders.edit).
        check = {"order": "x", "component": "cards", "check": "Look at it"}
        self.check(lambda p: shopping.resolve_check(self.body(p, **check)), {"matt", "script"})

    def test_purchase_queue_state_changes_are_admin_only(self):
        change = {"row": 1, "state": "long_term", "expect": inventory.current().revision}
        self.check(lambda p: shopping_queue.save_queue_state(self.body(p, **change)), {"matt", "script"})

    def test_order_recording_is_admin_only(self):
        change = {"record": {"id": "x"}, "expect": "stale"}
        self.check(lambda p: shopping_orders.preview_order(self.body(p, **change)), {"matt", "script"})
        self.check(lambda p: shopping_orders.apply_order(self.body(p, preview="0")), {"matt", "script"})

    def test_order_corrections_are_admin_only(self):
        change = {"order": "x", "action": "record", "values": {"seller": "Shop"}, "expect": "stale"}
        self.check(lambda p: shopping_order_changes.preview_order_change(self.body(p, **change)), {"matt", "script"})
        self.check(lambda p: shopping_order_changes.apply_order_change(self.body(p, preview="0")), {"matt", "script"})

    def test_accessories(self):
        # Not admin-only: each home profile changes its own and the shared ones (the routes check the rows).
        home = {"matt", "user1", "local", "script"}
        self.check(lambda p: accessories.fetch_picture(self.body(p, url="")), home)
        self.check(lambda p: accessories.save_accessory(self.body(p)), home)
        self.check(lambda p: accessories.assign_accessory(self.body(p)), home)

    def test_choosing_a_decks_kit_is_an_edit_of_the_deck(self):
        # E10-S42: deck.edit on the holder and on the deck a move takes them from, as the editor's save needs.
        def assign(p, holder, **extra):
            return accessories.assign_accessory(self.body(p, holder=holder, field="sleeves", id=None,
                                                          holder_sha256="0" * 64, **extra))
        self.check(lambda p: assign(p, "casual/gruul-test"), {"matt", "script"})          # either: Matt's
        self.check(lambda p: assign(p, "commander/elf-commander"), {"matt", "user1", "local", "script"})
        self.check(lambda p: assign(p, "commander/elf-commander", move_from="casual/gruul-test"),
                   {"matt", "script"})


class InventoryRouteTests(PermissionTestCase):

    # E10-S29 and E10-S43: a space's collection and tokens are changed only by its own people, User1
    # ("local" names her) home's as Matt can, and Matt ("script" names him) none of User2's.
    SPACE_WRITERS = (("home", {"matt", "user1", "local", "script"}), ("user2", {"user2"}))

    def test_tokens(self):
        row = {"front": "Llanowar Elves", "quantity": 1}
        for space, allowed in self.SPACE_WRITERS:
            self.check(lambda p: api_tokens.save_token(self.body(p, space=space, action="add", sha256="0" * 64,
                                                                 row=row)), allowed)
        # No space is home's.
        self.check(lambda p: api_tokens.save_token(self.body(p, action="add", sha256="0" * 64, row=row)),
                   {"matt", "user1", "local", "script"})

    def test_a_persons_tokens_go_in_their_file(self):
        with access.using({"profile": "user2", "email": "", "remote": True}):
            answer = api_tokens.save_token(self.body("user2", space="user2", action="add", sha256=None,
                                                     row={"front": "Llanowar Elves", "back": "", "quantity": 2,
                                                          "notes": "single-sided verified"}))
        self.assertEqual(answer["data"]["space"], "user2")
        path = self.box.magic / "people" / "user2" / "tokens.csv"
        self.assertIn("Llanowar Elves", path.read_text(encoding="utf-8"))
        self.assertFalse((self.box.magic / "tokens.csv").exists())
        self.assertEqual(api_tokens.tokens_view("user2")["cards"], 2)
        self.assertEqual(api_tokens.tokens_view()["cards"], 0)

    def test_collection(self):
        for space, allowed in self.SPACE_WRITERS:
            self.check(lambda p: collection_edit.save_card(self.body(p, space=space, action="remove",
                                                                     sha256="0" * 64)), allowed)
            self.check(lambda p: collection_edit.import_preview(self.body(p, space=space, filename="x.csv",
                                                                          text="")), allowed)
            self.check(lambda p: collection_edit.import_apply(self.body(p, space=space, token="0", sha256="0")),
                       allowed)


class OwnRouteTests(PermissionTestCase):

    def test_wishlist(self):
        # Removing a card that isn't on the list: allowed, and it changes nothing.
        remove = {"action": "remove", "name": "Not On The List"}
        self.check(lambda p: api.change_wishlist("user1", self.body(p, **remove)), {"user1", "local"})
        self.check(lambda p: api.change_wishlist("user2", self.body(p, **remove)), {"user2"})

    def test_reading_a_wishlist(self):
        # A wishlist is its owner's only: not an admin's, not a home request's naming nobody ("local" and
        # "script" send no viewer header).
        for owner in ("user1", "user2"):
            got = {who: self.status(who, lambda p, owner=owner: api.get_wishlist(owner)) for who in WHO}
            self.assertEqual(got, {who: 200 if who == owner else 403 for who in WHO}, owner)
        for viewer, expected in (("user1", 200), ("matt", 403), ("user2", 403)):
            with access.viewing(viewer):                # the home page's chooser
                self.assertEqual(self.status("local", lambda p: api.get_wishlist("user1")), expected, viewer)

    def test_settings(self):
        # Each profile's own settings, and an admin those of his own space only (E10-S29).
        self.check(lambda p: api.put_settings("user1", b'{"theme": "dark"}'), {"matt", "user1", "local", "script"})
        # The settings route names no profile in its body: it goes by the viewer, and a home request with no
        # viewer header passes, as a script does (this class's home callers send none).
        self.check(lambda p: api.put_settings("user2", b'{"theme": "dark"}'), {"user2", "local", "script"})
        for viewer, expected in (("user1", 403), ("user2", 200), ("matt", 403)):
            with access.viewing(viewer):                # the home page's chooser names its viewer
                self.assertEqual(self.status("local", lambda p: api.put_settings("user2", b'{"theme": "dark"}')),
                                 expected, viewer)

    def test_someone_elses_name_in_the_body(self):
        with access.using({"profile": "user2", "email": "", "remote": True}):
            self.assertApiError(403, api.parse_list, self.body("matt", text="1 Opt"))


class RunRouteTests(PermissionTestCase):

    def stop_status(self, who, kind, deck_id, *, by_id="matt", public=()):
        """Real route/visibility/stop rules over an inert, target-bearing job; no games start."""
        key = "a" * 64
        fn = types.SimpleNamespace(by="Matt", by_id=by_id)
        if kind == "matchup":
            fn.sides = [{"id": deck_id}, {"id": deck_id}]
            runner, route, extra = forge_runs.FORGE_JOBS, api.stop_matchup, {"key": key}
        elif kind == "field":
            fn.entry = {"id": deck_id}
            runner, route, extra = forge_runs.COORD_JOBS, api.stop_field, {"id": deck_id}
        else:
            fn.base, fn.against = {"id": deck_id}, "field"
            runner, route, extra = forge_runs.COORD_JOBS, api.stop_variant, {"test": key}
        job = types.SimpleNamespace(fn=fn, wait=mock.Mock())
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(guard, "public_deck_spaces", return_value=frozenset(public)))
            stack.enter_context(mock.patch.object(runner, "get", return_value=job))
            stack.enter_context(mock.patch.object(runner, "snapshot", return_value={"status": jobs.RUNNING,
                                                                                  "detail": {}}))
            cancel = stack.enter_context(mock.patch.object(runner, "cancel", return_value=True))
            # The response renderers are separate reader tests; authorization and cancellation stay real.
            stack.enter_context(mock.patch.object(forge_runs, "_matchup_by_key", return_value={}))
            stack.enter_context(mock.patch.object(field_page, "_answer", return_value={}))
            stack.enter_context(mock.patch.object(variant_page, "_forge", return_value=self.box.forge))
            stack.enter_context(mock.patch.object(variant_page, "_pending", return_value={"base": {"id": deck_id},
                                                                                       "against": "field"}))
            stack.enter_context(mock.patch.object(variant_page, "_view", return_value={}))
            status = self.status(who, lambda profile: route(self.body(profile, **extra)))
            self.assertEqual(cancel.call_count, int(status == 200), (who, kind, deck_id, status))
            self.assertEqual(job.wait.call_count, int(status == 200))
            return status

    def test_everyone_may_start_and_stops_require_a_visible_target(self):
        self.set_mode("everyone")
        for call in (api.run_matchup, api.run_field, api.run_variant, api.more_variant):
            self.check(lambda p: call(self.body(p)), set(WHO))
        for kind in ("matchup", "field", "variant"):
            for who in WHO:
                with self.subTest(kind=kind, who=who):
                    self.assertEqual(self.stop_status(who, kind, "casual/gruul-test"),
                                     404 if who == "user2" else 200)

    def test_the_packing_plan_preview(self):
        # Open to anyone who may see the home pool it plans from (InventoryReadTests).
        self.check(lambda p: assembly.assembly_preview(self.body(p, decks=[])), {"matt", "user1", "local", "script"})

    def set_mode(self, mode):
        with access.using({"profile": "matt", "email": "", "remote": True}):
            return api.change_simulations(self.body("matt", mode=mode))

    def test_admins_only_holds_at_home_too(self):
        # The default. It goes by role: User1 named on the home network is refused, a script naming Matt isn't.
        for call in (api.run_matchup, api.run_field, api.run_variant, api.more_variant):
            self.check(lambda p: call(self.body(p)), {"matt", "script"})
        # The start setting does not remove a member's right to stop their own visible run.
        for kind in ("matchup", "field", "variant"):
            with self.subTest(kind=kind):
                self.assertEqual(self.stop_status("local", kind, "casual/gruul-test"), 200)
                self.assertEqual(self.stop_status("user2", kind, "casual/gruul-test", public={"home"}), 403)
                self.assertEqual(self.stop_status("user2", kind, "casual/gruul-test", by_id="user2",
                                                  public={"home"}), 200)
                self.assertEqual(self.stop_status("user2", kind, "user2/casual/r-elves"), 200)
        self.check(lambda p: assembly.assembly_preview(self.body(p, decks=[])), {"matt", "user1", "local", "script"})

    def test_paused_starts_nothing(self):
        self.set_mode("paused")
        for call in (api.run_matchup, api.run_field, api.run_variant, api.more_variant):
            self.check(lambda p: call(self.body(p)), set())
        with access.using({"profile": "user2", "email": "", "remote": True}):
            with self.assertRaises(api.ApiError) as caught:
                api.run_matchup(self.body("user2"))
        self.assertIn("paused", caught.exception.message)
        for kind in ("matchup", "field", "variant"):
            with self.subTest(kind=kind):
                self.assertEqual(self.stop_status("user1", kind, "casual/gruul-test"), 200)


class SimulationsSettingTests(PermissionTestCase):

    def setUp(self):
        super().setUp()
        self.addCleanup(slots.set_limit, None)      # the test package's own slots folder (tests/__init__.py)

    def as_(self, who):
        return access.using({"profile": who, "email": "", "remote": True})

    def test_only_an_admin_changes_it(self):
        self.check(lambda p: api.change_simulations(self.body(p, mode="everyone")), {"matt", "script"})

    def test_what_each_sees(self):
        with self.as_("matt"):
            api.change_simulations(self.body("matt", mode="admins"))
            mine = api.simulations_view()
        self.assertEqual((mine["mode"], mine["by"], mine["may_start"], mine["may_edit"]), ("admins", "Matt", True, True))
        self.assertIn("since", mine)
        self.assertEqual(mine["workers"], slots.limit())
        for who in ("user1", "user2"):
            with self.as_(who):
                hers = api.simulations_view()
            # A member gets the mode and a reason naming nobody, never who set it, when, or the PC's
            # workers (E10-S34, decision F).
            self.assertEqual(hers, {"mode": "admins", "may_start": False, "may_edit": False,
                                    "why_not": permissions.RUNS_ADMINS}, who)
            self.assertNotIn("Matt", json.dumps(hers), who)

    def test_the_worker_limit(self):
        with self.as_("matt"):
            top = api.simulations_view()["max_workers"]
            self.assertEqual(api.change_simulations(self.body("matt", workers=4))["workers"], 4)
            self.assertEqual(slots.limit(), 4)
            self.assertIsNone(api.change_simulations(self.body("matt", workers=top))["workers"])   # all: no limit
            self.assertEqual(api.change_simulations(self.body("matt", workers=2))["workers"], 2)
            self.assertIsNone(api.change_simulations(self.body("matt", workers=None))["workers"])
            for bad in (0, top + 1, "4", 2.5, True):
                with self.subTest(workers=bad), self.assertRaises(api.ApiError) as caught:
                    api.change_simulations(self.body("matt", workers=bad))
                self.assertEqual(caught.exception.status, 400)
            with self.assertRaises(api.ApiError):
                api.change_simulations(self.body("matt", mode="nobody"))
        self.assertEqual(api.simulations_view(None)["mode"], "admins")     # the default, with nothing saved
        self.assertNotIn("unavailable", api.simulations_view(None))
        # Only the mode is the database's: the worker limit's changes write no change set.
        self.assertEqual(self.box.state.changes(), [])

    def test_who_set_it(self):
        with self.as_("matt"):
            api.change_simulations(self.body("matt", mode="paused"))
        api.change_simulations(self.body("matt", mode="everyone"))       # at home (it goes by role there too)
        got = [(c["actor"], c["via"], c["message"]) for c in self.box.state.changes()]
        self.assertEqual(got, [("matt", "tunnel", "Set simulations to paused"),
                               ("matt", "home", "Set simulations to everyone")])
        self.assertEqual(api.simulations_view(None)["by"], "Matt")

    def test_the_database_down(self):
        with self.as_("matt"):
            api.change_simulations(self.body("matt", mode="paused"))
            self.box.state.down = True
            # The last mode known holds (a pause isn't lifted by an outage), and the answer says so.
            seen = api.simulations_view()
            self.assertEqual((seen["mode"], seen["by"], seen.get("unavailable")), ("paused", "Matt", True))
            self.assertEqual(api.simulations.mode(), "paused")
            # A change needs the database, and then the worker limit isn't changed either.
            with self.assertRaises(api.ApiError) as caught:
                api.change_simulations(self.body("matt", mode="everyone", workers=2))
            self.assertEqual((caught.exception.status, caught.exception.extra), (503, {"reason": "database"}))
            self.assertIsNone(slots.limit())
            # The worker limit alone is a file, so it still changes.
            self.assertEqual(api.change_simulations(self.body("matt", workers=2))["workers"], 2)
        self.box.state.down = False
        self.assertNotIn("unavailable", api.simulations_view(None))

    def test_the_default_when_it_was_never_read(self):
        self.box.state.down = True
        seen = api.simulations_view(None)
        self.assertEqual((seen["mode"], seen["by"], seen["unavailable"]), ("admins", None, True))


class MeTests(PermissionTestCase):

    def test_what_each_may_change(self):
        may = access.me({"profile": "user2", "email": "", "remote": True})["may"]
        self.assertEqual((may["admin"], may["spaces"], may["create"]),
                         (False, ["user2"], [{"space": "user2", "player": None}]))
        may = access.me({"profile": "user1", "email": "", "remote": True})["may"]
        # Home's collection and tokens are User1's to change too (E10-S43).
        self.assertEqual((may["admin"], may["spaces"], may["home_player"]), (False, ["home"], "wife"))
        may = access.me({"profile": "matt", "email": "", "remote": True})["may"]
        self.assertEqual((may["admin"], may["spaces"], may["deck_spaces"], may["see_inventory"]),
                         (True, ["home"], ["home"], ["home"]))         # his own space only (E10-S29)
        local = access.me(None)
        self.assertEqual((local["profile"], local["may"]["admin"], local["may"]["spaces"]),
                         (None, True, ["home", "user2", "user3"]))

    def test_at_home_it_answers_for_the_profile_picked(self):
        # E10-S35: the chooser's pick (the viewer header) gets its own "may", as through the tunnel.
        with access.answering(False), access.viewing("user1"):
            user1 = access.me(None)
        self.assertEqual((user1["profile"], user1["name"], user1["remote"]), ("user1", "User1", False))
        self.assertEqual((user1["may"]["admin"], user1["may"]["spaces"], user1["may"]["home_player"]),
                         (False, ["home"], "wife"))
        with access.answering(False), access.viewing("matt"):
            self.assertTrue(access.me(None)["may"]["admin"])

    def test_at_home_naming_nobody_without_the_script_header_gets_nobodys(self):
        with access.answering(False):
            nobody = access.me(None)
        with access.answering(False), access.viewing("nobody-known"):
            unknown = access.me(None)
        for answer in (nobody, unknown):
            self.assertEqual((answer["profile"], answer["may"]["admin"], answer["may"]["spaces"],
                              answer["may"]["see_inventory"], answer["may"]["create"]), (None, False, [], [], []))


class AccessoryVisibilityTests(PermissionTestCase):
    """Private accessories follow their owners: User1's black sleeves (on her Elf Commander) are
    seen by her and unnamed-viewer script fixtures, never by Matt (an admin) or User2. The shared
    grey sleeves (on the "either" Gruul Test) are seen by every home profile."""

    SEE = {"user1", "local", "script"}           # direct no-viewer script fixtures see all
    SEE_SHARED = {"matt", "user1", "local", "script"}

    def setUp(self):
        super().setUp()
        from decklab.tests.test_accessory_fetch import png
        images = self.box.magic / "accessories" / "images"
        for name, value in (("PATH", self.box.magic / "accessories.csv"), ("IMAGES", images)):
            patcher = mock.patch.object(lib_accessories, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # One sleeve for a deck of three cards: too few, so User1's draft check warns about it.
        _write(self.box.magic / "accessories.csv", ",".join(lib_accessories.FIELDS) + "\n"
               "black-sleeves,sleeves,user1,Dragon Shield,Matte,black,1,,black-sleeves.png,,,,\n"
               "grey-sleeves,sleeves,shared,KMC,Hyper Matte,grey,100,,grey-sleeves.png,,,,\n")
        images.mkdir(parents=True, exist_ok=True)
        (images / "black-sleeves.png").write_bytes(png())
        (images / "grey-sleeves.png").write_bytes(png())
        gruul = self.box.magic / "decks" / "casual" / "gruul-test.md"
        _write(gruul, gruul.read_text(encoding="utf-8").replace(
            "- **Status:** building\n",
            "- **Status:** built\n- **Built version:** target\n- **Sleeves:** grey-sleeves\n"))
        path = self.box.magic / "decks" / "commander" / "elf-commander.md"
        _write(path, path.read_text(encoding="utf-8").replace(
            "- **Status:** idea\n", "- **Status:** built\n- **Sleeves:** black-sleeves\n- **Deck box:** blue box\n"))

    def answer(self, who, call):
        identity = None if who in HOME_WRITERS else {"profile": who, "email": "", "remote": True}
        with access.using(identity):
            return call()

    def test_the_accessories_list_and_pictures(self):
        self.check(lambda p: accessories.accessories_view(), self.SEE_SHARED)
        from decklab.tests.test_accessory_fetch import png
        from decklab.tests.test_api_accessories import image_version
        version = image_version(png())                      # both pictures' bytes
        self.check(lambda p: accessories.image_file("grey-sleeves.png", version), self.SEE_SHARED)
        self.check(lambda p: accessories.staged_image("0" * 32 + ".png"), self.SEE_SHARED)
        with access.using({"profile": "user2", "email": "", "remote": True}):
            # Its words name no space (E10-S38).
            self.assertApiError(403, accessories.accessories_view, contains="are private")
            with self.assertRaises(api.ApiError) as hidden:
                accessories.accessories_view()
            self.assertNotIn("home", hidden.exception.message)
        # User1's picture: as if it weren't there for Matt.
        with access.using({"profile": "matt", "email": "", "remote": True}):
            self.assertApiError(404, accessories.image_file, "black-sleeves.png", version)
        with access.using({"profile": "user1", "email": "", "remote": True}):
            self.assertEqual(accessories.image_file("black-sleeves.png", version)[1], "image/png")

    def test_each_sees_only_their_own_and_the_shared_rows(self):
        for who, ids in (("matt", ["grey-sleeves"]), ("user1", ["black-sleeves", "grey-sleeves"]),
                         ("local", ["black-sleeves", "grey-sleeves"])):
            view = self.answer(who, accessories.accessories_view)
            self.assertEqual([i["id"] for i in view["items"]], ids, who)
            holders = sorted(o["id"] for o in view["holders_options"])
            self.assertEqual("commander/elf-commander" in holders, who != "matt", who)
            self.assertIn("casual/gruul-test", holders, who)
            if who == "matt":
                self.assertNotIn("black-sleeves", json.dumps(view))
                self.assertNotIn("Elf Commander", json.dumps(view))
                self.assertEqual(view["owners"], [{"id": "matt", "name": "Matt"},
                                                  {"id": "shared", "name": "shared"}])

    def test_the_home_network_answers_for_the_profile_its_chooser_names(self):
        from decklab.tests.test_accessory_fetch import png
        from decklab.tests.test_api_accessories import image_version
        version = image_version(png())
        with access.viewing("matt"):
            view = accessories.accessories_view()
            self.assertEqual([i["id"] for i in view["items"]], ["grey-sleeves"])
            self.assertApiError(404, accessories.image_file, "black-sleeves.png", version)
            elf = next(d for d in api.decks_index()["decks"] if d["id"] == "commander/elf-commander")
            self.assertIsNone(elf["kit"])
        with access.viewing("user1"):
            self.assertEqual([i["id"] for i in accessories.accessories_view()["items"]],
                             ["black-sleeves", "grey-sleeves"])
        with access.viewing("user2"):
            self.assertApiError(403, accessories.accessories_view)
        with access.viewing("nobody-known"):          # not in config.json: as if nobody were named
            self.assertEqual(len(accessories.accessories_view()["items"]), 2)

    def test_a_shared_rows_holders_the_viewer_cant_see_are_anonymous(self):
        # User1's deck takes the shared grey sleeves in place of hers: Matt sees the row is used,
        # but only by "one of User1's decks".
        for path, old, new in (
                (self.box.magic / "decks" / "casual" / "gruul-test.md", "- **Sleeves:** grey-sleeves\n", ""),
                (self.box.magic / "decks" / "commander" / "elf-commander.md", "black-sleeves", "grey-sleeves")):
            _write(path, path.read_text(encoding="utf-8").replace(old, new))
        view = self.answer("matt", accessories.accessories_view)
        grey = next(i for i in view["items"] if i["id"] == "grey-sleeves")
        self.assertEqual(grey["used_by"], [{"holder": None, "title": "one of User1's decks", "kind": "deck",
                                            "need": 3}])
        self.assertNotIn("Elf Commander", json.dumps(view))
        grey = next(i for i in self.answer("user1", accessories.accessories_view)["items"]
                    if i["id"] == "grey-sleeves")
        self.assertEqual(grey["used_by"][0]["holder"], "commander/elf-commander")

    def test_a_shared_deck_shows_its_kit_to_every_home_profile(self):
        for who in WHO:
            sees = who in self.SEE_SHARED
            index = self.answer(who, api.decks_index)
            if who == "user2":        # a home deck isn't his to see: not listed, its page a missing deck's (E10-S30)
                self.assertNotIn("casual/gruul-test", [d["id"] for d in index["decks"]])
                self.assertNotIn("grey-sleeves", json.dumps(index))
                with access.using({"profile": who, "email": "", "remote": True}):
                    self.assertApiError(404, api.deck_view, "casual/gruul-test")
                continue
            gruul = next(d for d in index["decks"] if d["id"] == "casual/gruul-test")
            self.assertEqual(gruul["sleeves"], "grey-sleeves" if sees else None, who)
            self.assertEqual(gruul["kit"] is not None, sees, who)
            page = self.answer(who, lambda: api.deck_view("casual/gruul-test"))
            self.assertEqual(page["summary"]["kit"] is not None, sees, who)

    def test_the_library_and_deck_page(self):
        for who in WHO:
            sees = who in self.SEE
            index = self.answer(who, api.decks_index)
            if who == "user2":        # a home deck isn't his to see at all (E10-S30)
                self.assertNotIn("commander/elf-commander", [d["id"] for d in index["decks"]])
                self.assertNotIn("black-sleeves", json.dumps(index))
                with access.using({"profile": who, "email": "", "remote": True}):
                    self.assertApiError(404, api.deck_view, "commander/elf-commander")
                continue
            elf = next(d for d in index["decks"] if d["id"] == "commander/elf-commander")
            self.assertEqual(elf["sleeves"], "black-sleeves" if sees else None, who)
            self.assertEqual(elf["deck_box"], "blue box" if sees else None, who)
            self.assertEqual(elf["kit"] is not None, sees, who)
            page = self.answer(who, lambda: api.deck_view("commander/elf-commander"))
            s = page["summary"]
            self.assertEqual((s["kit"] is not None, s["holder_sha256"] is not None, s["sleeves"] is not None),
                             (sees, sees, sees), who)
            self.assertEqual(any("sleeve" in w.lower() for w in page["warnings"]), sees, who)
            if not sees:
                self.assertNotIn("black-sleeves", json.dumps(page))
                self.assertNotIn("black-sleeves", json.dumps(index))

    def test_the_editor_and_a_draft_check(self):
        for who in WHO:
            sees = who in self.SEE
            if who == "user2":        # a home deck is hidden from him: as a missing one (E10-S30)
                with access.using({"profile": who, "email": "", "remote": True}):
                    self.assertApiError(404, api.edit_view, "commander/elf-commander")
                    self.assertApiError(404, api.check_draft, self.body(who, id="commander/elf-commander"))
                continue
            view = self.answer(who, lambda: api.edit_view("commander/elf-commander"))
            self.assertEqual(view["fields"]["sleeves"], "black-sleeves" if sees else None, who)
            self.assertEqual(view["field_text"]["Deck box"], "blue box" if sees else None, who)
            self.assertEqual("sleeves" in view["editable_fields"], sees, who)
            self.assertEqual(bool(view["accessories"]["sleeves"]), sees, who)
            if not sees:
                self.assertNotIn("black-sleeves", json.dumps(view))
            check = self.answer(who, lambda: api.check_draft(self.body(
                HOME_WRITERS.get(who, who), id="commander/elf-commander")))
            self.assertEqual(any("sleeve" in w["text"].lower() if isinstance(w, dict) else "sleeve" in w.lower()
                                 for w in check["warnings"]), sees, who)

    def test_a_draft_s_played_by_doesnt_show_another_s_kit(self):
        # Matt's draft says Played by: user, but the deck's stored Sleeves are still User1's.
        check = self.answer("matt", lambda: api.check_draft(self.body(
            "matt", id="commander/elf-commander", fields={"player": "user"})))
        shown = json.dumps(check["warnings"])
        for hidden in ("black-sleeves", "Dragon Shield", "black", "User1", "sleeve"):
            self.assertNotIn(hidden, shown)
        # Her own check still has them.
        check = self.answer("user1", lambda: api.check_draft(self.body("user1", id="commander/elf-commander")))
        self.assertIn("sleeve", json.dumps(check["warnings"]).lower())

    def test_handing_on_a_deck_with_kit_is_an_accessories_change(self):
        deck = "commander/elf-commander"
        path = self.box.magic / "decks" / "commander" / "elf-commander.md"
        before = path.read_bytes()
        # Matt, an admin, may give a deck to someone else, but not one holding User1's sleeves.
        with access.using({"profile": "matt", "email": "", "remote": True}):
            self.assertApiError(403, api.save_deck, self.body("matt", id=deck, sha256=self.sha(deck),
                                                               fields={"player": "user"}), contains="sleeves")
        self.assertEqual(path.read_bytes(), before)
        # The shared grey sleeves on the "either" Gruul Test may go with it to Matt.
        gruul = "casual/gruul-test"
        with access.using({"profile": "matt", "email": "", "remote": True}):
            saved = api.save_deck(self.body("matt", id=gruul, sha256=self.sha(gruul), fields={"player": "user"}))
        self.assertTrue(saved["changed"])
        # Taking a deck apart as it changes hands frees its kit: nothing to choose.
        with access.using({"profile": "matt", "email": "", "remote": True}):
            saved = api.save_deck(self.body("matt", id=deck, sha256=self.sha(deck),
                                            fields={"player": "user", "status": "building"}))
        self.assertNotIn("black-sleeves", path.read_text(encoding="utf-8"))

    def test_a_revision_and_the_packing_plan(self):
        from decklab.tests.test_deck_history import install, revision as saved
        deck_id = "commander/elf-commander"
        text = (self.box.magic / "decks" / "commander" / "elf-commander.md").read_text(encoding="utf-8")
        install(self.box, {deck_id: [saved(deck_id, 1, text, op="A", actor="user1", kit=True,
                                           message="Sleeve it in black-sleeves")]})
        revision = "1"
        for who in WHO:
            if who == "user2":        # a home deck's history is as a missing deck's (E10-S30)
                with access.using({"profile": who, "email": "", "remote": True}):
                    self.assertApiError(404, history.deck_history, deck_id)
                    self.assertApiError(404, history.deck_revision, deck_id, revision)
                    self.assertApiError(403, assembly.assembly_view, "commander/elf-commander")
                continue
            subject = self.answer(who, lambda: history.deck_history(deck_id))["revisions"][0]["subject"]
            self.assertEqual(subject, "Sleeve it in black-sleeves" if who in self.SEE else None, who)
            sees = who in self.SEE
            old = self.answer(who, lambda: history.deck_revision("commander/elf-commander", revision))
            self.assertEqual(old["fields"]["Sleeves"], "black-sleeves" if sees else None, who)
            self.assertEqual(old["current"]["fields"]["sleeves"], "black-sleeves" if sees else None, who)
            if who == "user2":        # the packing plan is the home pool's (InventoryReadTests)
                with access.using({"profile": who, "email": "", "remote": True}):
                    self.assertApiError(403, assembly.assembly_view, "commander/elf-commander")
                continue
            plan = self.answer(who, lambda: assembly.assembly_view("commander/elf-commander"))
            deck = plan["decks"][0]
            self.assertEqual((deck["kit"] is not None, deck["sleeves"] is not None, deck["sleeves_need"] is not None),
                             (sees, sees, sees), who)
            plan = self.answer(who, lambda: assembly.assembly_preview(self.body(
                HOME_WRITERS.get(who, who), decks=[{"id": "commander/elf-commander", "version": "target"}])))
            self.assertEqual(plan["decks"][0]["kit"] is not None, sees, who)

    def test_a_deck_save_chooses_only_what_the_deck_may_take(self):
        csv_path = self.box.magic / "accessories.csv"
        _write(csv_path, csv_path.read_text(encoding="utf-8")
               + "white-sleeves,sleeves,matt,KMC,Hyper Matte,white,100,,,,,,\n")
        deck = "commander/elf-commander"
        # User1: Matt's sleeves aren't hers to use (she doesn't see them), the shared ones are.
        with access.using({"profile": "user1", "email": "", "remote": True}):
            self.assertApiError(400, api.save_deck, self.body("user1", id=deck, sha256=self.sha(deck),
                                                               fields={"sleeves": "white-sleeves"}))
            self.assertTrue(api.save_deck(self.body("user1", id=deck, sha256=self.sha(deck),
                                                    fields={"sleeves": "grey-sleeves"}))["saved"])
        self.assertIn("- **Sleeves:** grey-sleeves", (self.box.magic / "decks" / "commander" /
                                                      "elf-commander.md").read_text(encoding="utf-8"))
        # Matt: his own sleeves don't go on the house's "either" deck, which takes shared ones only.
        gruul = "casual/gruul-test"
        with access.using({"profile": "matt", "email": "", "remote": True}):
            self.assertApiError(400, api.save_deck, self.body("matt", id=gruul, sha256=self.sha(gruul),
                                                               fields={"sleeves": "white-sleeves"}),
                                contains="shared ones")
            self.assertApiError(400, api.save_deck, self.body("matt", id=gruul, sha256=self.sha(gruul),
                                                               fields={"sleeves": "black-sleeves"}))

    def test_me_says_who_sees_them(self):
        for who in ("matt", "user1", "user2"):
            may = access.me({"profile": who, "email": "", "remote": True})["may"]
            self.assertEqual(may["see_accessories"], who != "user2", who)
        self.assertTrue(access.me(None)["may"]["see_accessories"])

    def test_hiding_them_never_clears_a_files_lines(self):
        # A Sleeves line written by hand in User2's own deck: hidden from him, but his save keeps it.
        path = self.box.magic / "people" / "user2" / "decks" / "casual" / "r-elves.md"
        _write(path, path.read_text(encoding="utf-8").replace(
            "- **Status:** idea\n", "- **Status:** built\n- **Sleeves:** red\n"))
        with access.using({"profile": "user2", "email": "", "remote": True}):
            view = api.edit_view("user2/casual/r-elves")
            self.assertIsNone(view["fields"]["sleeves"])
            answer = api.save_deck(self.body("user2", id="user2/casual/r-elves", sha256=view["sha256"],
                                             fields={"archetype": "Elves"}))
        self.assertTrue(answer["saved"])
        text = path.read_text(encoding="utf-8")
        self.assertIn("- **Sleeves:** red", text)
        self.assertIn("- **Archetype:** Elves", text)


class InventoryReadTests(PermissionTestCase):
    """Who may read the inventory (permissions.sees_inventory, guard.require_sees_inventory): home's
    collection and tokens, shopping list, receipts and packing plan only the home profiles; User2's
    collection and tokens only User2 (E10-S29: an admin's role opens no other space). Each route
    is asked as Matt (admin), User1 (a home member) and User2 (his own space) through the tunnel, a tunnel login that isn't set up, the home
    network naming nobody (everything, as for accessories; a body naming User1) and the home network naming
    User1 or User2 (the chooser's viewer, whose reads and changes follow that profile, E10-S03)."""

    READERS = ("matt", "user1", "user2", "stranger", "local", "local:user1", "local:user2")
    HOME = {"matt", "user1", "local", "local:user1"}
    USER2 = {"user2", "local", "local:user2"}

    def as_(self, who):
        """(the context the request runs in, the profile a body names) for who."""
        stack = contextlib.ExitStack()
        if who.startswith("local"):
            named = who.partition(":")[2] or None
            stack.enter_context(access.using(None))
            stack.enter_context(access.viewing(named))
            return stack, named or "user1"
        stack.enter_context(access.using({"profile": who, "email": "", "remote": True}))
        return stack, who

    def read_status(self, who, call):
        context, profile = self.as_(who)
        with context:
            try:
                call(profile)
            except api.ApiError as e:
                return e.status
        return 200

    def readable(self, call, allowed):
        """call(profile) is refused (403) exactly for the readers not in allowed."""
        got = {who: self.read_status(who, call) != 403 for who in self.READERS}
        self.assertEqual(got, {who: who in allowed for who in self.READERS})

    def test_shopping_is_homes(self):
        self.readable(lambda p: shopping.shopping_overview(), self.HOME)

    def test_receipts_are_homes(self):
        self.readable(lambda p: receipts.receipt_view("2026-10-01-x"), self.HOME)
        full = {"order": "x", "fingerprint": "0", "received_on": "2026-10-01", "components": []}
        # The previews and applies are an admin's too, by role on the home network as well (E10-S03).
        admins = {"matt"}
        self.readable(lambda p: receipts.preview_receipt(self.body(p, **full)), admins)
        self.readable(lambda p: receipts.apply_receipt(self.body(p, preview="0")), admins)
        check = {"order": "x", "component": "cards", "check": "Look at it"}
        self.readable(lambda p: shopping.resolve_check(self.body(p, **check)), admins)
        change = {"row": 1, "state": "long_term", "expect": inventory.current().revision}
        self.readable(lambda p: shopping_queue.save_queue_state(self.body(p, **change)), admins)
        self.readable(lambda p: shopping_orders.preview_order(self.body(
            p, expect="stale", record={"id": "x"})), admins)
        self.readable(lambda p: shopping_orders.apply_order(self.body(p, preview="0")), admins)
        self.readable(lambda p: shopping_order_changes.preview_order_change(self.body(
            p, expect="stale", order="x", action="record", values={"seller": "Shop"})), admins)
        self.readable(lambda p: shopping_order_changes.apply_order_change(self.body(p, preview="0")), admins)
        context, _ = self.as_("user2")
        with context:
            self.assertApiError(403, receipts.receipt_view, "2026-10-01-x", contains="are private")
            with self.assertRaises(api.ApiError) as hidden:
                receipts.receipt_view("2026-10-01-x")
            self.assertEqual(hidden.exception.message, guard.INVENTORY_HIDDEN)
            self.assertNotIn("home", hidden.exception.message)          # it names no space (E10-S38)

    def test_the_collection_and_its_rows(self):
        for space, allowed in (("home", self.HOME), ("user2", self.USER2)):
            self.readable(lambda p: collection.collection_view(space=space), allowed)
            self.readable(lambda p: collection_edit.rows_view(space), allowed)
        # No space is home's.
        self.readable(lambda p: collection_edit.rows_view(), self.HOME)
        # The 403 names no one, and is the same for a space that doesn't exist (E10-S29).
        for who in ("user1", "matt", "local:user1"):
            context, _ = self.as_(who)
            with context:
                for space in ("user2", "nobody"):
                    error = self.assertApiError(403, collection_edit.rows_view, space)
                    self.assertEqual((error.message, error.extra), ("That collection isn't public.", {}), who)

    def test_the_tokens(self):
        for space, allowed in (("home", self.HOME), ("user2", self.USER2)):
            self.readable(lambda p: api_tokens.tokens_view(space), allowed)
        self.readable(lambda p: api_tokens.tokens_view(), self.HOME)

    def test_the_packing_plan(self):
        self.readable(lambda p: assembly.assembly_view(), self.HOME)
        self.readable(lambda p: assembly.assembly_preview(self.body(p, decks=[])), self.HOME)

    def test_a_precons_preview(self):
        # Only where it may add one (collection.edit, E10-S29): Matt is refused User2's before any deck
        # id there is looked up; User1 may preview home's (E10-S43).
        for space, allowed in (("home", self.HOME), ("user2", self.USER2)):
            self.readable(lambda p: precons.precon_preview(file="nothing.json", space=space), allowed)

    def test_the_collections_spaces_are_only_those_it_sees(self):
        everyone = ["home", "user2", "user3"]
        for who, ids in (("matt", ["home"]), ("user1", ["home"]), ("user2", ["user2"]), ("stranger", []),
                         ("local", everyone), ("local:user1", ["home"]), ("local:user2", ["user2"])):
            context, _ = self.as_(who)
            with context:
                self.assertEqual([s["id"] for s in collection.space_choices()], ids, who)

    def test_the_printing_pickers_counts(self):
        # Home's pool for whoever sees it, else the viewer's own space's, else none.
        for who, space in (("matt", "home"), ("user1", "home"), ("user2", "user2"), ("stranger", None),
                           ("local", "home"), ("local:user1", "home"), ("local:user2", "user2")):
            context, _ = self.as_(who)
            with context, mock.patch.object(pool, "printing_counts",
                                            side_effect=lambda space="home": {space: True}) as counts:
                self.assertEqual(card_lookup._pool_counts(), {space: True} if space else {}, who)
                self.assertEqual(counts.called, space is not None, who)

    def test_paste_a_list_defaults_from_the_same_pool_as_the_picker(self):
        # "Paste a list" picks a line's printing from card_lookup._pool_counts, as search and the
        # printing picker do: never home's counts for someone outside the home.
        for who, space in (("matt", "home"), ("user2", "user2"), ("local:user2", "user2"),
                           ("local:user1", "home")):
            context, profile = self.as_(who)
            with context, mock.patch.object(pool, "printing_counts",
                                            side_effect=lambda space="home": {}) as counts:
                api.parse_list(self.body(profile, text="1 Llanowar Elves"))
            self.assertEqual([c.args[0] if c.args else "home" for c in counts.call_args_list], [space], who)

    def test_a_drafts_counts_come_only_from_a_pool_it_sees(self):
        # "Try a change" compares the page's own list with a pool: only one the visitor may see,
        # else owned and availability are None (no counting another space's cards by pasting).
        cases = ((dict(id="casual/gruul-test"), self.HOME), (dict(kind="casual", space="home"), self.HOME),
                 (dict(id="user2/casual/r-elves"), self.USER2),
                 (dict(kind="casual", space="user2"), self.USER2))
        for data, allowed in cases:
            for who in ("matt", "user1", "user2", "local", "local:user1", "local:user2"):
                context, profile = self.as_(who)
                with context:
                    try:
                        answer = api.check_draft(self.body(profile, **data))
                    except api.ApiError as e:
                        if "id" in data:            # a saved deck of a space the writer isn't in: 404
                            # as a missing one (E10-S30), Matt the admin included
                            self.assertEqual(e.status, 404, (data, who))
                            self.assertNotEqual(spaces.space_of(data["id"]),
                                                "user2" if profile == "user2" else "home", (data, who))
                            continue
                        # a new deck in a space it may not make one in
                        self.assertEqual(e.status, 403, (data, who))
                        self.assertNotIn(who, allowed, (data, who))
                        continue
                seen = who in allowed
                self.assertEqual(answer["owned"] is not None, seen, (data, who))
                self.assertEqual(answer["availability"]["target"] is not None, seen, (data, who))

    def test_user2_picked_at_home_is_refused_homes_writes_with_nothing_of_homes(self):
        # At this lower-level API boundary, a named User2 cannot write home's data. The HTTP home
        # listener separately refuses non-home profile selection (E10-S35). A refusal carries only
        # the reason, never a list, conflict or rows, even when the submitted sha256 is stale.
        with access.using(None):
            sha = api_tokens.tokens_view()["sha256"]
            deck_sha = self.sha("casual/gruul-test")
        context, profile = self.as_("local:user2")
        row = {"front": "Treasure", "back": "", "quantity": 1, "notes": "single-sided verified"}
        card = {"name": "Llanowar Elves", "set": "fdn", "collector_number": "227", "finish": "nonfoil",
                "quantity": 1}
        full = {"order": "x", "fingerprint": "0", "received_on": "2026-10-01", "components": []}
        calls = (
            lambda: api_tokens.save_token(self.body(profile, space="home", action="add", sha256="0" * 64, row=row)),
            lambda: api_tokens.save_token(self.body(profile, space="home", action="add", sha256=sha, row=row)),
            lambda: collection_edit.save_card(self.body(profile, space="home", action="add", sha256="0" * 64,
                                                        row=card)),
            lambda: collection_edit.import_preview(self.body(profile, space="home", filename="x.csv", text="")),
            lambda: precons.add_precon(self.body(profile, space="home", file="x.json", title="X",
                                                 sha256="0" * 64)),
            lambda: receipts.preview_receipt(self.body(profile, **full)),
            lambda: receipts.apply_receipt(self.body(profile, preview="0")),
            lambda: shopping.resolve_check(self.body(profile, order="x", component="cards", check="Look")),
            lambda: shopping_queue.save_queue_state(self.body(profile, row=1, state="long_term", expect="stale")),
        )
        decks = (       # a home deck is hidden from him: 404 as a missing one, before any 403 or 409 (E10-S30)
            lambda: api.save_deck(self.body(profile, id="casual/gruul-test", sha256="0" * 64)),
            lambda: api.save_deck(self.body(profile, id="casual/gruul-test", sha256=deck_sha)),
        )
        names = mock.patch.object(lib_tokens, "check_names", lambda row: (row, []))   # no token names here
        with context, names:
            for i, call in enumerate(calls):
                with self.subTest(call=i), self.assertRaises(api.ApiError) as caught:
                    call()
                self.assertEqual((caught.exception.status, caught.exception.extra), (403, {}), i)
            for i, call in enumerate(decks):
                with self.subTest(deck_call=i), self.assertRaises(api.ApiError) as caught:
                    call()
                self.assertEqual((caught.exception.status, caught.exception.message, caught.exception.extra),
                                 (404, "No deck 'casual/gruul-test'", {}), i)
            self.assertApiError(403, api_tokens.tokens_view, "home")
        with access.using(None):
            self.assertEqual(api_tokens.tokens_view()["sha256"], sha)        # nothing was saved

    def test_a_write_names_the_same_profile_as_the_viewer_header(self):
        # The home page names its viewer in X-Deck-Lab-Viewer and the writer in the body: they must agree,
        # as a login and its body must through the tunnel. A script sending no header names itself.
        with access.using(None):
            with access.viewing("user1"):
                self.assertApiError(403, api.parse_list, self.body("matt", text="1 Opt"),
                                    contains="only make changes as yourself")
                with mock.patch.object(pool, "printing_counts", side_effect=lambda space="home": {}):
                    api.parse_list(self.body("user1", text="1 Llanowar Elves"))
            with mock.patch.object(pool, "printing_counts", side_effect=lambda space="home": {}):
                api.parse_list(self.body("matt", text="1 Llanowar Elves"))

    def test_me_says_which_spaces_it_sees(self):
        for who, seen in (("matt", ["home"]), ("user1", ["home"]), ("user2", ["user2"])):
            may = access.me({"profile": who, "email": "", "remote": True})["may"]
            self.assertEqual(may["see_inventory"], seen, who)
        self.assertIsNone(access.me(None)["may"]["see_inventory"])

    def test_the_rule(self):
        matt, user1 = {"id": "matt", "role": "admin", "space": "home"}, {"id": "user1", "role": "member"}
        user2 = {"id": "user2", "role": "member", "space": "user2"}
        for profile, local, home, user2s in ((matt, False, True, False), (matt, True, True, False),
                                               (user1, False, True, False),
                                               (user2, False, False, True), (user1, True, True, False),
                                               (user2, True, False, True), (None, True, True, True),
                                               (None, False, False, False)):
            self.assertEqual((permissions.sees_inventory(profile, "home", script=local),
                              permissions.sees_inventory(profile, "user2", script=local)),
                             (home, user2s), (profile, local))
