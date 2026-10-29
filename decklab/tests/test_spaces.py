"""Tests for decklab.lib.profiles and decklab.lib.spaces, and for person spaces
in decks, pool and tokens (lib/spaces.py: a person's collection, tokens and
decks under magic/people/<id>/).

Each test builds a small magic/ tree in a temp folder with a config.json that
lists one person space (user2) and points decks, pool and tokens at it.
Names resolve against the fixture card index (fixtures/default_cards.jsonl).

Run from the repo root: python scripts/test_fixtures.py
"""
import json
import unittest
from unittest import mock

from decklab.lib import config, decks, pool, profiles, spaces, tokens
from decklab.tests import deck_files, test_pool
from decklab.tests.test_pool import deck_md

PROFILES = [
    {"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin", "space": "home",
     "emails": ["Matt@Example.com", " matt@example.com "]},
    {"id": "user1", "name": "User1", "plays_as": "wife", "role": "member", "space": "home",
     "emails": ["user1@example.com"]},
    {"id": "user2", "name": "User2", "role": "member", "space": "user2",
     "emails": ["user2@example.com"]},
]

TOKEN_HEADER = ",".join(tokens.FIELDS) + "\n"


def setUpModule():
    test_pool.setUpModule()


def tearDownModule():
    test_pool.tearDownModule()


class ProfilesTests(unittest.TestCase):

    def test_roles_spaces_and_emails(self):
        got = profiles.parse(PROFILES)
        self.assertEqual([(p["id"], p["role"], p["space"], p["plays_as"]) for p in got],
                         [("matt", "admin", "home", "user"), ("user1", "member", "home", "wife"),
                          ("user2", "member", "user2", None)])
        self.assertEqual(got[0]["emails"], ["matt@example.com"])           # lowercased, trimmed, once
        self.assertNotIn("emails", profiles.public(got[0]))
        self.assertEqual(profiles.for_email("USER2@example.com", got)["id"], "user2")
        self.assertIsNone(profiles.for_email("nobody@example.com", got))

    def test_a_config_without_roles_makes_everyone_admin(self):
        got = profiles.parse([{"id": "matt", "name": "Matt", "plays_as": "user"},
                              {"id": "user1", "name": "User1", "plays_as": "wife"}])
        self.assertEqual([(p["role"], p["space"], p["emails"]) for p in got],
                         [("admin", "home", []), ("admin", "home", [])])

    def test_with_an_access_block_missing_roles_mean_member(self):
        listed = [{"id": "matt", "name": "Matt", "plays_as": "user"},
                  {"id": "user1", "name": "User1", "plays_as": "wife"}]
        self.assertTrue(profiles.legacy(listed))
        self.assertEqual([p["role"] for p in profiles.parse(listed, access=True)], ["member", "member"])
        self.assertEqual([p["role"] for p in profiles.read({"profiles": listed, "access": {"team": "t"}})],
                         ["member", "member"])
        self.assertEqual([p["role"] for p in profiles.read({"profiles": listed})], ["admin", "admin"])
        self.assertFalse(profiles.legacy([{**listed[0], "role": "admin"}, listed[1]]))

    def test_emails_are_ascii_only(self):
        got = profiles.parse([{"id": "a", "name": "A", "plays_as": "user", "role": "admin",
                               "emails": ["kim@example.com", "josé@example.com"]}])
        self.assertEqual(got[0]["emails"], ["kim@example.com"])
        self.assertEqual(profiles.for_email("KIM@Example.COM", got)["id"], "a")
        # The Kelvin sign lowercases to "k" under Unicode rules: never matched.
        self.assertIsNone(profiles.for_email("Kim@example.com", got))
        self.assertIsNone(profiles.for_email("josé@example.com", got))
        self.assertIsNone(profiles.email_key("josÉ@example.com"))
        self.assertEqual(profiles.email_key(" A@B.c "), "a@b.c")

    def test_once_roles_exist_a_missing_or_bad_one_is_member(self):
        got = profiles.parse([{"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin"},
                              {"id": "user1", "name": "User1", "plays_as": "wife"},
                              {"id": "guest", "name": "Guest", "plays_as": "user", "role": "admim"}])
        self.assertEqual([p["role"] for p in got], ["admin", "member", "member"])

    def test_unusable_entries_are_skipped(self):
        got = profiles.parse([
            {"id": "a", "name": "A", "plays_as": "nobody"},                  # home needs plays_as
            {"id": "b", "name": "B", "space": "someone-else"},               # a space must be its own id
            {"id": "product", "name": "P", "space": "product"},             # reserved space id
            {"id": "../x", "name": "X", "plays_as": "user"},                # bad id
            {"id": "c", "name": "C", "space": "c", "plays_as": "user"},     # plays_as ignored in a person space
            {"id": "c", "name": "C again", "space": "c"},                   # repeated
            "not a profile"])
        self.assertEqual([(p["id"], p["plays_as"]) for p in got], [("c", None)])

    def test_the_same_email_on_two_profiles_matches_neither(self):
        got = profiles.parse([{"id": "a", "name": "A", "plays_as": "user", "emails": ["x@example.com"]},
                              {"id": "b", "name": "B", "plays_as": "wife", "emails": ["X@example.com"]}])
        self.assertIsNone(profiles.for_email("x@example.com", got))


