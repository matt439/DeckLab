"""Physical snapshot parsing and raw-save safety, with no live deck or database writes."""
import json
import unittest
from unittest import mock

from decklab.lib import accessories, decks, inventory, pool, state, tokens
from decklab.lib.api import assembly as packing, assembly_completion, deck_page, settings
from decklab.lib.decks import assembled
from decklab.lib.inventory import ops_decks
from decklab.lib.state.memory import MemoryStore
from decklab.tests.test_assembly_completion import PROFILES, TABLE
from decklab.tests.test_collection_assembly import PreparationCase
from decklab.tests.test_pool import deck_md, setUpModule, tearDownModule  # noqa: F401


def parsed(text=None, kind="casual"):
    text = text or deck_md("A", "built", "Deck\n2 Llanowar Elves (FDN) 227 *F*\n20 Forest\n")
    return decks.parse_deck(text.encode(), "a", kind)


class AssembledParsingTests(unittest.TestCase):
    def test_snapshot_preserves_printing_finish_and_intended_lists(self):
        deck = parsed()
        original = decks.format_decklist(deck.target)
        assembled.install(deck, "target", deck.target)
        text = decks.render_deck_file(deck)
        reread = parsed(text)
        self.assertEqual(decks.format_decklist(assembled.sections(reread)), original)
        self.assertEqual(decks.format_decklist(reread.target), original)
        self.assertEqual(assembled.generation(reread), 1)
        self.assertEqual(assembled.key(deck), assembled.key(reread))
        self.assertNotIn(assembled.FIELD, decks.OWNED_FIELDS)
        self.assertNotIn(assembled.GENERATION, decks.OWNED_FIELDS)

    def test_malformed_headers_are_refused_without_guessing_a_recipe(self):
        valid = {"version": "target", "sections": {"Deck": ["1 Llanowar Elves"]}}
        values = ["{", "[]", '{"version":"target","version":"owned","sections":{}}',
                  json.dumps({**valid, "version": "future"}),
                  json.dumps({**valid, "sections": {"Sideboard": ["1 Llanowar Elves"]}}),
                  json.dumps({**valid, "sections": {"Deck": "1 Llanowar Elves"}}),
                  json.dumps({**valid, "sections": {"Deck": ["0 Llanowar Elves"]}}),
                  json.dumps({**valid, "sections": {"Deck": ["1 Llanowar Elves\n1 Forest"]}}),
                  json.dumps({**valid, "sections": {"Deck": ["10000 Llanowar Elves"]}}),
                  "[" * 1100 + "]" * 1100]
        for value in values:
            with self.subTest(value=value[:100]):
                deck = parsed()
                deck.header.append(decks.HeaderField(assembled.FIELD, value))
                with self.assertRaises(assembled.AssembledError):
                    assembled.get(deck)

    def test_duplicate_headers_and_casual_commander_snapshot_are_refused(self):
        deck = parsed()
        assembled.install(deck, "target", deck.target)
        deck.header.append(decks.HeaderField(assembled.FIELD, deck.get_field(assembled.FIELD)))
        with self.assertRaises(assembled.AssembledError):
            assembled.get(deck)
        deck = parsed()
        deck.header.append(decks.HeaderField(assembled.FIELD, json.dumps({"version": "target", "sections": {
            "Commander": ["1 Llanowar Elves"], "Deck": ["20 Forest"]}})))
        with self.assertRaises(assembled.AssembledError):
            assembled.get(deck)

    def test_generation_changes_for_marker_only_install_and_survives_clear(self):
        deck = parsed()
        assembled.install(deck, "target", deck.target)
        before = assembled.key(deck)
        self.assertFalse(assembled.install(deck, "target", deck.target))
        self.assertEqual(before, assembled.key(deck))
        assembled.install(deck, "target", deck.target, force=True)
        self.assertNotEqual(before, assembled.key(deck))
        assembled.clear(deck, serial=assembled.generation(deck) + 1)
        taken_apart = assembled.key(deck)
        assembled.install(deck, "target", deck.target)
        self.assertNotIn(assembled.key(deck), (before, taken_apart))


