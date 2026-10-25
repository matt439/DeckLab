"""Explicit CLI attribution (E11-S07), with isolated files and a throwaway database.

The files cases run the commands' real operations and inspect the actor passed to apply.
The database case verifies the resulting audit identity and Activity's wishlist privacy.
"""
import argparse
import contextlib
import io
import json
import unittest
from unittest import mock

from decklab.db import __main__ as cli, cli_actor
from decklab.lib import access, config, inventory, profiles, state
from decklab.lib.api import activity
from decklab.lib.inventory.files import FileInventory
from decklab.tests import test_pool, test_wishlist_db
from decklab.tests.test_api import ApiTestCase


PROFILES = [
    {"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin", "space": "home"},
    {"id": "user1", "name": "User1", "plays_as": "wife", "role": "member", "space": "home"},
]
CARD_HEADER = "name,set,collector_number,finish,quantity,condition,language,notes\n"
CARD = "Llanowar Elves,fdn,227,nonfoil,1,,,\n"


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main([str(a) for a in argv])
    return code, out.getvalue(), err.getvalue()


# Every user-facing audited leaf, including the commands whose writes are optional.
WRITES = [
    ("collection", "merge", "cards.csv", "-m", "Import"),
    ("tokens", "add", "--front", "Fish", "--quantity", "1", "-m", "Add"),
    ("tokens", "edit", "1", "--expect", "a" * 12, "-m", "Edit"),
    ("tokens", "remove", "1", "--expect", "a" * 12, "-m", "Remove", "--reason", "Gone"),
    ("order", "add", "--id", "2026-10-15-test", "--cards", "cards.csv", "-m", "Order"),
    ("order", "edit", "test", "cards", "--csv", "cards.csv", "-m", "Edit"),
    ("order", "checks", "test", "cards", "--add", "Check", "-m", "Check"),
    ("order", "split", "test", "cards", "--new-id", "later", "--take", "1", "-m", "Split"),
    ("order", "cancel", "test", "cards", "-m", "Cancel", "--reason", "Gone"),
    ("order", "extra-copies", "test", "cards", "-m", "Extra"),
    ("product", "add", "test", "--order", "test", "--csv", "cards.csv", "-m", "Add"),
    ("product", "set-intact", "test", "no", "-m", "Break up"),
    ("watchlist", "set", "--add", "--name", "Opt", "--state", "ready", "-m", "Add"),
    ("watchlist", "remove", "Opt", "-m", "Remove", "--reason", "Gone"),
    ("watchlist", "apply", "--csv", "queue.csv", "-m", "Update"),
    ("receive", "--order", "test", "--date", "2026-10-15", "--apply"),
    ("deck", "push", "casual/test", "deck.md", "--expect", "1", "-m", "Save"),
    ("deck", "new", "casual", "test", "--from", "deck.md", "-m", "Create"),
    ("deck", "delete", "casual/test", "--expect", "1", "-m", "Remove", "--reason", "Gone"),
    ("deck", "tables", "--apply"),
    ("accessories", "add", "--kind", "playmat", "--name", "Mat", "--expect", "none", "-m", "Add"),
    ("accessories", "edit", "mat", "--expect", "a" * 12, "-m", "Edit"),
    ("accessories", "remove", "mat", "--expect", "a" * 12, "-m", "Remove", "--reason", "Gone"),
    ("image", "put", "mat.png", "mat.png", "-m", "Picture"),
    ("image", "remove", "mat.png", "-m", "Remove"),
    ("wishlist", "add", "matt", "Opt", "-m", "Add"),
    ("wishlist", "set", "matt", "Opt", "--notes", "Nice", "-m", "Edit"),
    ("wishlist", "remove", "matt", "Opt", "-m", "Remove", "--reason", "Gone"),
]


class ResolverTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(config, "load", return_value={"profiles": PROFILES})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_omitted_actor_stays_claude_without_needing_the_config(self):
        with mock.patch.object(profiles, "read", side_effect=OSError("missing config")):
            for args in (argparse.Namespace(), argparse.Namespace(actor=None)):
                self.assertEqual(cli_actor.resolve(args), state.Actor("claude", "Claude", None, "cli"))

    def test_known_profile_uses_its_configured_name_and_cli_source(self):
        for profile in PROFILES:
            with self.subTest(profile=profile["id"]):
                self.assertEqual(cli_actor.resolve(argparse.Namespace(actor=profile["id"])),
                                 state.Actor(profile["id"], profile["name"], None, "cli"))

    def test_unknown_malformed_and_reserved_actors_are_refused(self):
        for actor in ("nobody", "", "Matt", " matt ", "../matt", "claude", "system", "test", "home"):
            with self.subTest(actor=actor), self.assertRaises(ValueError):
                cli_actor.resolve(argparse.Namespace(actor=actor))

    def test_every_audited_leaf_accepts_an_actor_and_defaults_to_none(self):
        parser = cli.parser()
        for argv in WRITES:
            with self.subTest(command=argv[:2]):
                self.assertIsNone(parser.parse_args(argv).actor)
                self.assertEqual(parser.parse_args([*argv, "--actor", "matt"]).actor, "matt")


class CommandTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        # A minimal second tree avoids the Sandbox's intentionally broken deck and pool.
        self.root = self.box.root / "cli-actors"
        self.magic = self.root / "magic"
        (self.magic / "products").mkdir(parents=True)
        self.file("magic/collection.csv", CARD_HEADER)
        self.file("magic/products/status.csv", "file,status,intact,sleeves,deck_box,notes\n")
        self.addCleanup(inventory.use(FileInventory(self.root)))

    def file(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return path

    def succeed(self, *argv):
        code, out, err = run_cli(*argv, "--actor", "matt")
        self.assertEqual(code, 0, f"{argv}: {err}\n{out}")
        return out

    def test_real_operations_forward_the_actor_for_every_inventory_command_family(self):
        cards = self.file("cards.csv", CARD_HEADER + CARD)
        product = self.file("product.csv", "deck,name,set,collector_number,finish,quantity\n"
                            "Elves,Elvish Mystic,cmm,648,nonfoil,1\n")
        deck = self.file("deck.md", test_pool.deck_md("Actor test", "idea", "Deck\n4 Llanowar Elves\n56 Forest\n",
                         table="| Llanowar Elves | 4 | 0 | **4** | | | |\n| **Total** | | | **4** | | | |\n"))
        picture = self.file("mat.png", b"\x89PNG\r\n\x1a\n" + bytes(16))
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            self.succeed("watchlist", "set", "--add", "--name", "Opt", "--state", "ready", "-m", "Plan")
            self.succeed("order", "add", "--id", "2026-10-15-actor-test", "--cards", cards, "-m", "Order")
            self.succeed("product", "add", "actor-product", "--order", "2026-10-15-actor-test", "--csv", product,
                         "-m", "Add product")
            self.succeed("receive", "--order", "2026-10-15-actor-test", "--date", "2026-10-15", "--apply",
                         "--intact", "no")
            self.succeed("tokens", "add", "--front", "Llanowar Elves", "--quantity", "1", "--notes", "single-sided verified",
                         "-m", "Add token")
            self.succeed("accessories", "add", "--kind", "playmat", "--name", "Mat", "--expect", "none", "-m", "Mat")
            self.succeed("image", "put", "mat.png", picture, "-m", "Picture")
            self.succeed("deck", "new", "casual", "actor-test", "--from", deck, "-m", "Build")
            self.succeed("collection", "merge", cards, "-m", "Trade")
            self.succeed("deck", "tables", "--apply", "-m", "Refresh")
        calls = apply.call_args_list
        self.assertEqual([call.args[0].kind for call in calls], [
            "watchlist.set", "order.add", "product.add", "receipt.receive", "tokens.add", "accessory.add",
            "image.put", "deck.create", "collection.import", "deck.update_tables"])
        self.assertTrue(all(call.args[1] == state.Actor("matt", "Matt", None, "cli") for call in calls))

    def test_unknown_actor_is_refused_without_an_audited_write(self):
        from decklab.lib.state import pg
        for argv in WRITES:
            with self.subTest(command=argv[:2]), mock.patch.object(inventory, "apply") as apply, \
                    mock.patch.object(pg.PgStore, "wishlist_add") as add, \
                    mock.patch.object(pg.PgStore, "wishlist_set") as edit, \
                    mock.patch.object(pg.PgStore, "wishlist_remove") as remove:
                code, _, err = run_cli(*argv, "--actor", "nobody")
                self.assertEqual(code, 1, err)
                self.assertIn("nobody", err)
                for write in (apply, add, edit, remove):
                    write.assert_not_called()


class AuditTests(test_wishlist_db.WishlistDbTestCase):
    def setUp(self):
        super().setUp()
        # Explicit roles: User1 is a member, so CLI messages need her own actor.
        (self.box.root / "config.json").write_text(json.dumps({"profiles": PROFILES}), encoding="utf-8")

    def test_profile_and_default_actors_reach_the_audit_trail_and_preserve_wishlist_privacy(self):
        commands = [
            ("add", "matt", "Llanowar Elves", "--actor", "matt", "-m", "Matt's private choice"),
            ("add", "user1", "Elvish Mystic", "-m", "User1's private choice"),
            ("set", "user1", "Elvish Mystic", "--notes", "User1's notes", "--actor", "user1",
             "-m", "User1's own change"),
        ]
        for argv in commands:
            code, _, err = run_cli("wishlist", *argv, "--dbname", self.dbname)
            self.assertEqual(code, 0, err)
        self.assertEqual(self.trail(), [
            ("matt", "cli", None, "Matt's private choice", None),
            ("claude", "cli", None, "User1's private choice", None),
            ("user1", "cli", None, "User1's own change", None)])
        with access.viewing("matt"):
            matt = activity.activity_view()["changes"]
        with access.viewing("user1"):
            user1 = activity.activity_view()["changes"]
        with access.viewing(None):
            anonymous = activity.activity_view()["changes"]
        self.assertEqual([(c["actor_name"], c["source"], c["via"], c["message"]) for c in matt],
                         [("Matt", "cli", None, "Matt's private choice")])
        self.assertEqual([(c["actor_name"], c["message"]) for c in user1],
                         [("User1", "User1's own change"), ("Claude", None)])
        self.assertEqual(anonymous, [])
        before = self.trail()
        code, _, err = run_cli("wishlist", "add", "matt", "Opt", "--actor", "nobody", "-m", "Rejected",
                              "--dbname", self.dbname)
        self.assertEqual(code, 1, err)
        self.assertEqual(self.trail(), before)
