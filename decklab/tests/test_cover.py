"""A deck's cover card (lib/decks/cover.py, lib/api/library.py's shelf extras, POST /api/deck/cover in
lib/api/cover.py) and the card images the library and card viewer use (large, art_crop).

- The "Cover card" header line: parsed and written, kept byte for byte by every other save, rewritten
  only by set_cover (and so by the cover route).
- The automatic cover: the commander, else the most-copied non-land of the Planned list (on a tie a
  creature, then the first).
- GET /api/deck/cards: the picture picker's light read (each card once, its shown printing, the
  automatic cover).
- GET /api/decks and GET /api/deck carry cover, colors and revision (and the library "edited").
- POST /api/deck/cover: one deck.save (one change), the deck.edit permission a save of the text needs,
  409 for a stale expect, 400 for a card that isn't Scryfall's or a printing of another card, and
  person-space decks allowed. The database tests check its one revision and one change set.
- GET /img/: Scryfall's 404 is a 404 and its other errors a 503, never the PC's 500.

Each API test runs in test_api's Sandbox (its files backend, the fixture card index).

Run from the repo root: python -m unittest decklab.tests.test_cover
"""
import unittest
import urllib.error
from unittest import mock

from decklab.lib import api, cards, decks, inventory
from decklab.lib.api import card_lookup, cover as api_cover, library as api_library
from decklab.tests import db_support
from decklab.tests.test_api import ApiTestCase, _write
from decklab.tests.test_api_permissions import PermissionTestCase
from decklab.tests.test_editor import TABLE_DECK, EditorTestCase

DECK = TABLE_DECK.replace("- **Status:** building\n", "- **Status:** building\n- **Cover card:** Elvish Mystic\n")


def parsed(text, slug="table-test", kind="casual"):
    return decks.parse_deck(text.encode("utf-8"), slug, kind)


