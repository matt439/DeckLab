"""Optional Planned identity swatches on visible Collection source links; fixture stores only."""
import copy
import json
import unittest
import zlib
from collections import Counter
from types import SimpleNamespace
from unittest import mock

from decklab.lib import access, cards, config, decks, inventory, pool
from decklab.lib.api import collection_edit as ce, collection_sources as sources, library
from decklab.lib.decks import assembled, identity
from decklab.tests import test_collection_sources as fixtures
from decklab.tests.test_api import ApiTestCase, _write


def line(name):
    return decks.DeckLine(1, name, None, None)


class DeckIdentityTests(unittest.TestCase):
    def setUp(self):
        known = {
            "Commander": {"colors": ["W"], "color_identity": ["W"]},
            "Partner": {"colors": ["U"], "color_identity": ["U"]},
            "Two faces": {"colors": ["B"], "color_identity": ["G", "B"]},
            "Sideboard": {"colors": ["R"], "color_identity": ["R"]},
            "Colourless": {"colors": [], "color_identity": []},
        }
        self.enterContext(mock.patch.object(cards, "resolve", side_effect=lambda name:
            "Two faces" if name == "Front face" else name if name in known else None))
        self.enterContext(mock.patch.object(cards, "card", side_effect=known.get))

    def test_library_reexports_the_same_low_level_identity_helper(self):
        self.assertIs(library.deck_colors, identity.deck_colors)
        self.assertEqual(library.COLOR_ORDER, identity.COLOR_ORDER)

    def test_known_commanders_have_priority_and_unknown_commanders_fall_back_to_the_main_list(self):
        sections = {"Commander": [line("Commander"), line("Partner")],
                    "Deck": [line("Front face")], "Sideboard": [line("Sideboard")]}
        self.assertEqual(identity.deck_colors(sections), ["W", "U"])
        sections["Commander"] = [line("Unreadable commander")]
        self.assertEqual(identity.deck_colors(sections), ["B", "G"])
        sections["Commander"] = [line("Colourless")]
        self.assertEqual(identity.deck_colors(sections), [])

    def test_face_alias_uses_full_identity_and_colourless_does_not_mean_unreadable(self):
        self.assertEqual(identity.deck_colors({"Deck": [line("Front face")]}), ["B", "G"])
        self.assertEqual(identity.deck_colors({"Companion": [line("Partner")], "Deck": [line("Front face")]}),
                         ["U", "B", "G"])
        self.assertEqual(identity.deck_colors({"Deck": [line("Colourless")]}), [])
        self.assertIsNone(identity.deck_colors({"Deck": [line("Unreadable")]}))
        self.assertIsNone(identity.deck_colors({}))


class HolderColorProjectionTests(unittest.TestCase):
    def annotate(self, uses, *, sees=lambda deck_id: True, records=True):
        return sources.annotate({"rows": {fixtures.KEY: {"held": len(uses), "guess": False}}, "error": None},
                                uses, fixtures.grouped([fixtures.row()]), sees=sees, records=records)

    def test_unknown_colors_are_omitted_and_known_colourless_is_an_explicit_empty_list(self):
        for colors in (None, [], ["U", "B"]):
            with self.subTest(colors=colors):
                use = fixtures.holder(planned_colors=colors, printing_version="owned")
                result = self.annotate([use])["rows"][fixtures.KEY]
                expected = {"id": "casual/a", "title": "A", "quantity": 1, "version": "owned"}
                if colors is not None:
                    expected["colors"] = colors
                self.assertEqual(result, {"held": 1, "guess": False,
                                         "listed_holders": [expected], "unattributed": 0})
                if colors is not None:
                    self.assertIsNot(result["listed_holders"][0]["colors"], use.planned_colors)

    def test_hidden_and_private_product_colors_never_escape_or_trigger_projection_reads(self):
        uses = [fixtures.holder(planned_colors=["G"]),
                fixtures.holder("casual/private", "Private deck", planned_colors=["U"]),
                fixtures.holder("product/private", "Private product", planned_colors=["R"])]
        before = copy.deepcopy(uses)
        with mock.patch.object(inventory, "current", side_effect=AssertionError("no private inventory read")), \
                mock.patch.object(decks, "load_deck", side_effect=AssertionError("no private deck read")), \
                mock.patch.object(inventory, "deck_revisions_with_text", side_effect=AssertionError("no history")), \
                mock.patch.object(cards, "resolve", side_effect=AssertionError("no extra card lookup")), \
                mock.patch.object(cards, "card", side_effect=AssertionError("no extra card lookup")):
            result = self.annotate(uses, sees=lambda deck_id: deck_id != "casual/private", records=False)
        self.assertEqual(result, {"rows": {fixtures.KEY: {"held": 3, "guess": False, "unattributed": 2,
            "listed_holders": [{"id": "casual/a", "title": "A", "quantity": 1,
                                "version": "target", "colors": ["G"]}]}}, "error": None})
        self.assertEqual(uses, before)
        for secret in ("Private", "casual/private", "product/private", '["U"]', '["R"]'):
            self.assertNotIn(secret, json.dumps(result))

    def test_late_visibility_failure_discards_colors_with_the_earlier_names(self):
        uses = [fixtures.holder(planned_colors=["G"]),
                fixtures.holder("casual/private", "Private source", cards={fixtures.MYSTIC: 1},
                    printings={fixtures.hint(fixtures.MYSTIC, set_code="cmm", number="648"): 1}, planned_colors=["B"])]
        rows = [fixtures.row(quantity=1), fixtures.row(fixtures.MYSTIC, set_code="cmm", number="648", quantity=1)]
        storage = {"rows": {fixtures.KEY: {"held": 1, "guess": True},
                            "cmm|648|nonfoil": {"held": 1, "guess": False}}, "error": None}
        policy = mock.Mock(side_effect=[True, RuntimeError("Secret visibility diagnostic")])
        result = sources.annotate(storage, uses, fixtures.grouped(rows), sees=policy, records=True)
        self.assertEqual(policy.call_count, 2)
        self.assertEqual(result, {"rows": {fixtures.KEY: {"held": 1, "guess": True,
                                     "listed_holders": [], "unattributed": 1},
                              "cmm|648|nonfoil": {"held": 1, "guess": False,
                                     "listed_holders": [], "unattributed": 1}}, "error": None})
        for secret in ("casual/a", "Private source", "Secret", '"colors"', '"version"'):
            self.assertNotIn(secret, json.dumps(result))


class PlannedColorsPoolTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.enterContext(mock.patch.object(config, "REPO", self.box.root))
        self.enterContext(mock.patch.object(config, "DATA", self.box.data))
        _write(self.box.root / "config.json", json.dumps(fixtures.ROLES))

    def as_(self, who):
        return access.using({"profile": who, "email": "", "remote": True})

    def make_owned_assembly(self, *, product=False):
        _write(self.box.magic / "products/status.csv", "file,status,intact,notes\n"
               "fdn-beginner-box.csv,cancelled,,\nfdc-test-precon.csv,cancelled,,\n"
               + ("source-box.csv,owned,yes,\n" if product else ""))
        rows = [fixtures.row(quantity=1)]
        collection = "Llanowar Elves,fdn,227,nonfoil,1,NM,en,\n"
        if product:
            rows.append(fixtures.row(fixtures.MYSTIC, set_code="cmm", number="648", quantity=1))
            collection += "Elvish Mystic,cmm,648,nonfoil,1,NM,en,\n"
            _write(self.box.magic / "products/source-box.csv",
                   "section,name,set,collector_number,finish,quantity\ndeck,Elvish Mystic,cmm,648,nonfoil,1\n")
        _write(self.box.magic / "collection.csv", ",".join(ce.FIELDS) + "\n" + collection)
        text = ("# Planned black, assembled green\n\n- **Status:** built\n- **Played by:** user\n"
                "- **Built version:** target\n\n## Decklist\n\n```\nDeck\n1 Murderous Rider (ELD) 97\n```\n\n"
                "## Substitutes\n\n### Owned-only version\n\n```\nDeck\n1 Llanowar Elves (FDN) 227\n```\n")
        parsed = decks.parse_deck(text.encode("utf-8"), "owned-color", "casual")
        assembled.install(parsed, "owned", parsed.owned)
        _write(self.box.magic / "decks/casual/owned-color.md", decks.render_deck_file(parsed))
        inventory.invalidate()
        return rows

    def test_planned_identity_differs_from_owned_evidence_and_products_use_their_existing_target(self):
        rows = self.make_owned_assembly(product=True)
        self.box.state.visibility_set("home", "collection", True, fixtures.ACTOR, "Publish fixture")
        self.box.state.visibility_set("home", "decks", True, fixtures.ACTOR, "Publish fixture")
        with self.as_("matt"), mock.patch.object(self.box.inventory, "load", wraps=self.box.inventory.load) as read, \
                mock.patch.object(decks, "load_deck", wraps=decks.load_deck) as deck_read, \
                mock.patch.object(inventory, "deck_revisions_with_text", side_effect=AssertionError("no history")), \
                inventory.pinned():
            actual = pool.load_pool()
            by_id = {use.id: use for use in actual.in_use}
            use = by_id["casual/owned-color"]
            self.assertEqual((use.cards, use.printings, use.printing_version, use.planned_colors),
                             (Counter({fixtures.NAME: 1}), Counter({fixtures.hint(): 1}), "owned", ["B"]))
            product = by_id["product/source-box"]
            self.assertEqual((product.printing_version, product.planned_colors), ("target", ["G"]))
            reads_before_projection = deck_read.call_count
            with mock.patch.object(pool, "load_pool", return_value=actual):
                own = ce._storage("home", rows, {"rows": {}})
                with self.as_("user2"):
                    outsider = ce.rows_view("home")["storage"]
            self.assertEqual(deck_read.call_count, reads_before_projection)
        self.assertEqual(read.call_count, 1)
        expected = {"id": "casual/owned-color", "title": use.title, "quantity": 1,
                    "version": "owned", "colors": ["B"]}
        self.assertEqual(own["rows"][fixtures.KEY]["listed_holders"], [expected])
        self.assertEqual(outsider["rows"][fixtures.KEY]["listed_holders"], [expected])
        self.assertEqual(own["rows"]["cmm|648|nonfoil"]["listed_holders"],
                         [{"id": product.id, "title": product.title, "quantity": 1, "version": "target", "colors": ["G"]}])
        self.assertEqual(outsider["rows"]["cmm|648|nonfoil"],
                         {"held": 1, "guess": False, "listed_holders": [], "unattributed": 1})
        for secret in ("product/source-box", product.title, '"colors": ["G"]'):
            self.assertNotIn(secret, json.dumps(outsider))

    def test_optional_local_index_read_errors_only_remove_the_swatch(self):
        rows = self.make_owned_assembly()
        errors = [OSError("Secret index path"), RuntimeError("Secret index version"),
                  json.JSONDecodeError("Secret index JSON", "x", 0), zlib.error("Secret compressed index"),
                  EOFError("Secret truncated gzip"), UnicodeDecodeError("utf-8", b"\xff", 0, 1, "Secret encoding")]
        for error in errors:
            with self.subTest(error=type(error).__name__):
                with self.as_("matt"), mock.patch.object(pool, "deck_colors", side_effect=error) as colors, \
                        mock.patch.object(self.box.inventory, "load", wraps=self.box.inventory.load) as read, \
                        mock.patch.object(decks, "load_deck", side_effect=AssertionError("no target reload")), \
                        mock.patch.object(inventory, "deck_revisions_with_text", side_effect=AssertionError("no history")), \
                        inventory.pinned():
                    actual = pool.load_pool()
                    use = next(item for item in actual.in_use if item.id == "casual/owned-color")
                    self.assertIsNone(use.planned_colors)
                    with mock.patch.object(pool, "load_pool", return_value=actual):
                        result = ce._storage("home", rows, {"rows": {}})
                colors.assert_called_once()
                self.assertEqual(read.call_count, 1)
                self.assertEqual(result, {"rows": {fixtures.KEY: {"held": 1, "guess": False, "unattributed": 0,
                    "listed_holders": [{"id": use.id, "title": use.title, "quantity": 1, "version": "owned"}]}}, "error": None})
                self.assertNotIn("Secret", json.dumps(result))

    def test_programmer_errors_in_optional_identity_still_propagate(self):
        self.make_owned_assembly()
        for error_type in (TypeError, KeyError, ValueError, AssertionError):
            with self.subTest(error=error_type.__name__):
                error = error_type("fixture programming error")
                with mock.patch.object(pool, "deck_colors", side_effect=error), self.assertRaises(error_type) as caught:
                    pool.load_pool()
                self.assertIs(caught.exception, error)

    def test_absent_parsed_target_never_substitutes_the_owned_list_or_loads_a_target(self):
        deck_id = "casual/unparsed"
        summary = {"id": deck_id, "source": deck_id, "title": "Unparsed target", "status": "built",
                   "space": "home", "versions": ["target", "owned"], "built_version": "owned"}
        owned = decks.parse_decklist("Deck\n1 Llanowar Elves (FDN) 227\n")
        with mock.patch.object(decks, "list_decks", return_value=[summary]), \
                mock.patch.object(inventory, "current", return_value=SimpleNamespace(deck=lambda deck_id: None)), \
                mock.patch.object(decks, "load_deck", return_value=owned) as load, \
                mock.patch.object(pool, "deck_colors", side_effect=AssertionError("owned is not Planned")) as colors, \
                mock.patch.object(self.box.inventory, "load", side_effect=AssertionError("no snapshot reload")), \
                mock.patch.object(inventory, "deck_revisions_with_text", side_effect=AssertionError("no history")):
            uses = pool._built_in_use("home", set(), set(), {}, [])
        load.assert_called_once_with(deck_id, "owned")
        colors.assert_not_called()
        self.assertEqual(len(uses), 1)
        self.assertEqual((uses[0].cards, uses[0].printing_version, uses[0].planned_colors),
                         (Counter({fixtures.NAME: 1}), "owned", None))
