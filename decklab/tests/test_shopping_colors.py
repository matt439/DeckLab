"""Optional Shopping swatches describe permitted home Planned lists, never queued cards or cached libraries."""
import contextlib
import copy
import json
import unittest
import zlib
from collections import Counter
from types import SimpleNamespace
from unittest import mock

from decklab.lib import cards, decks, inventory, pool
from decklab.lib.api import card_lookup, carddata, reprints, shopping
from decklab.lib.api.common import ApiError
from decklab.lib.decks import identity
from decklab.lib.inventory.model import Inventory


def summary(deck_id="casual/alpha", title="Alpha", **fields):
    return {"id": deck_id, "title": title, "space": "home", "versions": ["target"], **fields}


def sections(**parts):
    return {part: [SimpleNamespace(name=name) for name in names] for part, names in parts.items()}


class ShoppingColorsTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = Inventory("shopping-colors-v1")
        self.backend = mock.Mock()
        self.backend.load.return_value = self.snapshot
        self.enterContext(inventory.use(self.backend))
        self.enterContext(mock.patch.object(shopping.guard, "sees_deck", return_value=True))
        self.enterContext(mock.patch.object(shopping.guard, "require_sees_home_records"))
        self.identities = {"White": ["W"], "Blue": ["U"], "Black": ["B"], "Red": ["R"], "Green": ["G"],
                           "Colourless": [], "Commander": ["G", "U"]}
        self.enterContext(mock.patch.object(cards, "resolve", side_effect=lambda name: name if name in self.identities else None))
        self.enterContext(mock.patch.object(cards, "card", side_effect=lambda name: {"color_identity": self.identities[name]}))
        self.enterContext(mock.patch.object(inventory, "apply", side_effect=AssertionError("read-only projection")))

    @contextlib.contextmanager
    def overview(self, queue, summaries, *, ready=True):
        """Keep unrelated record/count/reprint work inert; no server or index is involved."""
        source = {"to_buy": queue, "orders": [], "checks": [], "warnings": []}
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(shopping.purchases, "overview", side_effect=lambda: copy.deepcopy(source)))
            stack.enter_context(mock.patch.object(shopping, "_home_decks", return_value=summaries))
            stack.enter_context(mock.patch.object(shopping, "_editable_components"))
            stack.enter_context(mock.patch.object(shopping, "_product_statuses"))
            check = stack.enter_context(mock.patch.object(shopping, "_cards_ready", return_value=ready))
            stack.enter_context(mock.patch.object(shopping, "_add_pictures"))
            stack.enter_context(mock.patch.object(reprints, "enrich"))
            stack.enter_context(mock.patch.object(shopping.shopping_missing, "gather", return_value=(
                {"ready": True, "rows": [], "warnings": [], "errors": [], "totals": {"cards": 0, "copies": 0}}, [])))
            yield shopping.shopping_overview, check

    def test_shared_library_identity_uses_planned_commander_first_and_wubrg_order(self):
        choices = [summary(), summary("commander/beta", "Beta", built_version="owned", status="built")]
        plans = {"casual/alpha": sections(Deck=["Green", "White", "Red", "Blue", "Black"], Sideboard=["Unknown"]),
                 "commander/beta": sections(Commander=["Commander"], Deck=["Black", "Red"])}
        before = copy.deepcopy(choices)
        with mock.patch.object(decks, "load_deck", side_effect=lambda deck_id, version: plans[deck_id]) as load:
            found = shopping._compact_decks(choices)
        self.assertEqual(found, [{"id": "casual/alpha", "title": "Alpha", "colors": ["W", "U", "B", "R", "G"]},
                                 {"id": "commander/beta", "title": "Beta", "colors": ["U", "G"]}])
        self.assertEqual(load.call_args_list, [mock.call("casual/alpha", "target"), mock.call("commander/beta", "target")])
        self.assertEqual(choices, before)

    def test_known_colourless_is_empty_array_and_unknown_never_uses_summary_or_owned_colors(self):
        choices = [summary(), summary("casual/unknown", "Unknown", colors=["R"], built_version="owned")]
        plans = {"casual/alpha": sections(Deck=["Colourless"]), "casual/unknown": sections(Deck=["Unknown"])}
        with mock.patch.object(decks, "load_deck", side_effect=lambda deck_id, version: plans[deck_id]):
            found = shopping._compact_decks(choices)
        self.assertEqual(found[0]["colors"], [])
        self.assertNotIn("colors", found[1])

    def test_foreign_hidden_unreadable_and_non_deck_choices_are_filtered_before_target_load(self):
        choices = [summary(), summary("user2/casual/private", "Private", space="home"),
                   summary("casual/wrong-space", "Wrong", space="user2"), summary("product/precon", "Product"),
                   summary("not an id", "Bad id"), summary("casual/hidden", "Hidden"),
                   summary("casual/unreadable", "Unreadable", error="private parse detail"),
                   summary("casual/no-target", "No target", versions=["owned"])]
        with mock.patch.object(shopping.guard, "sees_deck", side_effect=lambda item: item["id"] != "casual/hidden"), \
                mock.patch.object(decks, "load_deck", return_value=sections(Deck=["Red"])) as load:
            found = shopping._compact_decks(choices)
        self.assertEqual(found, [{"id": "casual/alpha", "title": "Alpha", "colors": ["R"]},
                                 {"id": "casual/no-target", "title": "No target"}])
        load.assert_called_once_with("casual/alpha", "target")

    def test_each_id_is_loaded_once_per_projection_and_color_arrays_are_not_shared(self):
        choices = [summary(), summary(), summary("casual/unreadable", "Unreadable"), summary("casual/unreadable", "Unreadable")]
        def load(deck_id, version):
            if deck_id.endswith("unreadable"):
                raise OSError("fixture read refused")
            return sections(Deck=["Red"])
        with mock.patch.object(decks, "load_deck", side_effect=load) as read:
            found = shopping._compact_decks(choices)
        self.assertEqual(read.call_args_list, [mock.call("casual/alpha", "target"), mock.call("casual/unreadable", "target")])
        found[0]["colors"].append("G")
        self.assertEqual(found[1]["colors"], ["R"])
        self.assertNotIn("colors", found[2])
        self.assertNotIn("colors", found[3])

    def test_expected_target_read_and_parse_failures_only_remove_optional_colors(self):
        failures = [decks.DeckNotFound("missing"), decks.DeckFileError("bad deck"), OSError("read failed"),
                    UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad fixture")]
        for failure in failures:
            with self.subTest(error=type(failure).__name__), mock.patch.object(decks, "load_deck", side_effect=failure):
                self.assertEqual(shopping._compact_decks([summary()]), [{"id": "casual/alpha", "title": "Alpha"}])

    def test_expected_missing_or_corrupt_index_failures_only_remove_optional_colors(self):
        failures = [OSError("missing index"), EOFError("truncated gzip"), zlib.error("bad gzip"),
                    json.JSONDecodeError("bad json", "{", 1), UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad fixture")]
        for failure in failures:
            with self.subTest(error=type(failure).__name__), \
                    mock.patch.object(decks, "load_deck", return_value=sections(Deck=["Red"])), \
                    mock.patch.object(shopping, "deck_colors", side_effect=failure):
                self.assertEqual(shopping._compact_decks([summary()]), [{"id": "casual/alpha", "title": "Alpha"}])

    def test_programmer_errors_in_target_loader_or_identity_are_not_masked(self):
        for failure in [TypeError("wrong call"), KeyError("wrong shape"), RuntimeError("programmer failure"),
                        ValueError("programmer value"), AttributeError("wrong object"), AssertionError("invariant")]:
            for function in ("load_deck", "deck_colors"):
                with self.subTest(error=type(failure).__name__, function=function), \
                        mock.patch.object(decks, "load_deck", return_value=sections(Deck=["Red"])):
                    owner = decks if function == "load_deck" else shopping
                    with mock.patch.object(owner, function, side_effect=failure), self.assertRaises(type(failure)):
                        shopping._compact_decks([summary()])

    def test_not_ready_card_data_keeps_records_revision_and_choices_without_color_reads(self):
        queued = {"name": "Card", "quantity": 2, "source": "magic/decks/casual/alpha.md", "for": "Old title",
                  "state": "deferred", "listed_aud": "0", "checked": "2026-10-24", "notes": "Saved evidence"}
        with self.overview([queued], [summary(colors=["G"])], ready=False) as (read, ready), \
                mock.patch.object(decks, "load_deck", side_effect=AssertionError("no target reads without card data")):
            answer = read()
        self.assertEqual(answer["queue_revision"], self.snapshot.revision)
        self.assertEqual(answer["queue_decks"], [{"id": "casual/alpha", "title": "Alpha"}])
        self.assertEqual(answer["to_buy"], [{**queued, "queue_row": 1, "deck": {"id": "casual/alpha", "title": "Alpha"}}])
        self.assertFalse(answer["missing_cards"]["ready"])
        ready.assert_called_once_with()
        self.backend.load.assert_called_once_with()

    def test_queue_links_and_choices_share_authoritative_metadata_without_changing_saved_rows(self):
        queue = [{"name": "First", "quantity": 2, "source": "magic/decks/casual/alpha.md", "for": "Old title", "state": "ready"},
                 {"name": "Second", "quantity": 1, "source": "magic/buylists/fixture.md", "for": " alpha ", "state": "long_term"}]
        before = copy.deepcopy(queue)
        with self.overview(queue, [summary()]) as (read, ready), \
                mock.patch.object(decks, "load_deck", return_value=sections(Deck=["Red"])) as load:
            answer = read()
        compact = {"id": "casual/alpha", "title": "Alpha", "colors": ["R"]}
        self.assertEqual(answer["queue_decks"], [compact])
        self.assertEqual([item["deck"] for item in answer["to_buy"]], [compact, compact])
        self.assertEqual([item["queue_row"] for item in answer["to_buy"]], [1, 2])
        self.assertEqual([{key: item[key] for key in original} for item, original in zip(answer["to_buy"], queue)], queue)
        self.assertEqual(queue, before)
        self.assertEqual(answer["queue_revision"], self.snapshot.revision)
        answer["to_buy"][0]["deck"]["colors"].append("G")
        self.assertEqual(answer["to_buy"][1]["deck"]["colors"], ["R"])
        self.assertEqual(answer["queue_decks"][0]["colors"], ["R"])
        load.assert_called_once_with("casual/alpha", "target")
        ready.assert_called_once_with()
        self.backend.load.assert_called_once_with()

    def test_omitted_color_after_index_failure_keeps_exact_overview_records_and_revision(self):
        queue = [{"name": "Card", "quantity": 1, "source": "magic/decks/casual/alpha.md", "for": "Alpha", "state": "ready"}]
        with self.overview(queue, [summary()]) as (read, _), \
                mock.patch.object(decks, "load_deck", return_value=sections(Deck=["Red"])), \
                mock.patch.object(shopping, "deck_colors", side_effect=EOFError("truncated local index")):
            answer = read()
        self.assertEqual(answer["queue_revision"], self.snapshot.revision)
        self.assertEqual(answer["queue_decks"], [{"id": "casual/alpha", "title": "Alpha"}])
        self.assertEqual(answer["to_buy"], [{**queue[0], "queue_row": 1, "deck": {"id": "casual/alpha", "title": "Alpha"}}])

    def test_color_reads_stay_in_the_request_pin_and_a_later_request_retries_from_its_own_snapshot(self):
        later = Inventory("shopping-colors-v2")
        self.backend.load.side_effect = [self.snapshot, later]
        seen = []
        def load(deck_id, version):
            current = inventory.current()
            seen.append((deck_id, version, current.revision))
            return sections(Deck=["Red" if current.revision == self.snapshot.revision else "Blue"])
        choices = [summary(), summary("casual/beta", "Beta")]
        with self.overview([], choices) as (read, _), mock.patch.object(decks, "load_deck", side_effect=load):
            first, second = read(), read()
        self.assertEqual([item["colors"] for item in first["queue_decks"]], [["R"], ["R"]])
        self.assertEqual([item["colors"] for item in second["queue_decks"]], [["U"], ["U"]])
        self.assertEqual((first["queue_revision"], second["queue_revision"]), (self.snapshot.revision, later.revision))
        self.assertEqual([entry[2] for entry in seen], [self.snapshot.revision] * 2 + [later.revision] * 2)
        self.assertEqual(self.backend.load.call_count, 2)

    def test_failed_identity_is_retried_next_request_instead_of_reusing_a_failed_cache(self):
        with self.overview([], [summary()]) as (read, _), \
                mock.patch.object(decks, "load_deck", return_value=sections(Deck=["Colourless"])) as load, \
                mock.patch.object(shopping, "deck_colors", side_effect=[OSError("temporary index failure"), []]):
            first, second = read(), read()
        self.assertNotIn("colors", first["queue_decks"][0])
        self.assertEqual(second["queue_decks"][0]["colors"], [])
        self.assertEqual(load.call_count, 2)

    def test_changed_card_index_identity_is_read_again_with_the_same_inventory_revision(self):
        with self.overview([], [summary()]) as (read, _), \
                mock.patch.object(decks, "load_deck", return_value=sections(Deck=["Red"])) as load:
            first = read()
            self.identities["Red"] = ["U"]      # A replaced/corrected card index, with the deck text unchanged.
            second = read()
        self.assertEqual(first["queue_decks"][0]["colors"], ["R"])
        self.assertEqual(second["queue_decks"][0]["colors"], ["U"])
        self.assertEqual(first["queue_revision"], second["queue_revision"])
        self.assertEqual(load.call_count, 2)

    def test_home_record_permission_is_checked_before_any_record_or_color_read(self):
        with mock.patch.object(shopping.guard, "require_sees_home_records", side_effect=ApiError(403, "Private")), \
                mock.patch.object(shopping.purchases, "overview", side_effect=AssertionError("must not read records")), \
                mock.patch.object(decks, "load_deck", side_effect=AssertionError("must not read targets")), self.assertRaises(ApiError):
            shopping.shopping_overview()
        self.backend.load.assert_not_called()


_NO_IDENTITY = object()


class PreparedIndexShoppingColorsTests(unittest.TestCase):
    """Coarse readiness can succeed while one returned card has damaged identity metadata."""

    def setUp(self):
        self.snapshot = Inventory("prepared-index-colors-v1")
        self.backend = mock.Mock()
        self.backend.load.return_value = self.snapshot
        self.enterContext(inventory.use(self.backend))
        self.enterContext(mock.patch.object(shopping.guard, "sees_deck", return_value=True))
        self.enterContext(mock.patch.object(shopping.guard, "require_sees_home_records"))
        self.logs = []
        self.enterContext(mock.patch.object(shopping.common, "_log", self.logs.append))
        self.enterContext(mock.patch.object(inventory, "apply", side_effect=AssertionError("read-only fixture")))

    @staticmethod
    def card_record(name, colors=_NO_IDENTITY):
        record = {"name": name, "paper": True, "mana_cost": "", "cmc": 0, "type_line": "Creature",
                  "colors": [], "roles": [], "printings": [], "oracle_text": "Fixture text"}
        if colors is not _NO_IDENTITY:
            record["color_identity"] = colors
        return record

    @contextlib.contextmanager
    def loaded(self, bad=_NO_IDENTITY):
        records = {"Bad": self.card_record("Bad", bad), "Good": self.card_record("Good", ["G"]),
                   "Queued": self.card_record("Queued", []), "White": self.card_record("White", ["W"]),
                   "Blue": self.card_record("Blue", ["U"]), "Black": self.card_record("Black", ["B"]),
                   "Red": self.card_record("Red", ["R"]), "Commander": self.card_record("Commander", ["G", "U"])}
        data = {"version": cards.INDEX_VERSION, "built_at": "fixture index", "bulk": {}, "roles": {},
                "cards": records, "tokens": {}, "printings": {}}
        # Neither resolve/card nor readiness is mocked: this is the real prepared-index path.
        with mock.patch.object(cards, "_index", cards._prepare(data)):
            yield records

    @staticmethod
    def plan(name, quantity=1):
        return {"Deck": [decks.DeckLine(quantity, name, None, None)]}

    @contextlib.contextmanager
    def projected(self):
        queued = {"name": "Queued", "quantity": 2, "state": "ready", "for": "Alpha",
                  "source": "magic/decks/casual/alpha.md", "listed_aud": "0", "checked": "2026-10-24"}
        plans = {"casual/alpha": self.plan("Bad", 3), "casual/good": self.plan("Good")}
        supply = pool.Pool(Counter({"Bad": 1}), {}, [])
        source = {"to_buy": [queued], "orders": [], "checks": [], "warnings": []}
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(shopping.purchases, "overview", side_effect=lambda: copy.deepcopy(source)))
            stack.enter_context(mock.patch.object(shopping, "_home_decks", return_value=[summary(), summary("casual/good", "Good")]))
            stack.enter_context(mock.patch.object(shopping, "_editable_components"))
            stack.enter_context(mock.patch.object(shopping, "_product_statuses"))
            stack.enter_context(mock.patch.object(reprints, "enrich"))
            stack.enter_context(mock.patch.object(decks, "load_deck", side_effect=lambda deck_id, version: plans[deck_id]))
            stack.enter_context(mock.patch.object(pool, "load_pool", return_value=supply))
            stack.enter_context(mock.patch.object(cards, "price_aud", side_effect=AssertionError("no price reads")))
            yield shopping.shopping_overview, queued

    def test_real_ready_index_with_bad_or_missing_returned_identity_only_omits_optional_deck_colors(self):
        malformed = [_NO_IDENTITY, None, "R", {"R": True}, ["red"], ["C"], ["R", None], [["R"]], [1]]
        for value in malformed:
            with self.subTest(identity=value), self.loaded(value):
                self.assertIsNone(carddata._require_cards())
                self.assertTrue(shopping._cards_ready())
                self.assertEqual(cards.resolve("Bad"), "Bad")
                with self.assertRaises(identity.CardIdentityError):
                    identity.deck_colors(self.plan("Bad"))
                self.backend.reset_mock()
                with self.projected() as (read, queued), \
                        mock.patch.object(carddata, "_require_cards", wraps=carddata._require_cards) as ready, \
                        mock.patch.object(card_lookup, "_card_json", wraps=card_lookup._card_json) as card_json:
                    answer = read()
                ready.assert_called_once_with()
                self.assertTrue(card_json.called)
                self.assertEqual(answer["queue_revision"], self.snapshot.revision)
                self.assertEqual(answer["queue_decks"], [{"id": "casual/alpha", "title": "Alpha"},
                                                         {"id": "casual/good", "title": "Good", "colors": ["G"]}])
                linked = answer["to_buy"][0]
                self.assertEqual(linked["deck"], {"id": "casual/alpha", "title": "Alpha"})
                self.assertEqual(linked["queue_row"], 1)
                self.assertEqual({key: linked[key] for key in queued}, queued)
                self.assertEqual((linked["card"]["name"], linked["card"]["color_identity"]), ("Queued", []))
                missing = answer["missing_cards"]
                self.assertEqual((missing["ready"], missing["warnings"], missing["errors"]), (True, [], []))
                self.assertEqual(missing["totals"], {"cards": 2, "copies": 3})
                self.assertEqual({row["name"]: row["missing"] for row in missing["rows"]}, {"Bad": 2, "Good": 1})
                self.backend.load.assert_called_once_with()

    def test_real_prepared_valid_identities_keep_colourless_wubrg_and_commander_priority(self):
        with self.loaded(["R"]):
            self.assertIsNone(carddata._require_cards())
            self.assertIs(shopping.deck_colors, identity.deck_colors)
            self.assertEqual(identity.deck_colors(self.plan("Queued")), [])
            self.assertIsNone(identity.deck_colors(self.plan("Unknown card")))
            full = {"Deck": [decks.DeckLine(1, name, None, None) for name in ["Good", "Red", "Black", "Blue", "White"]]}
            self.assertEqual(identity.deck_colors(full), ["W", "U", "B", "R", "G"])
            full["Commander"] = [decks.DeckLine(1, "Commander", None, None)]
            self.assertEqual(identity.deck_colors(full), ["U", "G"])
            full["Commander"] = [decks.DeckLine(1, "Queued", None, None)]
            self.assertEqual(identity.deck_colors(full), [])
            full["Commander"] = [decks.DeckLine(1, "Unknown card", None, None)]
            self.assertEqual(identity.deck_colors(full), ["W", "U", "B", "R", "G"])
            self.assertEqual(card_lookup._card_json(cards.card("Queued"), None)["color_identity"], [])

    def test_lookup_programmer_errors_including_identity_named_keyerror_still_propagate(self):
        with self.loaded(["R"]), mock.patch.object(decks, "load_deck", return_value=self.plan("Bad")):
            self.assertIsNone(carddata._require_cards())
            for lookup in ("resolve", "card"):
                for failure in [KeyError("color_identity"), TypeError("lookup programming fault"),
                                RuntimeError("lookup programming fault"), ValueError("lookup programming fault"),
                                AssertionError("lookup invariant")]:
                    with self.subTest(lookup=lookup, error=type(failure).__name__), \
                            mock.patch.object(cards, lookup, side_effect=failure), self.assertRaises(type(failure)) as caught:
                        shopping._compact_decks([summary()])
                    self.assertIs(caught.exception, failure)

    def test_non_none_returned_record_shape_is_a_typed_fault_but_absent_card_is_unknown(self):
        with self.loaded(["R"]), mock.patch.object(decks, "load_deck", return_value=self.plan("Bad")):
            for record in ([], "malformed returned record", 0):
                with self.subTest(record=record), mock.patch.object(cards, "card", return_value=record):
                    with self.assertRaises(identity.CardIdentityError):
                        identity.deck_colors(self.plan("Bad"))
                    self.assertEqual(shopping._compact_decks([summary()]), [{"id": "casual/alpha", "title": "Alpha"}])
            with mock.patch.object(cards, "card", return_value=None):
                self.assertIsNone(identity.deck_colors(self.plan("Bad")))


if __name__ == "__main__":
    unittest.main()