class CoverLineTests(unittest.TestCase):

    def test_parse_and_format(self):
        self.assertEqual(decks.parse_cover("Llanowar Elves (FDN) 227"),
                         {"name": "Llanowar Elves", "set": "fdn", "number": "227"})
        self.assertEqual(decks.parse_cover("  Fire // Ice  "), {"name": "Fire // Ice", "set": None, "number": None})
        self.assertEqual(decks.parse_cover("Hazmat Suit (Used)"),        # a name ending in brackets stays a name
                         {"name": "Hazmat Suit (Used)", "set": None, "number": None})
        for bad in ("", "   ", None, "Llanowar Elves (FDN)", "Llanowar Elves (FDN) 227 *F*", "Opt (FDN) 512 extra"):
            self.assertIsNone(decks.parse_cover(bad), bad)
        self.assertEqual(decks.format_cover("Llanowar Elves", "fdn", "227"), "Llanowar Elves (FDN) 227")
        self.assertEqual(decks.format_cover("Llanowar Elves"), "Llanowar Elves")
        for args in (("",), ("A\nB",), ("Opt", "fdn", None), ("Opt (FDN) 512",)):
            with self.assertRaises(ValueError, msg=args):
                decks.format_cover(*args)

    def test_an_untouched_line_is_kept_byte_for_byte(self):
        for text in (DECK, DECK.replace("\n", "\r\n"),
                     DECK.replace("- **Cover card:** Elvish Mystic", "- **Cover card**:   Elvish  Mystic (CMM) 648 ")):
            deck = parsed(text)
            self.assertEqual(decks.render_deck_file(deck), text)
            # A save of other fields leaves it as written: Deck Lab doesn't own it.
            decks.set_status(deck, "built")
            out = decks.render_deck_file(deck)
            self.assertEqual(out, text.replace("- **Status:** building", "- **Status:** built"))
            # set_cover to what it already says changes nothing either.
            again = parsed(text)
            decks.set_cover(again, decks.cover_field(again))
            self.assertEqual(decks.render_deck_file(again), text)

    def test_set_cover_rewrites_only_its_line(self):
        deck = parsed(TABLE_DECK)
        self.assertIsNone(decks.cover_field(deck))
        decks.set_cover(deck, {"name": "Llanowar Elves", "set": "fdn", "number": "227"})
        out = decks.render_deck_file(deck)
        self.assertEqual(out, TABLE_DECK.replace("- **Status:** building\n",
                                                 "- **Status:** building\n- **Cover card:** Llanowar Elves (FDN) 227\n"))
        # Rewritten in place, then removed.
        deck = parsed(out)
        decks.set_cover(deck, {"name": "Black Lotus"})
        out2 = decks.render_deck_file(deck)
        self.assertEqual(out2, out.replace("Cover card:** Llanowar Elves (FDN) 227", "Cover card:** Black Lotus"))
        deck = parsed(out2)
        decks.set_cover(deck, None)
        self.assertEqual(decks.render_deck_file(deck), TABLE_DECK)
        # CRLF files keep their line endings, and a cover line in the middle of the header stays there.
        crlf = DECK.replace("- **Status:** building\n- **Cover card:** Elvish Mystic\n",
                            "- **Cover card:** Elvish Mystic\n- **Status:** building\n").replace("\n", "\r\n")
        deck = parsed(crlf)
        decks.set_cover(deck, {"name": "Sol Ring", "set": "ecc", "number": "57"})
        self.assertEqual(decks.render_deck_file(deck), crlf.replace("Cover card:** Elvish Mystic", "Cover card:** Sol Ring (ECC) 57"))
        # A deck with no header gets one.
        bare = "# Bare\n\n## Decklist\n\n```\nDeck\n1 Opt\n```\n"
        deck = parsed(bare, "bare")
        decks.set_cover(deck, {"name": "Opt"})
        self.assertEqual(decks.render_deck_file(deck), "# Bare\n\n- **Cover card:** Opt\n\n## Decklist\n\n```\nDeck\n1 Opt\n```\n")

    def test_the_automatic_cover(self):
        lands = {"Forest", "Llanowar Wastes"}
        line = lambda n, name, s=None, c=None: decks.DeckLine(n, name, s, c)
        auto = lambda sections: decks.auto_cover_line(sections, lambda name: name in lands)
        # The commander first, whatever else has more copies.
        self.assertEqual(auto({"Commander": [line(1, "Ghalta")], "Deck": [line(30, "Forest"), line(4, "Opt")]}).name,
                         "Ghalta")
        # Else the most copies of a non-land, counted over printings; the first in list order on a tie.
        got = auto({"Deck": [line(2, "Opt", "fdn", "512"), line(20, "Forest"), line(3, "Shock"), line(2, "Opt", "m19", "1"),
                             line(4, "Llanowar Wastes")], "Sideboard": [line(10, "Duress")]})
        self.assertEqual((got.name, got.set), ("Opt", "fdn"))
        self.assertEqual(auto({"Deck": [line(3, "Shock"), line(3, "Opt")]}).name, "Shock")
        # On a tie a creature beats a spell, then list order: a deck of singles shows its first creature.
        creatures = {"Llanowar Elves", "Elvish Mystic"}
        pick = lambda sections: decks.auto_cover_line(sections, lambda name: name in lands, lambda name: name in creatures)
        self.assertEqual(pick({"Deck": [line(1, "Shock"), line(1, "Opt"), line(1, "Llanowar Elves"), line(1, "Elvish Mystic")]}).name,
                         "Llanowar Elves")
        self.assertEqual(pick({"Deck": [line(1, "Llanowar Elves"), line(4, "Opt")]}).name, "Opt")    # more copies still win
        # Only lands: the first card; nothing at all: None.
        self.assertEqual(auto({"Deck": [line(20, "Forest")]}).name, "Forest")
        self.assertIsNone(auto({}))


