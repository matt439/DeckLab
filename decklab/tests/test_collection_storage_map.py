"""Synthetic collection snapshots, storage filing and physical audit receipts."""
import json
import unittest
from collections import Counter
from datetime import datetime
from unittest import mock

from decklab.lib import inventory, pool, state, tokens
from decklab.lib.api import collection_storage_map as storage_map
from decklab.lib.api import collection_storage_sections as sections
from decklab.lib.api import guard
from decklab.tests.test_api import COLLECTION, _write
from decklab.tests.test_collection_edit import CollectionEditTestCase
from decklab.tests.test_server import WRITE, ServerTestCase


class FilingTests(unittest.TestCase):
    def test_dividers_follow_front_face_artifact_and_land_filing(self):
        cases = (
            ({"type_line": "Creature — Human", "colors": ["W"]}, "White creatures"),
            ({"type_line": "Adventure // Creature", "colors": ["B"],
              "faces": [{"type_line": "Creature — Human", "colors": ["W"]},
                        {"type_line": "Sorcery — Adventure", "colors": ["B"]}]}, "White creatures"),
            ({"type_line": "Legendary Artifact Creature — Golem", "colors": ["W"]}, "Artifact creatures"),
            ({"type_line": "Artifact — Equipment", "colors": ["G"]}, "Artifacts"),
            ({"type_line": "Artifact Land", "produced_mana": ["W", "U"], "color_identity": ["W"]},
             "Multicolour lands"),
            ({"type_line": "Land", "produced_mana": ["C"], "color_identity": ["W"]}, "White lands"),
            ({"type_line": "Instant", "colors": [], "color_identity": ["U"]}, "Colourless spells"),
            (None, "Other cards"),
        )
        for card, label in cases:
            with self.subTest(label=label, card=card):
                self.assertEqual(sections.DIVIDERS[sections._divider(card)][0], label)