class DeckIdTests(unittest.TestCase):

    def test_split_and_join(self):
        cases = {"casual/gruul": ("home", "casual", "gruul"),
                 "commander/x": ("home", "commander", "x"),
                 "product/fdn-beginner-box/cats": ("home", "product", "fdn-beginner-box/cats"),
                 "pairing/cats+elves": ("home", "pairing", "cats+elves"),
                 "user2/casual/elves": ("user2", "casual", "elves"),
                 "user2/commander/ghalta": ("user2", "commander", "ghalta")}
        for deck_id, parts in cases.items():
            with self.subTest(deck_id=deck_id):
                self.assertEqual(spaces.split_deck_id(deck_id), parts)
                if parts[1] in decks.KINDS:
                    self.assertEqual(spaces.join_deck_id(*parts), deck_id)

    def test_bad_ids(self):
        for deck_id in ("casual", "user2/casual", "user2/product/x", "user2/casual/a/b", "home/casual/x",
                        "User2/casual/x", "../casual/x", "", None, "file:x.dck"):
            with self.subTest(deck_id=deck_id):
                with self.assertRaises(ValueError):
                    spaces.split_deck_id(deck_id)
        self.assertEqual(spaces.space_of("nonsense"), "home")


class SpaceTestCase(test_pool.PoolTestCase):
    """test_pool's temp magic/ tree (the installed inventory), plus a config.json listing User2's space
    and no token orders."""

    def setUp(self):
        super().setUp()
        root = self.magic.parent
        (root / "config.json").write_text(json.dumps({"profiles": PROFILES}), encoding="utf-8")
        for target, name, value in ((config, "CONFIG_FILE", root / "config.json"),
                                    (tokens, "incoming", lambda: ([], []))):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.people = self.magic / "people" / "user2"

    def person_deck(self, slug, *args, kind="casual", **kwargs):
        path = self.people / "decks" / kind / f"{slug}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(deck_md(*args, **kwargs).replace("- **Played by:** either\n", ""), encoding="utf-8",
                        newline="\n")
        return path


class SpacesTests(SpaceTestCase):

    def test_the_spaces_and_their_paths(self):
        self.assertEqual(spaces.space_ids(), ["home", "user2"])
        home = spaces.get("home")
        self.assertEqual((home.root, home.decks), (self.magic, decks.DECKS_DIR))
        user2 = spaces.get("user2")
        self.assertEqual((user2.name, user2.owner), ("User2", "user2"))
        self.assertEqual(user2.root, self.people)
        self.assertEqual(user2.deck_dir("commander"), self.people / "decks" / "commander")
        self.assertFalse(self.people.exists())          # nothing is made in advance
        with self.assertRaises(spaces.SpaceNotFound):
            spaces.get("user1")                         # a home profile has no space of its own
        self.assertEqual(spaces.space_ids([]), ["home"])

    def test_an_unreadable_config_leaves_only_home(self):
        config.CONFIG_FILE.write_text("{not json", encoding="utf-8")
        self.assertEqual(spaces.space_ids(), ["home"])
        self.assertEqual(decks.deck_files(), [])