class ShelfTests(ApiTestCase):

    def index(self):
        return {d["id"]: d for d in api.decks_index()["decks"]}

    def test_the_library_and_deck_page_carry_the_cover(self):
        by_id = self.index()
        gruul = by_id["casual/gruul-test"]
        self.assertEqual({k: gruul["cover"][k] for k in ("name", "set", "number", "auto")},
                         {"name": "Llanowar Elves", "set": "fdn", "number": "227", "auto": True})
        self.assertEqual(gruul["cover"]["art"], "/img/fdn/227/art_crop")
        self.assertEqual(gruul["cover"]["img"], "/img/fdn/227/normal")
        self.assertEqual(gruul["colors"], ["U", "B", "R", "G"])
        self.assertEqual((gruul["revision"], gruul["edited"]), (0, None))     # the files backend keeps no history
        commander = by_id["commander/elf-commander"]
        self.assertEqual((commander["cover"]["name"], commander["cover"]["auto"]), ("Ghalta, Primal Hunger", True))
        self.assertEqual(commander["colors"], ["G"])                      # the commander's identity
        # Products: the same rules on their lists.
        self.assertEqual(by_id["product/fdc-test-precon"]["cover"]["name"], "Abaddon the Despoiler")
        self.assertEqual(by_id["product/fdn-beginner-box/elves"]["cover"]["name"], "Llanowar Elves")
        self.assertIsNone(by_id["casual/broken"]["cover"])
        view = api.deck_view("casual/gruul-test", "owned")              # the Planned list's, on either list
        self.assertEqual(view["summary"]["cover"]["name"], "Llanowar Elves")
        self.assertEqual(view["summary"]["revision"], 0)

    def test_the_colours_of_a_list(self):
        line = lambda name: decks.DeckLine(1, name, None, None)
        colours = api_library.deck_colors
        self.assertEqual(colours({"Deck": [line("Sol Ring")]}), [])                       # really colourless
        self.assertEqual(colours({"Commander": [line("Ghalta, Primal Hunger")], "Deck": [line("Murderous Rider")]}), ["G"])
        # No card could be read: None (no colours shown), not a colourless [].
        self.assertIsNone(colours({"Deck": [line("Not A Card"), line("Nor This")]}))
        self.assertIsNone(colours({}))
        # A commander that can't be read falls back to the Deck cards, as the deck page does.
        self.assertEqual(colours({"Commander": [line("Not A Card")], "Deck": [line("Murderous Rider"), line("Sol Ring")]}), ["B"])
        # The shelf says the same when working the cover out fails.
        with mock.patch.object(api_library, "deck_cover", side_effect=RuntimeError("boom")), \
                mock.patch.object(api_library.common, "_log"):
            summary = {"id": "casual/gruul-test"}
            api_library._shelf(summary, {"Deck": [line("Llanowar Elves")]})
        self.assertEqual((summary["cover"], summary["colors"]), (None, None))

    def test_a_cover_card_line(self):
        path = self.box.magic / "decks" / "casual" / "gruul-test.md"
        text = path.read_text(encoding="utf-8")
        _write(path, text.replace("- **Status:** building\n", "- **Status:** building\n- **Cover card:** sol ring (M19) 314\n"))
        inventory.invalidate()
        cover = self.index()["casual/gruul-test"]["cover"]
        # The exact name; a printing that isn't Sol Ring's gives way to the shown one, and isn't reported as
        # written (a save would write the bare name back).
        self.assertEqual((cover["name"], cover["auto"], cover["set"], cover["number"], cover["shown_set"]),
                         ("Sol Ring", False, None, None, "ecc"))
        self.assertEqual(cover["art"], f"/img/ecc/{cover['shown_number']}/art_crop")
        _write(path, text.replace("- **Status:** building\n", "- **Status:** building\n- **Cover card:** Pick Your Poison (CMB2) 97\n"))
        inventory.invalidate()
        cover = self.index()["casual/gruul-test"]["cover"]
        self.assertEqual((cover["name"], cover["set"], cover["number"], cover["art"]),
                         ("Pick Your Poison", "cmb2", "97", "/img/cmb2/97/art_crop"))
        self.assertEqual((cover["shown_set"], cover["shown_number"]), ("cmb2", "97"))
        # A bare name: nothing written to keep, and some printing of it shown.
        _write(path, text.replace("- **Status:** building\n", "- **Status:** building\n- **Cover card:** Sol Ring\n"))
        inventory.invalidate()
        cover = self.index()["casual/gruul-test"]["cover"]
        self.assertEqual((cover["name"], cover["set"], cover["number"], cover["auto"]), ("Sol Ring", None, None, False))
        self.assertTrue(cover["shown_set"] and cover["art"])
        # A name that isn't a card: the automatic one, saying why.
        _write(path, text.replace("- **Status:** building\n", "- **Status:** building\n- **Cover card:** Not A Card\n"))
        inventory.invalidate()
        cover = self.index()["casual/gruul-test"]["cover"]
        self.assertEqual((cover["name"], cover["auto"], cover["written"]), ("Llanowar Elves", True, "Not A Card"))
        self.assertIn("isn't a Scryfall card name", cover["problem"])