class StorageMapTests(CollectionEditTestCase):
    def section(self, label="Green creatures", space="home", place=None):
        return next(section for section in storage_map.view(space)["sections"]
                    if section["label"] == label and (place is None or section["place"] == place))

    def review(self, label="Green creatures", space="home", place=None):
        return storage_map.view(space, self.section(label, space, place)["id"])

    def record(self, review, counts=None, extra=0, profile="matt", **overrides):
        data = {"space": review["space"], "section": review["section"]["id"], "expect": review["expect"],
                "counts": {row["key"]: row["quantity"] for row in review["rows"]} if counts is None else counts,
                "extra": extra, **overrides}
        return self.call(storage_map.record, profile, **data)

    def test_map_uses_actual_loose_quantities_and_recorded_section(self):
        _write(self.box.magic / "collection.csv", COLLECTION + "Aerie Mystics,con,1,nonfoil,9,NM,en,\n"
               "Forest,fdn,280,foil,7,NM,en,full art\n")
        _write(self.box.magic / "locations.csv", "set,collector_number,finish,location\ncon,1,nonfoil,Row 2\n")
        elk = pool.InUse("casual/piled", "Hidden title", "built", Counter({"Llanowar Elves": 2}))
        loan = pool.InUse("loan/fixture", "Hidden borrower", "lent out", Counter({"Llanowar Elves": 1}),
                          recorded=Counter({("Llanowar Elves", "fdn", "227", "nonfoil"): 1}))
        different = pool.Pool(Counter({"Llanowar Elves": 70}), {"Llanowar Elves": [("in the mail", 65)]}, [elk, loan])
        with mock.patch.object(pool, "load_pool", return_value=different):
            answer = storage_map.view()
            self.assertTrue(answer["ready"])
            self.assertEqual(answer["containers"],
                             [{"name": "Storage box", "sections": ["Row 1", "Row 2", "Row 3", "Row 4"]}])
            populated = {section["label"]: (section["quantity"], section["place"])
                         for section in answer["sections"] if section["quantity"]}
            self.assertEqual(populated, {"Green creatures": (3, "Row 1"), "White creatures": (9, "Row 2"),
                                         "Artifacts": (1, "Row 2")})
            self.assertTrue(any(item["quantity"] == 7 and "basic" in item["label"].lower()
                                for item in answer["excluded"]))
            green = self.review()
        self.assertEqual({row["key"]: row["quantity"] for row in green["rows"]},
                         {"fdn|227|nonfoil": 2, "cmm|648|nonfoil": 1})
        self.assertNotIn("Hidden", str(green))
        self.assertNotIn("in the mail", str(answer))

    def test_configured_sections_keep_the_setup_order_including_empty_ones(self):
        record = {"default": "box", "containers": [
            {"id": "box", "name": "Box", "kind": "box", "sections": ["Back", "Front"],
             "order": "colour-type", "holds": {"Front": "creatures"}},
            {"id": "binder", "name": "Binder", "kind": "binder", "sections": [], "order": "set"},
        ]}
        self.box.state.space_storage_put("home", record, 0, state.Actor("matt", "Matt", "home"), "Set storage")
        answer = storage_map.view()
        self.assertEqual(answer["containers"], [{"name": "Box", "sections": ["Back", "Front"]},
                                                {"name": "Binder", "sections": []}])
        self.assertFalse(any(item["place"] == "Back" for item in answer["sections"]))

    def test_double_faced_tokens_count_once_and_packed_copies_are_excluded(self):
        token = dict.fromkeys(tokens.FIELDS, "")
        token.update(front="Goblin", back="Treasure", quantity="5", notes="Fixture note")
        _write(self.box.magic / "tokens.csv", ",".join(tokens.FIELDS) + "\n"
               + ",".join(token[field] for field in tokens.FIELDS) + "\n")
        holds = {"built": {"rows": {0: 2}, "unmatched": []}}
        with mock.patch.object(tokens.reserve, "holds", return_value=holds):
            review = self.review("Token cards")
        self.assertEqual((review["section"]["quantity"], review["section"]["place"]), (3, "Row 4"))
        self.assertEqual([row["quantity"] for row in review["rows"]], [3])
        self.assertIn("Goblin", review["rows"][0]["name"])
        self.assertIn("Treasure", review["rows"][0]["name"])
        self.assertNotIn("Fixture note", str(review))

    def test_saved_discrepancies_use_exact_rows_without_inventory_writes(self):
        _write(self.box.magic / "collection.csv", COLLECTION + "Elvish Mystic,cmm,648,foil,2,NM,en,\n")
        with mock.patch.object(pool, "load_pool", return_value=pool.Pool(Counter(), {}, [])):
            review = self.review()
            before = self.magic_files()
            counts = {row["key"]: row["quantity"] for row in review["rows"]}
            counts.update({"cmm|648|foil": 0, "cmm|648|nonfoil": 3})
            with self.as_("user1"):  # the other authorised home profile can count this section
                result = self.record(review, counts, extra=1, profile="user1")["section"]["audit"]
            reread = self.review()["section"]["audit"]
            adjacent = self.section("White creatures")["audit"]
        self.assertEqual(reread, result)
        self.assertTrue(reread["current"])
        self.assertIsNotNone(datetime.fromisoformat(reread["audited_at"]).tzinfo)
        self.assertEqual({key: reread[key] for key in ("expected", "observed", "missing", "surplus", "extra",
                                                       "mismatch_rows")},
                         {"expected": 8, "observed": 9, "missing": 2, "surplus": 2, "extra": 1,
                          "mismatch_rows": 2})
        self.assertEqual({(row["set"], row["collector_number"], row["finish"]): (row["expected"], row["observed"])
                          for row in reread["differences"]},
                         {("cmm", "648", "foil"): (2, 0), ("cmm", "648", "nonfoil"): (1, 3)})
        self.assertIsNone(adjacent)
        self.assertEqual(self.magic_files(), before)
        self.assertEqual(self.writes, [])

    def test_invalid_counts_do_not_mark_the_section_audited(self):
        review = self.review()
        exact = {row["key"]: row["quantity"] for row in review["rows"]}
        key = next(iter(exact))
        for counts, extra in (({}, 0), ({**exact, "fake": 1}, 0), ({**exact, key: True}, 0),
                              ({**exact, key: -1}, 0), ({**exact, key: 0.5}, 0), ({**exact, key: "1"}, 0),
                              (exact, -1), (exact, True), (exact, 2**53)):
            with self.subTest(counts=counts, extra=extra):
                self.assertApiError(400, self.record, review, counts, extra)
        self.assertIsNone(self.section()["audit"])

    def test_an_empty_configured_divider_can_record_unlisted_cards(self):
        review = self.review("White creatures")
        self.assertEqual((review["section"]["quantity"], review["rows"]), (0, []))
        result = self.record(review, extra=4)["section"]["audit"]
        self.assertEqual((result["observed"], result["mismatch_rows"], result["extra"]), (4, 0, 4))

    def test_revision_blocks_a_second_audit_from_the_same_receipt(self):
        review = self.review()
        saved = self.record(review)["section"]["audit"]
        self.assertApiError(409, self.record, review, extra=4)
        self.assertEqual(self.review()["section"]["audit"], saved)

    def test_fresh_snapshot_rejects_quantity_change_even_in_a_pinned_request(self):
        review = self.review()
        self.record(review)
        open_again = self.review()
        with inventory.pinned():
            _write(self.box.magic / "collection.csv", COLLECTION.replace("227,nonfoil,5", "227,nonfoil,6"))
            self.assertApiError(409, self.record, open_again)
        audit = self.section()["audit"]
        self.assertFalse(audit["current"])
        self.assertEqual(audit["observed"], open_again["section"]["quantity"])

    def test_same_total_printing_swap_marks_previous_audit_out_of_date(self):
        with mock.patch.object(pool, "load_pool", return_value=pool.Pool(Counter(), {}, [])):
            review = self.review()
            saved = self.record(review)["section"]["audit"]
            _write(self.box.magic / "collection.csv", COLLECTION.replace("227,nonfoil,5", "227,foil,5"))
            reloaded = self.review()
        self.assertEqual(reloaded["section"]["quantity"], saved["expected"])
        self.assertFalse(reloaded["section"]["audit"]["current"])
        self.assertIn("fdn|227|foil", {row["key"] for row in reloaded["rows"]})

    def test_a_manually_filed_empty_divider_keeps_its_last_audit(self):
        location_file = self.box.magic / "locations.csv"
        _write(location_file, "set,collector_number,finish,location\nfdn,227,nonfoil,Row 3\n")
        review = self.review(place="Row 3")
        self.record(review)
        location_file.unlink()
        after = self.review(place="Row 3")
        self.assertEqual(after["section"]["id"], review["section"]["id"])
        self.assertEqual((after["section"]["quantity"], after["rows"]), (0, []))
        self.assertFalse(after["section"]["audit"]["current"])

    def test_unreadable_location_source_cannot_be_replaced_with_a_default_guess(self):
        _write(self.box.magic / "locations.csv", "invalid,header\n")
        self.assertApiError(409, storage_map.view, contains="locations")

    def test_publishing_collection_does_not_publish_section_audits(self):
        home = self.review()
        self.record(home)
        with (
            self.as_("user2"),
            mock.patch.object(guard, "public_spaces", return_value=frozenset({"home"})),
            mock.patch.object(state.store(), "collection_audits", side_effect=AssertionError("private read")),
        ):
            self.assertApiError(403, storage_map.view, "home")
            self.assertApiError(403, storage_map.view, "home", home["section"]["id"])
            self.assertApiError(403, self.record, home, profile="user2")
        with self.as_("matt"):
            self.assertApiError(403, storage_map.view, "user2")  # administrative role is scoped to home
        with self.as_("user2"):
            own = self.section("No storage location", "user2")
            self.assertEqual(own["quantity"], 2)
            self.assertFalse(own["auditable"])
            self.assertIsNone(own["audit"])

    def test_missing_audit_migration_cannot_record_a_previously_open_section(self):
        review = self.review()
        self.box.state.collection_audits_ready = False
        view = storage_map.view()
        self.assertFalse(view["ready"])
        self.assertApiError(409, self.record, review)