class PersonDeckTests(SpaceTestCase):

    def test_the_library_lists_person_decks_with_their_space(self):
        self.deck("home-deck", "Home Deck", "idea", "Deck\n4 Llanowar Elves\n")
        self.person_deck("elves", "User2's Elves", "built", "Deck\n4 Llanowar Elves\n")
        summaries = {s["id"]: s for s in decks.list_decks()}
        self.assertEqual(summaries["casual/home-deck"]["space"], "home")
        user2 = summaries["user2/casual/elves"]
        self.assertEqual((user2["space"], user2["title"], user2["player"], user2["status"]),
                         ("user2", "User2's Elves", None, "built"))
        self.assertEqual(user2["source"], "user2/casual/elves")      # messages name it by its id
        self.assertEqual(decks.load_deck("user2/casual/elves")["Deck"][0].name, "Llanowar Elves")
        self.assertEqual(decks.find_summary("user2/casual/elves")["title"], "User2's Elves")
        with self.assertRaises(decks.DeckNotFound):
            decks.load_deck("user3/casual/elves")      # no such space
        with self.assertRaises(decks.DeckNotFound):
            decks.load_deck("user2/casual/missing")

    def test_paths_ids_and_writing(self):
        path = decks.deck_path("casual", "goblins", "user2")
        self.assertEqual(path, self.people / "decks" / "casual" / "goblins.md")
        self.assertEqual(decks.path_for_id("user2/casual/goblins"), path)
        self.assertEqual(decks.path_for_id("casual/goblins"), self.magic / "decks" / "casual" / "goblins.md")
        with self.assertRaises(ValueError):
            decks.deck_path("casual", "goblins", "user3")
        with self.assertRaises(ValueError):
            decks.path_for_id("product/fdn-beginner-box")
        # The first deck makes the folders; the file then has its id and space.
        deck_files.write_deck_file(path, deck_md("Goblins", "idea", "Deck\n1 Aerie Mystics\n"), None)
        self.assertEqual(decks.deck_id_of(path), "user2/casual/goblins")
        deck = decks.read_deck_file(path)
        self.assertEqual((deck.space, deck.deck_id), ("user2", "user2/casual/goblins"))
        self.assertEqual(decks.existing_deck_id("GOBLINS", "user2"), "user2/casual/goblins")
        self.assertIsNone(decks.existing_deck_id("goblins"))            # not a home deck
        with self.assertRaises(ValueError):
            deck_files.write_deck_file(self.people / "elsewhere.md", "x", None)

    def test_deck_files_round_trip_without_played_by(self):
        path = self.person_deck("elves", "User2's Elves", "idea", "Deck\n4 Llanowar Elves\n")
        deck = decks.read_deck_file(path)
        self.assertIsNone(deck.player)
        self.assertEqual(decks.render_deck_file(deck), path.read_text(encoding="utf-8"))