class CoverCardsTests(ApiTestCase):
    """GET /api/deck/cards: the picker's light read."""

    def test_each_card_once_with_its_shown_printing(self):
        answer = api_cover.cover_cards("casual/gruul-test")
        self.assertEqual(set(answer), {"summary", "auto", "cards"})
        self.assertEqual(set(answer["summary"]), {"id", "title", "revision", "cover"})
        self.assertEqual(answer["summary"]["id"], "casual/gruul-test")
        self.assertEqual(answer["auto"]["name"], "Llanowar Elves")
        names = [c["name"] for c in answer["cards"]]
        self.assertEqual(len(names), len(set(names)))                  # once each
        self.assertIn("Llanowar Elves", names)
        for c in answer["cards"]:
            with self.subTest(card=c["name"]):
                # The tile's printing is the one the card's own picture shows, so its art always exists.
                self.assertEqual(c["card"]["name"], c["name"])
                if c["card"]["img"]:
                    self.assertTrue(c["card"]["img"].startswith(f"/img/{c['set']}/"))
                if c["set"]:
                    printed = cards.printing_card(c["set"], c["number"])
                    self.assertEqual(printed["name"], c["name"])
        # None of the deck page's heavy parts.
        for key in ("owned", "stats", "matchups", "tokens", "table"):
            self.assertNotIn(key, answer)
        self.assertApiError(404, api_cover.cover_cards, "casual/nope")
        self.assertApiError(400, api_cover.cover_cards, "bad id")

    def test_a_line_naming_another_cards_printing_shows_the_cards_own(self):
        path = self.box.magic / "decks" / "casual" / "gruul-test.md"
        text = path.read_text(encoding="utf-8")
        self.assertIn("Llanowar Elves (FDN) 227", text)
        _write(path, text.replace("Llanowar Elves (FDN) 227", "Llanowar Elves (CMB2) 97", 1))
        inventory.invalidate()
        elves = next(c for c in api_cover.cover_cards("casual/gruul-test")["cards"] if c["name"] == "Llanowar Elves")
        self.assertNotEqual((elves["set"], elves["number"]), ("cmb2", "97"))
        self.assertEqual(cards.printing_card(elves["set"], elves["number"])["name"], "Llanowar Elves")

    def test_the_route_is_served(self):
        from decklab.lib import feature_routes
        handler = mock.Mock()
        handler._query.return_value = {"id": "casual/gruul-test"}
        handler._deck_id.return_value = "casual/gruul-test"
        self.assertTrue(feature_routes.dispatch(handler, ["deck", "cards"], "id=casual/gruul-test"))
        handler._allow.assert_called_once_with("GET", "HEAD")
        status, answer = handler._send_json.call_args.args
        self.assertEqual((status, answer["summary"]["id"]), (200, "casual/gruul-test"))


