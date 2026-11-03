"""E5-S30's first slice: the Wishlist page's "short of this card" line (lib/api/wishlist_short.py).

A wished card is short in a deck when its Planned list is missing copies (pool.owned_vs_needed),
counted in the wishlist owner's own space only, for decks the owner may see, and only when the
owner may see that space's inventory; another space's decks are never named."""
import json
from types import SimpleNamespace
from unittest import mock

from decklab.lib import access, api, config, inventory, pool
from decklab.lib.api import guard, library, wishlist_short, wishlists
from decklab.lib.inventory.files import FileInventory
from decklab.tests.test_api import GRUUL, ApiTestCase, _write
from decklab.tests.test_collection_edit import ROLES

HEADER = "name,set,collector_number,finish,quantity,condition,language,notes\n"
RIDER = "Murderous Rider // Swift End"

RHYSTIC_DECK = """# {title}

- **Format:** Casual 60-card, 1v1
{played}- **Status:** idea

## Decklist

```
Deck
{qty} Rhystic Study (WOT) 25
4 Llanowar Elves (FDN) 227
```
"""


def deck(title, qty, played="- **Played by:** user\n"):
    return RHYSTIC_DECK.format(title=title, qty=qty, played=played)


def entry(name):
    return {"name": name, "set": "", "number": "", "notes": "", "source": ""}