class AssembledRawSaveTests(PreparationCase):
    def setUp(self):
        super().setUp()
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4))
        self.deck("a", "A", "built", "Deck\n4 Llanowar Elves\n20 Forest\n")

    def test_corrupt_snapshot_makes_reservations_unknown_without_mutable_fallback(self):
        path = self.magic / "decks/casual/a.md"
        text = path.read_text().replace("- **Status:** built", '- **Status:** built\n- **Assembled:** {"bad":1}')
        path.write_text(text, encoding="utf-8")
        result = pool.load_pool()
        self.assertFalse(result.in_use)
        self.assertTrue(any("Assembled" in warning for warning in result.warnings))

    def test_inactive_and_mismatched_snapshots_cannot_be_created(self):
        for status, version in (("building", "target"), ("built", "owned")):
            with self.subTest(status=status, version=version):
                deck = parsed(deck_md("B", status, "Deck\n1 Llanowar Elves\n",
                                      owned="Deck\n1 Elvish Mystic\n", built_version="target"))
                assembled.install(deck, version, deck.target)
                with self.assertRaises(inventory.Invalid):
                    ops_decks.create(inventory.current(), space="home", kind="casual", slug="b",
                                     text=decks.render_deck_file(deck))

    def test_plain_text_clients_cannot_reset_a_saved_physical_generation(self):
        snapshot = inventory.current()
        record = snapshot.deck("casual/a")
        deck = ops_decks.parsed_deck(record)
        assembled.install(deck, "target", deck.target)
        snapshot, _ = ops_decks.save(snapshot, deck_id=record.id, text=decks.render_deck_file(deck),
                                     base_sha256=record.sha256, allow_assembled=True)
        current = snapshot.deck(record.id)
        deck = ops_decks.parsed_deck(current)
        deck.header[:] = [f for f in deck.header if f.key != assembled.GENERATION]
        with self.assertRaises(ops_decks.DeckRefused):
            ops_decks.save(snapshot, deck_id=record.id, text=decks.render_deck_file(deck),
                           base_sha256=current.sha256)

    def test_snapshot_survives_removal_of_its_old_intended_version_and_can_repack(self):
        main = "Deck\n4 Llanowar Elves\n20 Forest\n"
        old = "Deck\n4 Elvish Mystic\n20 Forest\n"
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4),
                       ("Elvish Mystic", "cmm", "648", "nonfoil", 4))
        self.deck("a", "A", "built", main, owned=old, built_version="owned-only", table=TABLE)
        before = ops_decks.parsed_deck(inventory.current().deck("casual/a"))
        assembled.install(before, "owned", before.owned)
        self.write("decks/casual/a.md", decks.render_deck_file(before))
        record = inventory.current().deck("casual/a")
        metadata = "".join(f"- **{field.key}:** {field.value}\n" for field in before.header
                           if field.key in (assembled.FIELD, assembled.GENERATION))
        text = deck_md("A", "built", main, built_version="owned-only", table=TABLE)
        text = text.replace("- **Status:** built\n", "- **Status:** built\n" + metadata)
        after, _ = ops_decks.save(inventory.current(), deck_id=record.id, text=text, base_sha256=record.sha256)
        self.write("decks/casual/a.md", after.deck(record.id).text)
        held = pool.load_pool()
        self.assertFalse(held.warnings)
        self.assertEqual(held.in_use[0].cards, {"Elvish Mystic": 4})
        self.assertEqual(accessories.sleeve_need(accessories._own(record.id, [])[4]), 24)
        holder, = tokens._holders([])
        self.assertEqual(holder[2:4], ("owned", decks.parse_decklist(old)))
        with mock.patch.object(tokens, "cached_deck_tokens", wraps=tokens.cached_deck_tokens) as cached:
            deck_page._index_tokens()(decks.find_summary(record.id))
        self.assertEqual(cached.call_args.args[1:3], ("owned", decks.parse_decklist(old)))
        with state.use(MemoryStore()), mock.patch.object(settings, "_config_profiles", return_value=PROFILES):
            selection = [{"id": record.id, "version": "target"}]
            plan = packing.assembly_preview(json.dumps({"profile": "matt", "decks": selection}))
            assembly_completion.mark_built(json.dumps({"profile": "matt", "decks": selection,
                "fingerprint": plan["completion"]["fingerprint"], "confirmed": True}))
        rebuilt = ops_decks.parsed_deck(inventory.current().deck(record.id))
        self.assertIsNone(rebuilt.built_version)
        self.assertEqual(assembled.sections(rebuilt), decks.parse_decklist(main))

    def test_explicit_snapshot_resolves_legacy_missing_built_version_after_intended_edit(self):
        self.cards_csv("collection.csv", ("Llanowar Elves", "fdn", "227", "nonfoil", 4),
                       ("Elvish Mystic", "cmm", "648", "nonfoil", 4))
        self.deck("a", "A", "built", "Deck\n4 Llanowar Elves\n",
                  owned="Deck\n2 Elvish Mystic\n")
        record = inventory.current().deck("casual/a")
        parsed_deck = ops_decks.parsed_deck(record)
        decks.apply_edit(parsed_deck, None, decks.parse_decklist("Deck\n1 Elvish Mystic\n"))
        result, _ = ops_decks.save(inventory.current(), deck_id=record.id,
                                   text=decks.render_deck_file(parsed_deck), base_sha256=record.sha256)
        self.write("decks/casual/a.md", result.deck(record.id).text)
        physical = pool.load_pool()
        self.assertFalse(physical.warnings)
        self.assertEqual(physical.in_use[0].cards, {"Elvish Mystic": 2})