class CoverRouteTests(EditorTestCase):

    def cover(self, deck_id="casual/table-test", cover=None, expect=None, profile="matt"):
        data = {"id": deck_id, "expect": self.sha(deck_id) if expect is None else expect, "cover": cover}
        return api_cover.save_cover(self.body(profile, **data))

    def test_choose_and_clear(self):
        before = self.text("casual/table-test")
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            answer = self.cover(cover={"name": "llanowar elves", "set": "FDN", "number": "227"})
        self.assertEqual(apply.call_count, 1)                           # one change
        op, actor, message = apply.call_args.args
        self.assertEqual((op.kind, actor.id, message),
                         ("deck.save", "matt", "choose the cover card of Table Test: Llanowar Elves (FDN) 227"))
        self.assertEqual(self.text("casual/table-test"), before.replace(
            "- **Status:** building\n", "- **Status:** building\n- **Cover card:** Llanowar Elves (FDN) 227\n"))
        self.assertEqual((answer["saved"], answer["id"], answer["title"], answer["revision"]),
                         (True, "casual/table-test", "Table Test", 0))
        self.assertEqual({k: answer["cover"][k] for k in ("name", "set", "number", "auto", "art")},
                         {"name": "Llanowar Elves", "set": "fdn", "number": "227", "auto": False,
                          "art": "/img/fdn/227/art_crop"})
        # The same again saves nothing.
        with mock.patch.object(inventory, "apply") as apply:
            self.assertEqual(self.cover(cover={"name": "Llanowar Elves", "set": "fdn", "number": "227"})["saved"], False)
        apply.assert_not_called()
        # Back to automatic: the line goes, and the text is as it was.
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            answer = self.cover(cover=None)
        self.assertEqual(apply.call_args.args[2], "set the cover card of Table Test back to automatic")
        self.assertEqual(self.text("casual/table-test"), before)
        self.assertEqual((answer["cover"]["name"], answer["cover"]["auto"]), ("Llanowar Elves", True))

    def test_stale_expect_is_409(self):
        old = self.sha("casual/table-test")
        self.cover(cover={"name": "Sol Ring"})
        error = self.assertApiError(409, lambda: self.cover(cover={"name": "Black Lotus"}, expect=old))
        self.assertEqual(error.extra["conflict"]["reason"], "changed")
        # A revision: the files backend's decks are revision 0 ("unknown"), so 1 is stale there.
        self.assertApiError(409, lambda: self.cover(cover={"name": "Black Lotus"}, expect=1))
        self.assertEqual(self.cover(cover={"name": "Black Lotus"}, expect=0)["saved"], True)
        self.assertIn("- **Cover card:** Black Lotus\n", self.text("casual/table-test"))

    def test_bad_requests(self):
        before = self.text("casual/table-test")
        sha = self.sha("casual/table-test")
        for cover, words in (({"name": "Not A Card"}, "isn't a Scryfall card name"),
                             ({"name": "Sol Ring", "set": "fdn", "number": "227"}, "isn't a printing of Sol Ring"),
                             ({"name": "Sol Ring", "set": "ecc"}, "needs both"),
                             ({"name": "Sol Ring", "colour": "blue"}, "Unknown key"),
                             ("Sol Ring", "cover must be")):
            with self.subTest(cover=cover):
                error = self.assertApiError(400, lambda: self.cover(cover=cover, expect=sha))
                self.assertIn(words, error.message)
        for expect in (True, -1, "abc", 1.5, None):
            with self.subTest(expect=expect):
                self.assertApiError(400, api_cover.save_cover, self.body(id="casual/table-test", expect=expect, cover=None))
        self.assertApiError(400, api_cover.save_cover, self.body(id="casual/table-test", cover=None))       # no expect
        # Products and pairings have no text to write; a deck that isn't there is 404.
        self.assertApiError(400, api_cover.save_cover, self.body(id="product/fdn-beginner-box/elves", expect=0,
                                                                  cover=None))
        self.assertApiError(404, api_cover.save_cover, self.body(id="casual/nope", expect=0, cover=None))
        self.assertEqual(self.text("casual/table-test"), before)

    def test_the_route_is_served(self):
        from decklab.lib import feature_routes
        handler = mock.Mock()
        handler._write_body.return_value = self.body(id="casual/table-test", expect=self.sha("casual/table-test"),
                                                     cover={"name": "Sol Ring"})
        self.assertTrue(feature_routes.dispatch(handler, ["deck", "cover"], ""))
        handler._allow.assert_called_once_with("POST")
        status, answer = handler._send_json.call_args.args
        self.assertEqual((status, answer["saved"], answer["cover"]["name"]), (200, True, "Sol Ring"))