class WishlistShortTests(ApiTestCase):

    def setUp(self):
        super().setUp()
        box = self.box
        _write(box.root / "config.json", json.dumps(ROLES))
        _write(box.magic / "people" / "user2" / "decks" / "casual" / "u2-rhystic.md",
               deck("User2 Rhystic", 3, played=""))
        _write(box.magic / "people" / "user2" / "collection.csv",
               HEADER + "Llanowar Elves,fdn,227,nonfoil,4,NM,en,\nRhystic Study,wot,25,nonfoil,1,NM,en,\n")
        # An unreadable deck leaves home's pool incomplete, which says nothing (see the incomplete test).
        (box.magic / "decks" / "casual" / "broken.md").unlink()
        # Gruul Test's Opt isn't in the fixture card index, and a deck with an unknown card isn't counted
        # (as Shopping skips it: see the unknown-cards test), so its line goes here.
        _write(box.magic / "decks" / "casual" / "gruul-test.md", GRUUL.replace("1 Opt (FDN) 512\n", ""))
        for target, name, value in ((config, "REPO", box.root), (config, "DATA", box.data)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(inventory.use(FileInventory(box.root)))

    def seed(self, profile, names):
        self.box.state.seed_wishlist(profile, [entry(name) for name in names])

    @staticmethod
    def get(profile):
        with access.viewing(profile):
            return api.get_wishlist(profile)

    @staticmethod
    def short(answer):
        return {e["name"]: e["short_in"] for e in answer["entries"]}

    def test_home_owner_sees_their_space_decks_short_of_each_card(self):
        # Gruul Test needs 6 Llanowar Elves: 5 owned, 2 held by the intact Beginner Box, so 3 short; it
        # lacks its Murderous Rider. Elf Commander lacks Ghalta. Sol Ring is on the way (the preordered
        # precon) for each deck counted on its own, so no deck is short of it; Black Lotus is owned.
        for owner in ("user1", "matt"):
            self.seed(owner, ["Llanowar Elves", RIDER, "Sol Ring", "Ghalta, Primal Hunger", "Black Lotus"])
            with self.subTest(owner=owner):
                short = self.short(self.get(owner))
                gruul = {"id": "casual/gruul-test", "title": "Gruul Test"}
                self.assertEqual(short["Llanowar Elves"], [dict(gruul, missing=3)])
                self.assertEqual(short[RIDER], [dict(gruul, missing=1)])
                self.assertEqual(short["Ghalta, Primal Hunger"],
                                 [{"id": "commander/elf-commander", "title": "Elf Commander", "missing": 1}])
                self.assertEqual(short["Sol Ring"], [])
                self.assertEqual(short["Black Lotus"], [])

    def test_several_decks_come_most_short_first_then_by_title(self):
        for slug, title, qty in (("zebra", "Zebra Rhystic", 4), ("beta", "Beta Rhystic", 1),
                                 ("alpha", "Alpha Rhystic", 1)):
            _write(self.box.magic / "decks" / "casual" / f"{slug}.md", deck(title, qty))
        self.seed("user1", ["Rhystic Study"])
        self.assertEqual([(d["id"], d["title"], d["missing"]) for d in self.short(self.get("user1"))["Rhystic Study"]],
                         [("casual/zebra", "Zebra Rhystic", 4), ("casual/alpha", "Alpha Rhystic", 1),
                          ("casual/beta", "Beta Rhystic", 1)])

    def test_a_member_sees_only_their_own_decks_and_home_never_sees_theirs(self):
        _write(self.box.magic / "decks" / "casual" / "home-rhystic.md", deck("Home Rhystic", 2))
        self.seed("user2", ["Rhystic Study", RIDER])
        self.seed("user1", ["Rhystic Study"])
        # User2 owns one Rhystic Study; their deck wants 3. Home's decks lack Rhystic Study and a
        # Murderous Rider too, and are never named to User2, even with home's decks Public.
        mine = self.get("user2")
        self.assertEqual(self.short(mine), {
            "Rhystic Study": [{"id": "user2/casual/u2-rhystic", "title": "User2 Rhystic", "missing": 2}],
            RIDER: []})
        with mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home", "user2"})):
            public = self.get("user2")
            home = self.get("user1")
        self.assertEqual(self.short(public), self.short(mine))
        self.assertEqual([d["id"] for d in self.short(home)["Rhystic Study"]], ["casual/home-rhystic"])
        for answer in (mine, public):
            self.assertNotIn("Home Rhystic", json.dumps(answer))
            self.assertNotIn("Gruul Test", json.dumps(answer))
        self.assertNotIn("User2 Rhystic", json.dumps(home))

    def test_nothing_is_said_without_the_space_inventory(self):
        self.seed("user1", [RIDER])
        with mock.patch.object(guard, "sees_inventory", return_value=False):
            answer = self.get("user1")
        self.assertIsNone(answer["entries"][0]["short_in"])
        self.assertNotIn("Gruul Test", json.dumps(answer))

    def test_only_the_owner_reads_it(self):
        self.seed("user1", [RIDER])
        for who in ("matt", "user2", None):
            with self.subTest(who=who), access.viewing(who):
                self.assertApiError(403, api.get_wishlist, "user1")

    def test_one_pool_load_per_request(self):
        self.seed("user1", [RIDER, "Llanowar Elves", "Ghalta, Primal Hunger"])
        with mock.patch.object(pool, "load_pool", side_effect=pool.load_pool) as loads:
            self.get("user1")
        self.assertEqual(loads.call_count, 1)

    def test_an_incomplete_pool_says_why_and_names_no_deck(self):
        self.seed("user1", [RIDER])
        real = library._load_pool

        def incomplete(warnings, space):
            found = real(warnings, space)
            found.warnings.append("Something in the pool needs fixing")
            return found
        with mock.patch.object(wishlists, "_load_pool", side_effect=incomplete):
            answer = self.get("user1")
        self.assertIsNone(answer["entries"][0]["short_in"])
        self.assertEqual(answer["short_warnings"], [wishlist_short.INCOMPLETE])
        self.assertNotIn(wishlist_short.INCOMPLETE, answer["warnings"])

    def test_unreadable_decks_keep_the_wishlist(self):
        self.seed("user1", [RIDER])
        with mock.patch.object(wishlist_short, "_own_decks", side_effect=OSError("disk C:/secret")):
            answer = self.get("user1")
        self.assertEqual(answer["entries"][0]["name"], RIDER)
        self.assertIsNone(answer["entries"][0]["short_in"])
        self.assertEqual(answer["short_warnings"], [wishlist_short.UNCOUNTED])
        self.assertNotIn(wishlist_short.UNCOUNTED, answer["warnings"])
        self.assertNotIn("secret", json.dumps(answer))
        # One deck that can't be counted leaves the others' lines, and a warning (naming no deck) says
        # the answer may be missing a deck: Elf Commander is in fact short of Ghalta.
        real = pool.owned_vs_needed

        def counted(deck_id, *args, **kwargs):
            if deck_id == "commander/elf-commander":
                raise OSError("unreadable")
            return real(deck_id, *args, **kwargs)
        self.seed("user1", [RIDER, "Ghalta, Primal Hunger"])
        with mock.patch.object(wishlist_short.pool, "owned_vs_needed", side_effect=counted):
            short = self.short(self.get("user1"))
        self.assertEqual([d["id"] for d in short[RIDER]], ["casual/gruul-test"])
        self.assertEqual(short["Ghalta, Primal Hunger"], [])
        with mock.patch.object(wishlist_short.pool, "owned_vs_needed", side_effect=counted):
            answer = self.get("user1")
        self.assertEqual(answer["short_warnings"], [wishlist_short.PARTIAL])
        self.assertNotIn("Elf Commander", json.dumps(answer))

    def test_a_deck_with_unknown_cards_is_skipped_and_said(self):
        # Shopping skips a deck whose own count is incomplete; so does the wishlist, saying so.
        self.seed("user1", [RIDER, "Ghalta, Primal Hunger"])
        real = pool.owned_vs_needed

        def unresolved(deck_id, *args, **kwargs):
            result = real(deck_id, *args, **kwargs)
            if deck_id == "commander/elf-commander":
                result = dict(result, unresolved=[("Not A Card", deck_id)])
            return result
        with mock.patch.object(wishlist_short.pool, "owned_vs_needed", side_effect=unresolved):
            answer = self.get("user1")
        short = self.short(answer)
        self.assertEqual([d["id"] for d in short[RIDER]], ["casual/gruul-test"])
        self.assertEqual(short["Ghalta, Primal Hunger"], [])
        self.assertEqual(answer["short_warnings"], [wishlist_short.PARTIAL])
        self.assertNotIn("Not A Card", json.dumps(answer))

    def test_an_unreadable_own_deck_is_said_but_another_space_is_not(self):
        self.seed("user1", [RIDER])
        self.seed("user2", ["Rhystic Study"])
        real = wishlist_short.decks

        def listing(*extra):
            # Only the wishlist's listing has them (the pool's own would call itself incomplete).
            return SimpleNamespace(list_decks=lambda: [*real.list_decks(), *extra], KINDS=real.KINDS)
        home_error = {"id": "casual/unreadable", "title": "Unreadable", "error": "bad text"}
        with mock.patch.object(wishlist_short, "decks", listing(home_error)):
            answer = self.get("user1")
            theirs = self.get("user2")
        self.assertEqual(answer["short_warnings"], [wishlist_short.PARTIAL])
        self.assertEqual([d["id"] for d in self.short(answer)[RIDER]], ["casual/gruul-test"])
        self.assertNotIn("Unreadable", json.dumps(answer))
        # Another space's unreadable deck is neither counted nor hinted at; one's own is said.
        self.assertEqual(theirs["short_warnings"], [])
        self.assertEqual(len(self.short(theirs)["Rhystic Study"]), 1)
        mine = {"id": "user2/casual/theirs", "space": "user2", "title": "Theirs", "error": "bad text"}
        with mock.patch.object(wishlist_short, "decks", listing(mine)):
            self.assertEqual(self.get("user2")["short_warnings"], [wishlist_short.PARTIAL])

    def test_a_complete_count_has_no_short_warnings(self):
        self.seed("user1", [RIDER])
        answer = self.get("user1")
        self.assertEqual(answer["short_warnings"], [])

    def test_offline_cards_say_nothing(self):
        self.seed("user1", [RIDER])
        with self.box.no_index():
            self.assertIsNone(self.get("user1")["entries"][0]["short_in"])

    def test_a_change_answers_with_the_lines_too(self):
        body = json.dumps({"profile": "user1", "action": "add", "name": "Ghalta, Primal Hunger"}).encode()
        with access.viewing("user1"):
            answer = api.change_wishlist("user1", body)
        self.assertEqual(answer["entries"][0]["short_in"],
                         [{"id": "commander/elf-commander", "title": "Elf Commander", "missing": 1}])