class PersonPoolTests(SpaceTestCase):

    def test_a_person_deck_counts_their_collection_and_built_decks_only(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4))
        self.cards_csv("orders/2026-10-01-x.csv", ("Elvish Mystic", "cmm", "648", "nonfoil", 2))
        self.deck("home-built", "Home Built", "built", "Deck\n4 Llanowar Elves\n")
        self.people.mkdir(parents=True)
        test_pool.PoolTestCase.cards_csv(self, "people/user2/collection.csv",
                                         ("Llanowar Elves", "fdn", "227", "nonfoil", 3),
                                         ("Elvish Mystic", "cmm", "648", "nonfoil", 1))
        self.person_deck("built", "User2 Built", "built", "Deck\n2 Llanowar Elves\n")
        self.person_deck("elves", "User2's Elves", "idea", "Deck\n4 Llanowar Elves\n2 Elvish Mystic\n")
        p = pool.load_pool("user2")
        self.assertEqual((p.space, dict(p.owned), p.on_the_way),
                         ("user2", {"Llanowar Elves": 3, "Elvish Mystic": 1}, {}))
        self.assertEqual([d.id for d in p.in_use], ["user2/casual/built"])
        result, rows = self.check("user2/casual/elves")
        self.assertEqual((rows["Llanowar Elves"]["available"], rows["Llanowar Elves"]["missing"]), (1, 3))
        self.assertEqual(rows["Llanowar Elves"]["in_use_elsewhere"], [("User2 Built", 2)])
        self.assertEqual((rows["Elvish Mystic"]["on_the_way"], rows["Elvish Mystic"]["missing"]), (0, 1))
        # The home pool doesn't see User2's decks; a home pool passed in is replaced.
        home = pool.load_pool()
        self.assertEqual([d.id for d in home.in_use], ["casual/home-built"])
        self.assertEqual(pool.owned_vs_needed("user2/casual/elves", pool=home, prices=False)["rows"],
                         result["rows"])
        self.assertIs(pool.for_space("home", home), home)

    def test_no_collection_yet_owns_nothing(self):
        self.person_deck("elves", "User2's Elves", "idea", "Deck\n4 Llanowar Elves\n")
        result, rows = self.check("user2/casual/elves")
        self.assertEqual((rows["Llanowar Elves"]["owned"], rows["Llanowar Elves"]["missing"]), (0, 4))
        self.assertEqual(result["warnings"], [])
        self.assertEqual(pool.printing_counts("user2"), {})
        with self.assertRaises(spaces.SpaceNotFound):
            pool.load_pool("user3")

    def test_tables_and_stale_tables_use_each_space(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4))
        path = self.person_deck("elves", "User2's Elves", "idea", "Deck\n4 Llanowar Elves\n",
                                table="| Llanowar Elves | 4 | 4 | 0 | | | |\n")
        deck = decks.read_deck_file(path)
        rows, _, _ = pool.deck_table(deck, pool.load_pool(), prices=False)
        self.assertEqual([(r.card, r.owned, r.missing) for r in rows], [("Llanowar Elves", 0, 4)])
        self.assertEqual([s["id"] for s in pool.stale_tables(pool.load_pool())], ["user2/casual/elves"])

    def test_the_command_line_takes_person_ids(self):
        self.person_deck("elves", "User2's Elves", "idea", "Deck\n4 Llanowar Elves\n")
        code, out, _ = test_pool.CommandLineTests.run_main(self, "user2/casual/elves", "--no-prices")
        self.assertEqual(code, 0)
        self.assertIn("user2/casual/elves (target list)", out)
        self.assertIn("4 missing", out)


class PersonTokenTests(SpaceTestCase):

    def test_each_space_reads_its_own_tokens(self):
        (self.magic / "tokens.csv").write_text(TOKEN_HEADER + "Goblin,,,,,,2,,,single-sided verified\n",
                                               encoding="utf-8")
        self.people.mkdir(parents=True)
        (self.people / "tokens.csv").write_text(TOKEN_HEADER + "Elf Warrior,,,,,,1,,,single-sided verified\n",
                                                encoding="utf-8")
        self.assertEqual([r["front"] for r in tokens.read().rows], ["Goblin"])
        self.assertEqual([r["front"] for r in tokens.read(space="user2").rows], ["Elf Warrior"])
        inv, inc, problems = tokens.for_space("user2")
        self.assertEqual(([r["front"] for r in inv.rows], inc, problems), (["Elf Warrior"], [], []))
        self.assertEqual(tokens.label_for("user2"), "user2's token cards")
        with self.assertRaises(spaces.SpaceNotFound):
            tokens.read(space="user3")

    def test_a_missing_person_file_is_empty_and_problems_name_it(self):
        self.assertEqual(tokens.read(space="user2").rows, [])
        self.people.mkdir(parents=True)
        (self.people / "tokens.csv").write_text("front,back\n", encoding="utf-8")
        self.assertIn("User2's token cards' columns must be", tokens.read(space="user2").problems[0])
        self.assertTrue(any("User2's token cards" in p for p in tokens.check(space="user2")))
        self.assertFalse(any("magic/" in p for p in tokens.check(space="user2")))

    def test_holders_stay_in_their_space(self):
        self.deck("home-built", "Home Built", "built", "Deck\n4 Llanowar Elves\n")
        self.person_deck("built", "User2 Built", "built", "Deck\n2 Llanowar Elves\n")
        self.assertEqual([h[0] for h in tokens.holders([])], ["casual/home-built"])
        self.assertEqual([h[0] for h in tokens.holders([], space="user2")], ["user2/casual/built"])


if __name__ == "__main__":
    unittest.main()