class CoverPermissionTests(PermissionTestCase):
    """The route asks what a save of the deck's text asks (deck.edit): Matt's, User1's, User2's."""

    def call(self, deck_id):
        return lambda p: api_cover.save_cover(self.body(p, id=deck_id, expect=self.sha(deck_id),
                                                        cover={"name": "Llanowar Elves"}))

    def test_who_may_choose_a_cover(self):
        # "local" is User1 named on the home network (her own rights there too), "script" Matt named there.
        # A deck of another space answers 404 as a missing one, before any 403 (E10-S30): Matt's admin
        # role doesn't reach User2's decks, nor User2 home's.
        self.check(self.call("casual/gruul-test"), {"matt", "script"}, hidden={"user2"})   # Played by: either
        self.check(self.call("commander/elf-commander"), {"matt", "user1", "local", "script"},
                   hidden={"user2"})                                                     # Played by: wife
        self.check(self.call("user2/casual/r-elves"), {"user2"},
                   hidden={"matt", "user1", "local", "script"})                           # User2's own space
        self.assertIn("- **Cover card:** Llanowar Elves\n",
                      (self.box.magic / "people" / "user2" / "decks" / "casual" / "r-elves.md").read_text(encoding="utf-8"))


class ImageErrorTests(ApiTestCase):
    """Scryfall's answers are never the PC's fault (stage 1: an HTTPError has the URL as its filename)."""

    def fails_with(self, error):
        with mock.patch.object(cards, "_download", side_effect=error):
            return self.assertApiError

    def setUp(self):
        super().setUp()
        card_lookup._missing_images.clear()
        self.addCleanup(card_lookup._missing_images.clear)

    def test_scryfall_errors(self):
        url = "https://cards.scryfall.io/art_crop/front/x.jpg"
        for error, status in ((urllib.error.HTTPError(url, 404, "Not Found", {}, None), 404),
                              (urllib.error.HTTPError(url, 500, "Server Error", {}, None), 503),
                              (urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None), 503),
                              (urllib.error.URLError("timed out"), 503),
                              (TimeoutError("timed out"), 503)):
            card_lookup._missing_images.clear()
            with self.subTest(error=error), mock.patch.object(cards, "_download", side_effect=error):
                self.assertApiError(status, card_lookup.image_file, "fdn", "227", "art_crop")
        # The PC's own disk is still a 500.
        disk = PermissionError(13, "Access is denied", str(self.box.data / "images" / "x.jpg"))
        with mock.patch.object(cards, "_download", side_effect=disk):
            self.assertApiError(500, card_lookup.image_file, "fdn", "227", "large")
        self.assertApiError(404, card_lookup.image_file, "fdn", "227", "huge")

    def test_an_answer_is_closed_and_a_missing_image_is_remembered(self):
        error = urllib.error.HTTPError("https://cards.scryfall.io/art_crop/front/x.jpg", 404, "Not Found", {}, None)
        with mock.patch.object(error, "close", wraps=error.close) as close, \
                mock.patch.object(cards, "_download", side_effect=error) as download:
            self.assertApiError(404, card_lookup.image_file, "fdn", "227", "art_crop")
            self.assertApiError(404, card_lookup.image_file, "fdn", "227", "art_crop")
        close.assert_called_once_with()
        self.assertEqual(download.call_count, 1)                        # the second one wasn't asked of Scryfall
        # Another size, or the time running out, asks again.
        with mock.patch.object(cards, "_download", side_effect=error) as download:
            self.assertApiError(404, card_lookup.image_file, "fdn", "227", "large")
            with mock.patch.object(card_lookup.time, "monotonic",
                                   return_value=card_lookup.time.monotonic() + card_lookup.MISSING_IMAGE_SECONDS + 1):
                self.assertApiError(404, card_lookup.image_file, "fdn", "227", "art_crop")
        self.assertEqual(download.call_count, 2)
        # A 500 is closed too, and never remembered.
        server = urllib.error.HTTPError("https://cards.scryfall.io/x.jpg", 500, "Server Error", {}, None)
        with mock.patch.object(server, "close", wraps=server.close) as close, \
                mock.patch.object(cards, "_download", side_effect=server):
            self.assertApiError(503, card_lookup.image_file, "fdn", "227", "normal")
        close.assert_called_once_with()
        self.assertNotIn(("fdn", "227", "normal"), card_lookup._missing_images)


