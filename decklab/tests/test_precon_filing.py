"""Post-precon filing with fake MTGJSON, locked JSON receipts and disposable inventory fixtures."""
import json
from collections import Counter
from unittest import mock

from decklab.lib import inventory, pool
from decklab.lib.api import collection_filing as filing, precons as api
from decklab.lib.inventory import paths
from decklab.tests import test_precons as support
from decklab.tests.test_api import _write
from decklab.tests.test_collection_edit import HEADER, ROLES, USER2
from decklab.tests.test_collection_filing import deck_text
from decklab.tests.test_precon_tokens import PreconTokensTestCase


class PreconFilingTests(support.PreconTestCase):

    def setUp(self):
        super().setUp()
        self.listed("Small_TST", {"data": {"name": "Small", "code": "TST", "type": "Theme Deck",
                     "mainBoard": [support.card("Llanowar Elves", "FDN", "227", 4)], "sideBoard": []}}, "Theme Deck")

    def set_owned(self, quantity):
        text = HEADER if not quantity else USER2.replace(",nonfoil,2,", f",nonfoil,{quantity},")
        _write(self.box.root / paths.collection("user2"), text)

    def fresh(self, **options):
        return self.add("Small_TST", title="Fresh precon", **options)

    def guide(self, answer):
        result = answer["collection"]["filing"]
        self.assertEqual((result["space"], result["profile"]), ("user2", "user2"))
        counted = Counter()
        for item in result["destinations"]:
            counted[item["row"]] += item["quantity"]
        self.assertEqual([counted[i] for i in range(len(result["added"]))],
                         [row["quantity"] for row in result["added"]])
        json.dumps(result, allow_nan=False)
        return result

    def test_new_built_holder_is_supplied_by_new_copies_when_prior_stock_is_zero(self):
        self.set_owned(0)
        answer = self.fresh()
        guide = self.guide(answer)
        self.assertEqual(guide["status"], "ready")
        self.assertEqual(guide["destinations"], [{"kind": "deck", "row": 0, "quantity": 4,
                         "deck": {"id": answer["deck"]["id"], "title": "Fresh precon", "status": "built"}}])
        saved = self.backend.load()
        with inventory.pinned(saved):
            found = pool.load_pool("user2")
        self.assertEqual(found.owned["Llanowar Elves"] - 4, 0)
        self.assertEqual(sum(h.cards["Llanowar Elves"] for h in found.in_use), 4)
        extra = self.writes[-1][3].extra
        self.assertEqual(extra["added_printings"][0]["before_quantity"], 0)
        self.assertEqual(extra["added_printings"][0]["after_quantity"], 4)
        self.assertEqual(extra["created_deck"], {"id": answer["deck"]["id"], "space": "user2",
                         "sha256": saved.deck(answer["deck"]["id"]).sha256, "was_absent": True})
        json.dumps(extra["created_deck"])
        self.assertNotIn("created_deck", json.dumps(answer))
        self.assertNotIn("before_quantity", json.dumps(answer))

    def test_preowned_duplicates_and_competing_decks_do_not_steal_the_built_precon(self):
        self.set_owned(10)
        _write(self.box.magic / "people/user2/decks/casual/a-waiter.md", deck_text("Waiting", 12))
        source = (self.cache / "decks/Small_TST.json").read_bytes()
        answer = self.fresh()
        guide = self.guide(answer)
        self.assertEqual(guide["status"], "ready")
        self.assertEqual([(d["deck"]["id"], d["quantity"]) for d in guide["destinations"]],
                         [(answer["deck"]["id"], 4)])
        self.assertEqual((self.cache / "decks/Small_TST.json").read_bytes(), source)
        raw = (self.box.root / answer["collection"]["raw"]).read_bytes()
        self.assertIn(b"Llanowar Elves,fdn,227,nonfoil,4", raw)

    def test_nonbuilt_override_uses_ordinary_shared_prior_stock_and_priority(self):
        self.set_owned(0)
        _write(self.box.magic / "people/user2/decks/casual/a-waiter.md", deck_text("Waiting", 2))
        answer = self.fresh(fields={"status": "idea"})
        guide = self.guide(answer)
        self.assertEqual(guide["status"], "ready")
        self.assertEqual([(d["deck"]["id"], d["deck"]["status"], d["quantity"]) for d in guide["destinations"]],
                         [("user2/casual/a-waiter", "building", 2), (answer["deck"]["id"], "idea", 2)])
        with inventory.pinned(self.backend.load()):
            self.assertEqual(pool.load_pool("user2").in_use, [])

    def test_default_plan_and_compound_operation_keep_filing_capture_off(self):
        before = self.backend.load()
        profile = next(p for p in ROLES["profiles"] if p["id"] == "user2")
        with inventory.pinned(before):
            made = api.plan_add("user2", "Small_TST", "Plan only", None, profile, "User2")
            self.assertNotIn("capture_filing", made["op"].params)
            self.assertNotIn("capture_additions", made["op"].params["collection"])
            _, summary = made["op"].run(before)
        self.assertNotIn("created_deck", summary.extra)
        self.assertNotIn("added_printings", summary.extra)
        self.assertEqual(self.backend.load(), before)

    def test_malformed_locked_proof_yields_unknown_without_failing_saved_precon(self):
        real = api.saving.apply_op

        def corrupt(*args, **kwargs):
            after, summary = real(*args, **kwargs)
            extra = {**summary.extra, "created_deck": {**summary.extra["created_deck"], "was_absent": False}}
            return after, inventory.Summary(summary.text, summary.counts, summary.changed, extra)

        with mock.patch.object(api.saving, "apply_op", side_effect=corrupt):
            answer = self.fresh()
        self.assertEqual(self.guide(answer)["status"], "unknown")
        self.assertIsNotNone(self.backend.load().deck(answer["deck"]["id"]))
        self.assertEqual(self.rows("user2")["rows"][0]["quantity"], "6")
        self.assertEqual(self.writes_made(), 1)

    def test_advice_exception_keeps_both_cards_and_deck_saved(self):
        with mock.patch.object(filing, "after_precon", side_effect=RuntimeError("private fixture error")):
            answer = self.fresh()
        self.assertEqual(self.guide(answer)["status"], "unknown")
        self.assertEqual(answer["collection"]["filing"]["message"], filing.PRECON_UNKNOWN)
        self.assertNotIn("private fixture error", json.dumps(answer))
        self.assertIsNotNone(self.backend.load().deck(answer["deck"]["id"]))
        self.assertEqual(self.writes_made(), 1)

    def test_response_and_advice_use_actual_after_without_a_later_load(self):
        real = api.saving.apply_op
        patchers = []

        def save(*args, **kwargs):
            after, summary = real(*args, **kwargs)
            patcher = mock.patch.object(self.backend, "load", side_effect=AssertionError("later snapshot"))
            patcher.start()
            patchers.append(patcher)
            return after, summary

        try:
            with mock.patch.object(api.saving, "apply_op", side_effect=save):
                answer = self.fresh()
            self.assertEqual(self.guide(answer)["status"], "ready")
        finally:
            for patcher in patchers:
                patcher.stop()

    def test_tampered_sha_space_identity_or_absence_proof_is_unknown(self):
        answer = self.fresh()
        after = self.backend.load()
        extra = self.writes[-1][3].extra
        profile = next(p for p in ROLES["profiles"] if p["id"] == "user2")
        for proof in (None, {}, {**extra["created_deck"], "sha256": "0" * 64},
                      {**extra["created_deck"], "space": "home"},
                      {**extra["created_deck"], "id": "casual/hidden-home"},
                      {**extra["created_deck"], "was_absent": 1}):
            with self.subTest(proof=proof):
                result = filing.after_precon(after, "user2", profile, extra["added_printings"], 4, proof)
                self.assertEqual(result["status"], "unknown")
                self.assertFalse(any(d["kind"] == "storage" for d in result["destinations"]))
                self.assertNotIn("hidden-home", json.dumps(result))

    def test_assembled_new_holder_can_use_residual_old_stock_without_inventing_it(self):
        self.set_owned(2)
        profile = next(p for p in ROLES["profiles"] if p["id"] == "user2")
        made = api.plan_add("user2", "Small_TST", "Assembly", None, profile, "User2", capture_filing=True)
        assembled = json.dumps({"version": "target", "sections": {"Deck": ["6 Llanowar Elves"]}})
        text = made["text"].replace("\n\n## Decklist", f"\n- **Assembled:** {assembled}\n\n## Decklist")
        op = inventory.Op("precon.add", {**made["op"].params, "text": text})
        after, summary = api.saving.apply_op(op, profile, made["message"], made["refused"])
        result = filing.after_precon(after, "user2", profile, summary.extra["added_printings"], 4,
                                     summary.extra["created_deck"])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(sum(d["quantity"] for d in result["destinations"]), 4)
        # A proof with the same post-save deck but less physical stock cannot imply free cards.
        with mock.patch.object(filing.pool, "load_pool", return_value=pool.Pool(
                Counter({"Llanowar Elves": 5}), {}, [pool.InUse(result["destinations"][0]["deck"]["id"],
                "Assembly", "built", Counter({"Llanowar Elves": 6}))], space="user2")):
            unknown = filing.after_precon(after, "user2", profile, summary.extra["added_printings"], 4,
                                          summary.extra["created_deck"])
        self.assertEqual(unknown["status"], "unknown")

    def test_missing_new_built_holder_is_unknown_even_when_pool_reports_no_warning(self):
        answer = self.fresh()
        after = self.backend.load()
        extra = self.writes[-1][3].extra
        profile = next(p for p in ROLES["profiles"] if p["id"] == "user2")
        with mock.patch.object(filing.pool, "load_pool", return_value=pool.Pool(
                Counter({"Llanowar Elves": 6}), {}, [], space="user2")):
            result = filing.after_precon(after, "user2", profile, extra["added_printings"], 4,
                                         extra["created_deck"])
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["destinations"], [{"kind": "unknown", "row": 0, "quantity": 4}])
        self.assertIsNotNone(after.deck(answer["deck"]["id"]))

    def marker_precon(self, physical_quantity):
        self.set_owned(0)
        _write(self.box.root / paths.collection("user2"),
               HEADER + f"Elvish Mystic,cmm,648,nonfoil,{physical_quantity},,,\n")
        profile = next(p for p in ROLES["profiles"] if p["id"] == "user2")
        made = api.plan_add("user2", "Small_TST", "Markers", None, profile, "User2", capture_filing=True)
        mapping = {"for": "Llanowar Elves", "using": "Elvish Mystic", "qty": 4}
        installed = json.dumps({"target": [mapping], "built": {"version": "target", "cards": [mapping]}})
        text = made["text"].replace("\n\n## Decklist", f"\n- **Stand-ins:** {installed}\n\n## Decklist")
        after, summary = api.saving.apply_op(inventory.Op("precon.add", {**made["op"].params, "text": text}),
                                             profile, made["message"], made["refused"])
        return made, after, summary, profile

    def test_installed_standins_stay_held_while_new_real_cards_are_suggested(self):
        made, after, summary, profile = self.marker_precon(4)
        result = filing.after_precon(after, "user2", profile, summary.extra["added_printings"], 4,
                                     summary.extra["created_deck"])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["destinations"][0]["quantity"], 4)
        with inventory.pinned(after):
            held = next(h for h in pool.load_pool("user2").in_use if h.id == made["deck_id"])
        self.assertEqual(held.cards, Counter({"Elvish Mystic": 4}))

    def test_short_nonadded_standin_stock_is_unknown_without_changing_saved_recipe(self):
        made, after, summary, profile = self.marker_precon(2)
        with inventory.pinned(after):
            found = pool.load_pool("user2")
        self.assertEqual(found.warnings, [])
        self.assertEqual(found.owned["Elvish Mystic"], 2)
        self.assertEqual(next(h.cards for h in found.in_use if h.id == made["deck_id"]),
                         Counter({"Elvish Mystic": 4}))
        result = filing.after_precon(after, "user2", profile, summary.extra["added_printings"], 4,
                                     summary.extra["created_deck"])
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["destinations"], [{"kind": "unknown", "row": 0, "quantity": 4}])
        self.assertEqual(self.writes_made(), 1)

    def test_all_plain_basics_keep_collection_none_and_create_only_the_deck(self):
        self.listed("Basics_TST", {"data": {"name": "Basics", "code": "TST", "type": "Theme Deck",
                    "mainBoard": [support.card("Forest", "FDN", "280", 20)], "sideBoard": []}}, "Theme Deck")
        answer = self.add("Basics_TST", title="Basics")
        self.assertIsNone(answer["collection"])
        self.assertTrue(answer["deck"]["created"])
        self.assertEqual(self.writes_made(), 1)


class PreconTokenFilingTests(PreconTokensTestCase):

    def test_confirmed_tokens_are_separate_from_card_printing_destinations(self):
        answer = self.add_tokens(tokens_choices=[{"source_row": 1, "front": "Dinosaur", "quantity": 2},
                                                {"source_row": 2, "front": "", "quantity": 0}])
        guide = answer["collection"]["filing"]
        self.assertEqual(answer["tokens"], {"cards": 2, "rows": 1})
        self.assertEqual(guide["status"], "ready")
        self.assertEqual(sum(row["quantity"] for row in guide["added"]), 5)
        self.assertEqual(sum(item["quantity"] for item in guide["destinations"]), 5)
        self.assertNotIn("Dinosaur", [row["name"] for row in guide["added"]])
        self.assertEqual(self.writes_made(), 1)