class StorageMapHttpTests(ServerTestCase):
    def test_named_same_origin_audit_round_trip(self):
        endpoint = "/api/collection/storage-map"
        named = {"X-Deck-Lab-Viewer": "matt"}
        code, _, _ = self.request("GET", endpoint, script=False)
        self.assertEqual(code, 403)
        map_data = self.get_json(endpoint, headers=named)
        section = next(item for item in map_data["sections"] if item["label"] == "Green creatures")
        detail_url = endpoint + "?section=" + section["id"]
        review = self.get_json(detail_url, headers=named)
        observed = {row["key"]: row["quantity"] for row in review["rows"]}
        body = json.dumps({"space": "home", "profile": "matt", "section": section["id"], "expect": review["expect"],
                           "counts": observed, "extra": 1}).encode()
        write = {**named, **WRITE}
        self.assertError(endpoint, 403, "POST", body, {**write, "Origin": "http://untrusted.example"})
        saved = self.get_json(endpoint, method="POST", headers={**write, "Origin": f"http://127.0.0.1:{self.port}"},
                              body=body)
        loaded = self.get_json(detail_url, headers=named)
        self.assertEqual(loaded["section"], saved["section"])
        self.assertEqual(loaded["section"]["audit"]["observed"], section["quantity"] + 1)