@unittest.skipIf(db_support.unavailable(), db_support.unavailable() or "")
class DatabaseCoverTests(EditorTestCase, db_support.DbTestCase):
    """The route on the database backend: one revision with its message, one change set, and the revision
    as the expect token."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from decklab.db import profiles_sync
        from decklab.tests.test_inventory_contract import FIXTURE_PROFILES
        profiles_sync.sync(listed=FIXTURE_PROFILES, dbname=cls.dbname)

    def setUp(self):
        super().setUp()
        from decklab.tests.test_deck_saving_db import into_database
        self.backend = into_database(self)

    def sql(self, query, *args):
        with self.connect() as c:
            return c.execute(query, args).fetchall()

    def test_one_revision_and_one_change_set(self):
        deck_id = "casual/table-test"
        summary = {d["id"]: d for d in api.decks_index()["decks"]}[deck_id]
        self.assertEqual(summary["revision"], 1)
        self.assertIsNone(summary["edited"])        # the import changed every deck at once: not an edit
        sets = self.sql("select count(*) from audit.change_set")[0][0]
        answer = api_cover.save_cover(self.body("user1", id=deck_id, expect=1, cover={"name": "Elvish Mystic"}))
        self.assertEqual((answer["saved"], answer["revision"]), (True, 2))
        self.assertEqual(self.sql("select revision, actor, message from deck_revision where deck_id = %s "
                                  "order by revision", deck_id),
                         [(1, "claude", "Import"), (2, "user1", "choose the cover card of Table Test: Elvish Mystic")])
        self.assertEqual(self.sql("select count(*) from audit.change_set")[0][0], sets + 1)
        self.assertIn("- **Cover card:** Elvish Mystic\n", inventory.current().deck(deck_id).text)
        # The revision read before is stale now: 409, naming who saved it.
        error = self.assertApiError(409, api_cover.save_cover, self.body(id=deck_id, expect=1, cover=None))
        self.assertEqual(error.extra["conflict"]["by"], "User1")
        self.assertEqual(api_cover.save_cover(self.body(id=deck_id, expect=2, cover=None))["revision"], 3)
        # Choosing a picture isn't an edit of the deck for the library's "Recently changed".
        self.assertNotIn(deck_id, inventory.deck_edited())

    def test_recently_changed_counts_only_edits_of_the_deck_itself(self):
        deck_id = "casual/table-test"
        from decklab.lib.state import Actor

        def save(text, message):
            held = inventory.current().deck(deck_id)
            inventory.apply(inventory.Op("deck.save", {"deck_id": deck_id, "text": text, "base_sha256": held.sha256}),
                            Actor("claude", "Claude", source="cli"), message)

        text = inventory.current().deck(deck_id).text
        self.assertNotIn(deck_id, inventory.deck_edited())
        # A table cell or the price stamp changing (what a table refresh does) isn't an edit.
        save(text.replace("| hand note |", "| hand note again |", 1).replace("1 USD = 1.5 AUD", "1 USD = 1.6 AUD", 1),
             "a table refresh")
        self.assertNotIn(deck_id, inventory.deck_edited())
        # A note in the prose is.
        text = inventory.current().deck(deck_id).text
        save(text + "\nA new note.\n", "a note")
        edited = inventory.deck_edited()
        self.assertIn(deck_id, edited)
        latest = self.sql("select at from deck_revision where deck_id = %s order by revision desc limit 1", deck_id)[0][0]
        self.assertEqual(edited[deck_id], latest)
        # And the library gives it in UTC, to the second.
        summary = {d["id"]: d for d in api.decks_index()["decks"]}[deck_id]
        self.assertRegex(summary["edited"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")


if __name__ == "__main__":
    unittest.main()
