"""The library read once per inventory snapshot (E11-S90, lib/decks/library_cache.py): however many
find_summary(), list_decks() and load_deck() lookups one request makes, each deck's text is parsed
at most once; every caller gets its own copy; and a write's new snapshot is read afresh.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_deck_library_cache
"""
from unittest import mock

from decklab.lib import decks, inventory
from decklab.lib.api import play_records
from decklab.lib.decks import DeckLine, library_cache
from decklab.lib.inventory import ops_decks  # noqa: F401 (registers deck.save)
from decklab.lib.state import Actor
from decklab.tests.test_api import ApiTestCase, _write

DECK = """# {title}

- **Format:** Casual 60-card, 1v1
- **Played by:** either
- **Status:** idea

## Decklist

```
Deck
4 Llanowar Elves (FDN) 227
20 Forest
```
"""

SANDBOX_DECKS = ("casual/broken", "casual/gruul-test", "commander/elf-commander")


class LibraryCacheTestCase(ApiTestCase):

    def add_decks(self, count):
        for n in range(count):
            _write(self.box.magic / "decks" / "casual" / f"extra-{n}.md", DECK.format(title=f"Extra {n}"))

    def deck_ids(self):
        return [s["id"] for s in decks.list_decks() if not s["id"].startswith("product/")]

    def counting(self):
        """A patch counting decks.parse_deck's calls (the stored text's parse) in self.parses."""
        self.parses = []
        real = decks.parse_deck

        def parse(*args, **kwargs):
            self.parses.append(args[1] if len(args) > 1 else kwargs.get("slug"))
            return real(*args, **kwargs)
        return mock.patch.object(decks, "parse_deck", side_effect=parse)


class ParsedOnceTests(LibraryCacheTestCase):

    def test_every_lookup_in_one_request_parses_each_deck_at_most_once(self):
        with inventory.pinned(), self.counting():
            ids = self.deck_ids()
            for _ in range(5):
                for deck_id in ids:
                    self.assertEqual(decks.find_summary(deck_id)["id"], deck_id)
                decks.list_decks()
                decks.load_deck("casual/gruul-test")
                decks.load_deck("casual/gruul-test", "owned")
                decks.load_deck("commander/elf-commander")
        self.assertEqual(sorted(ids), sorted(SANDBOX_DECKS))
        self.assertEqual(sorted(self.parses), sorted(["broken", "gruul-test", "elf-commander"]))

    def test_parses_grow_with_the_library_not_with_its_square(self):
        counts = {}
        for extra in (0, 10, 30):
            self.add_decks(extra)
            with inventory.pinned(), self.counting():
                ids = self.deck_ids()
                for deck_id in ids:                     # one lookup a deck, as the Game log's records make
                    decks.find_summary(deck_id)
                    decks.find_summary(deck_id)
            counts[len(ids)] = len(self.parses)
        self.assertEqual(counts, {n: n for n in counts})
        self.assertEqual(sorted(counts), [3, 13, 33])

    def test_the_game_logs_record_lookups_share_one_reading(self):
        record = {"sides": [{"id": "casual/gruul-test"}, {"id": "commander/elf-commander"}]}
        with inventory.pinned(), self.counting():
            for _ in range(20):
                found = play_records._record_decks(record)
        self.assertEqual([s["id"] for s in found], ["casual/gruul-test", "commander/elf-commander"])
        self.assertEqual(len(self.parses), len(SANDBOX_DECKS))

    def test_product_decks_and_pairings_are_read_once_a_snapshot(self):
        with inventory.pinned():
            with mock.patch.object(decks, "_read_product_decks", wraps=decks._read_product_decks) as products, \
                    mock.patch.object(decks, "_read_pairings", wraps=decks._read_pairings) as pairings:
                for _ in range(4):
                    decks.list_decks()
                    pairs = decks.beginner_box_pairings()
                    decks.find_summary(pairs[0]["id"])
                    decks.load_deck(pairs[0]["id"])
                    decks.load_deck("product/fdn-beginner-box/elves")
                    decks._product_decks()
        self.assertEqual((products.call_count, pairings.call_count), (1, 1))

    def test_outside_a_request_each_call_reads_the_inventory_as_it_is(self):
        self.assertNotIn("casual/extra-0", self.deck_ids())
        self.assertIsNone(decks.find_summary("casual/extra-0"))
        self.add_decks(1)
        self.assertIn("casual/extra-0", self.deck_ids())
        self.assertIsNotNone(decks.find_summary("casual/extra-0"))

    def test_a_failed_reading_is_not_kept(self):
        snapshot = inventory.current()
        calls = []

        def work():
            calls.append(1)
            if len(calls) == 1:
                raise OSError("busy")
            return "read"
        with self.assertRaises(OSError):
            library_cache.kept(snapshot, "probe", work)
        self.assertEqual(library_cache.kept(snapshot, "probe", work), "read")
        self.assertEqual(library_cache.kept(snapshot, "probe", work), "read")
        self.assertEqual(len(calls), 2)

    def test_an_object_that_cant_keep_anything_works_each_time(self):
        self.assertEqual([library_cache.kept(object(), "k", lambda: 1) for _ in range(2)], [1, 1])


