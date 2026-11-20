"""Read-only Commander draft, availability, mana and household basic-land assumptions."""
import json
from collections import Counter
from unittest import TestCase, mock

from decklab.lib import feature_routes, pool
from decklab.lib.api import commander_draft as api
from decklab.lib.decks import commander_draft
from decklab.tests import test_commander_candidates as base
from decklab.tests.test_api import _write
from decklab.tests.test_collection_edit import ROLES
from decklab.tests.test_commander_candidates_pairs import INVENTED, _invented
from decklab.tests.test_deck_privacy_readers import _as


class DraftApiTests(base.CandidatesTestCase):
    def setUp(self):
        super().setUp()
        (self.box.magic / "decks" / "casual" / "broken.md").unlink()

    def preview(self, **fields):
        return api.preview(json.dumps({"name": "Ghalta, Primal Hunger", **fields}))

    def test_normal_route_counts_only_loose_copies_and_no_order_sources(self):
        handler = mock.Mock(command="POST")
        _write(self.box.root / "config.json", json.dumps(ROLES))
        handler._write_body.return_value = json.dumps({"profile": "matt", "name": "ghalta, primal hunger", "locked": ["llanowar elves"]})
        self.assertTrue(feature_routes.dispatch(handler, ["commanders", "draft"], ""))
        status, answer = handler._send_json.call_args.args
        self.assertEqual(status, 200)
        picks = {p["name"]: p for p in answer["picks"]}
        self.assertEqual(picks["Llanowar Elves"]["quantity"], 1)
        self.assertTrue(picks["Llanowar Elves"]["locked"])
        self.assertNotIn("Sol Ring", picks)
        self.assertNotIn("Elvish Mystic", picks)
        self.assertIn({"name": "Sol Ring", "quantity": 1}, answer["incoming"])
        self.assertEqual(answer["target"], answer["picked"] + answer["open_slots"])

    def test_changed_loans_incomplete_snapshot_and_unavailable_locks(self):
        snapshot = api._pool("home")
        snapshot.in_use.append(pool.InUse("loan", "Private title", "lent out", Counter({"Llanowar Elves": 3})))
        with mock.patch.object(api, "_pool", return_value=snapshot):
            self.assertApiError(400, lambda: self.preview(locked=["Llanowar Elves"]))
            self.assertApiError(400, lambda: self.preview(locked=["Sol Ring"]))
            snapshot.warnings.append("Private title")
            error = self.assertApiError(409, self.preview)
            self.assertNotIn("Private title", error.message)

    def test_private_or_public_cross_space_never_reads_pool(self):
        _write(self.box.root / "config.json", json.dumps(ROLES))
        with _as("user2"), mock.patch.object(api, "_pool") as loader:
            self.assertApiError(403, self.preview)
            with mock.patch.object(api.guard, "require_sees_inventory"):
                self.assertApiError(403, self.preview)
            loader.assert_not_called()


class DraftSelectionTests(TestCase):
    def setUp(self):
        self.cards = {name: dict(card) for name, card in INVENTED.items()}
        self.rules = api._rules()

    def card(self, name, identity="", kind="Artifact", **fields):
        self.cards[name] = {**_invented(name, identity, kind, ""), **fields}

    def draft(self, locks=(), names=("Green Partner", "Blue Partner"), denial=()):
        return commander_draft.build(list(names), list(locks), dict.fromkeys(self.cards, 3),
                                     self.cards.get, self.rules, denial)

    def test_pair_full_list_balances_basic_supply_under_skewed_colour_demand(self):
        for colour, name in (("G", "Forest"), ("U", "Island")):
            self.card(name, colour, "Basic Land")
        for i in range(70):
            self.card(f"Spell {i}", "U", mana_cost="{U}{U}")
            self.card(f"Green land {i}", "G", "Land", produced_mana=["G"])
        result = self.draft(["Spell 0"])
        self.assertEqual((result["target"], result["picked"], result["open_slots"]), (98, 98, 0))
        self.assertEqual(result["picks"][0]["name"], "Spell 0")
        sources = {r["colour"]: r["count"] for r in result["mana_sources"]}
        self.assertGreaterEqual(sources["G"], 3)
        self.assertGreater(sources["U"], sources["G"])
        self.assertEqual(sum(sources.values()), 38)
        self.assertTrue(all(p["quantity"] == 1 or p["assumed_basic"] for p in result["picks"]))

    def test_strict_eligibility_legal_locks_and_social_flags(self):
        self.card("Unknown")
        del self.cards["Unknown"]["color_identity"]
        self.card("Banned", commander_legality="banned")
        self.card("Blue changer", "U", game_changer=True)
        self.card("Land denial", oracle_id="denial")
        result = self.draft(denial={"denial"})
        names = {p["name"] for p in result["picks"]}
        self.assertIn("No selected land is known to produce blue mana.", result["warnings"])
        self.assertIn("No selected land is known to produce green mana.", result["warnings"])
        self.assertFalse(names & {"Unknown", "Banned", "Blue changer", "Land denial", "Red Chooser"})
        for lock in ("Unknown", "Banned", "Red Chooser", "Blue Partner"):
            with self.subTest(lock), self.assertRaises(ValueError):
                self.draft([lock])
        locked = self.draft(["Blue changer", "Land denial"], denial={"denial"})
        self.assertEqual(sum("chosen card flagged" in w for w in locked["warnings"]), 2)
        self.assertTrue(all(p["locked"] for p in locked["picks"][:2]))
        with self.assertRaises(ValueError):
            self.draft(names=("Red Chooser", "Blue Partner"))
        del self.cards["Green Partner"]["color_identity"]
        with self.assertRaises(ValueError):
            self.draft()


    def test_only_verified_plain_wastes_and_card_text_copy_exceptions(self):
        self.card("Colourless Lead", kind="Legendary Creature")
        self.card("Wastes", kind="Basic Land")
        self.card("Spell", oracle_text="A deck can have up to two cards named Spell.")
        self.card("More", oracle_text="A deck can have any number of cards named More.")
        answer = self.draft(names=("Colourless Lead",))
        picks = {p["name"]: p for p in answer["picks"]}
        self.assertEqual((picks["Spell"]["quantity"], picks["More"]["quantity"]), (2, 3))
        self.assertEqual((picks["Wastes"]["quantity"], picks["Wastes"]["assumed_basic"]), (38, True))
        self.assertEqual(answer["open_lands"], 0)
        self.assertEqual(answer["mana_sources"], [{"colour": "C", "count": 38}])
        del self.cards["Wastes"]
        self.assertEqual(self.draft(names=("Colourless Lead",))["open_lands"], 38)

    def test_cache_inclusion_has_provenance_and_fallback_spreads_curve(self):
        for mana in (1, 3, 6):
            for i in range(70):
                self.card(f"Card {mana}-{i}", cmc=mana)
        self.card("Synergy card", cmc=5)
        affinity = lambda names: ("https://example.com/sample", {"Synergy card": 95.6})
        answer = commander_draft.build(["Green Partner"], [], dict.fromkeys(self.cards, 1),
                                       self.cards.get, self.rules, set(), affinity)
        self.assertEqual(answer["affinity_source"], "https://example.com/sample")
        picks = {p["name"]: p for p in answer["picks"]}
        self.assertIn("95.6%", picks["Synergy card"]["reason"])
        for mana in (1, 3, 6):
            self.assertTrue(any(name.startswith(f"Card {mana}-") for name in picks))