class CopiesTests(LibraryCacheTestCase):

    def test_a_changed_summary_changes_no_other_callers_copy(self):
        with inventory.pinned():
            found = decks.find_summary("casual/gruul-test")
            found["title"] = "Changed"
            found["versions"].append("changed")
            listed = decks.list_decks()
            listed[0]["title"] = "Changed too"
            listed.clear()
            again = decks.find_summary("casual/gruul-test")
            self.assertEqual((again["title"], again["versions"]), ("Gruul Test", ["target", "owned"]))
            self.assertEqual(decks.list_decks()[0]["title"], "Broken")
            self.assertTrue(decks.list_decks())

    def test_a_changed_pairing_or_product_deck_changes_no_other_callers_copy(self):
        with inventory.pinned():
            pair = decks.beginner_box_pairings()[0]
            pair["halves"].append("changed")
            found = decks.find_summary(pair["id"])
            self.assertEqual(len(found["halves"]), 2)
            found["halves"].clear()
            self.assertEqual(len(decks.beginner_box_pairings()[0]["halves"]), 2)
            product = decks._product_decks()[0]
            product["sections"]["Deck"].clear()
            self.assertTrue(decks._product_decks()[0]["sections"]["Deck"])

    def test_a_changed_decklist_changes_no_other_callers_copy(self):
        for deck_id, version in (("casual/gruul-test", "target"), ("casual/gruul-test", "owned"),
                                 ("product/fdn-beginner-box/elves", "target")):
            with self.subTest(deck_id=deck_id, version=version), inventory.pinned():
                first = decks.load_deck(deck_id, version)
                expected = {name: [DeckLine(l.quantity, l.name, l.set, l.number, l.finish) for l in lines]
                            for name, lines in first.items()}
                first["Deck"][0].quantity += 50
                first["Deck"].append(DeckLine(1, "Opt"))
                first["Sideboard"] = []
                self.assertEqual(decks.load_deck(deck_id, version), expected)

    def test_a_merged_pairing_changes_no_other_callers_copy(self):
        with inventory.pinned():
            pair_id = decks.beginner_box_pairings()[0]["id"]
            first = decks.load_deck(pair_id)
            total = decks.card_count(first)
            first["Deck"][0].quantity += 9
            self.assertEqual(decks.card_count(decks.load_deck(pair_id)), total)


class WritesTests(LibraryCacheTestCase):

    def test_a_save_in_the_request_is_seen_by_its_next_lookup(self):
        with inventory.pinned():
            self.assertEqual(decks.find_summary("casual/gruul-test")["status"], "building")
            deck = inventory.current().deck("casual/gruul-test")
            text = deck.text.replace("- **Status:** building", "- **Status:** idea")
            inventory.apply(inventory.Op("deck.save", {"deck_id": deck.id, "text": text,
                                                       "base_sha256": deck.sha256}),
                            Actor("matt", "Matt", "home"), "an idea again")
            self.assertEqual(decks.find_summary("casual/gruul-test")["status"], "idea")
            self.assertEqual(next(s for s in decks.list_decks() if s["id"] == "casual/gruul-test")["status"], "idea")

    def test_a_new_deck_after_an_invalidated_snapshot_is_found(self):
        with inventory.pinned():
            self.assertIsNone(decks.find_summary("casual/extra-0"))
            self.add_decks(1)
            inventory.invalidate()
            self.assertEqual(decks.find_summary("casual/extra-0")["title"], "Extra 0")
            self.assertEqual(decks.load_deck("casual/extra-0")["Deck"][1], DeckLine(20, "Forest"))

    def test_a_changed_space_list_reads_the_library_again(self):
        with inventory.pinned():
            decks.list_decks()
            with mock.patch.object(decks.spaces, "space_ids", return_value=["home"]), self.counting():
                self.assertEqual(len([s for s in decks.list_decks() if not s["id"].startswith("product/")]), 3)
            self.assertEqual(self.parses, [])               # the parses themselves are still kept


class BuildDecksTests(LibraryCacheTestCase):
    """Build decks (GET /api/assembly and its preview) reads each deck's text once too: the usual
    opponents and the selected decks' packing, stand-ins and sections share the library's parse."""

    def test_the_build_decks_page_parses_each_deck_at_most_once(self):
        from decklab.lib.api import assembly
        self.add_decks(10)
        with inventory.pinned(), self.counting():
            ids = self.deck_ids()
            answer = assembly.assembly_view("casual/gruul-test")
            self.assertEqual([item["id"] for item in answer["decks"]], ["casual/gruul-test"])
        self.assertEqual(len(ids), 13)
        self.assertEqual(sorted(self.parses), sorted(deck_id.rsplit("/", 1)[1] for deck_id in ids))

    def test_a_preview_of_several_decks_parses_each_at_most_once(self):
        import json
        from decklab.lib.api import assembly
        body = json.dumps({"decks": [{"id": "casual/gruul-test", "version": "target"},
                                     {"id": "commander/elf-commander", "version": "target"}]})
        with inventory.pinned(), self.counting():
            answer = assembly.assembly_preview(body)
        self.assertEqual(len(answer["decks"]), 2)
        self.assertEqual(sorted(self.parses), ["broken", "elf-commander", "gruul-test"])

    def test_a_parse_handed_to_build_decks_is_its_own_copy(self):
        with inventory.pinned():
            stored = inventory.current().deck("casual/gruul-test")
            first = decks.parsed_stored(stored)
            first.target["Deck"].clear()
            first.header.clear()
            again = decks.parsed_stored(stored)
            self.assertTrue(again.target["Deck"])
            self.assertEqual(again.status, "building")
            self.assertIs(decks.parsed_stored(stored, own_copy=False), decks.parsed_stored(stored, own_copy=False))

    def test_a_wrapped_list_decks_doesnt_send_lookups_back_to_rereading_the_library(self):
        # Review finding: find_summary fell back to list_decks() whenever list_decks wasn't the
        # module's own function (a test's patch, or a profiling wrapper), reading it per lookup.
        with inventory.pinned(), mock.patch.object(decks, "list_decks", wraps=decks.list_decks) as listed, \
                mock.patch.object(decks, "beginner_box_pairings", wraps=decks.beginner_box_pairings) as pairs:
            pair_id = decks._kept_pairing_summaries()[0]["id"]
            for _ in range(3):
                self.assertEqual(decks.find_summary("casual/gruul-test")["id"], "casual/gruul-test")
                self.assertEqual(decks.find_summary(pair_id)["id"], pair_id)
        self.assertEqual((listed.call_count, pairs.call_count), (0, 0))


class StandInTests(LibraryCacheTestCase):

    def test_a_tests_stand_in_library_is_the_one_find_summary_looks_in(self):
        from decklab.tests import library_stand_in
        pairing = {"id": "pairing/cats+elves", "kind": "casual", "versions": ["target"]}
        library_stand_in.start(self, [{"id": "casual/green", "title": "Green", "kind": "casual"}], [pairing])
        self.assertEqual(decks.find_summary("casual/green")["title"], "Green")
        self.assertIsNone(decks.find_summary("casual/gruul-test"))
        self.assertEqual(decks.find_summary("pairing/elves+cats")["id"], "pairing/cats+elves")
        self.assertEqual([s["id"] for s in decks.list_decks()], ["casual/green"])
