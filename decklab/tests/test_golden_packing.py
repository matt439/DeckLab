"""Compatibility ignores only documented additive/default packing projections."""
import copy
import hashlib
import json
import unittest

from decklab.tests import golden_packing


def product_summary(**changes):
    return {"id": "product/box/deck", "source": "magic/products/box.csv", "read_only": True,
            "holder_sha256": "a" * 64, "card_count": 20, "kit": {"sleeves": "keep this value"}, **changes}


def picker(**changes):
    return {"tokens_sha256": None, "expect": "a" * 64,
            "product": {"stem": "box", "status_sha256": "a" * 64}, "editable": True, "written": False,
            "lines": [], "choices": [{"row": 0, "front": "Zombie", "back": "", "set": "", "number": "",
                                        "quantity": 3, "free": 1, "packed": 0}], **changes}


def physical():
    return {"available": True, "reason": None, "can_take_apart": True, "why_not": None,
            "sha256": "b" * 64, "source": "built-list", "version": "target", "card_count": 3,
            "sections": {"Deck": [{"kind": "card", "name": "Opt", "quantity": 2, "basic": False, "for": None},
                                  {"kind": "marker", "name": None, "quantity": 1, "basic": None, "for": "Forest"}]}}


def box_participant(**changes):
    rows = physical()
    text = json.dumps({"version": rows["version"], "sections": rows["sections"]}, ensure_ascii=False,
                      sort_keys=True, separators=(",", ":"))
    check = {"expect": rows["sha256"], "recipe_sha256": hashlib.sha256(text.encode()).hexdigest(),
             "checked_on": None, "editable": True, "why_not": None}
    return {"id": "casual/a", "take_apart": rows, "box_check": {**check, **changes},
            "steps": [{"need": 2, "keep": 1, "storage": 1, "missing": 0}]}


def box_art(**changes):
    return {"name": "Opt", "mana_cost": "{U}", "cmc": 1.0, "type_line": "Instant", "oracle_text": "Scry 1.",
            "colors": ["U"], "color_identity": ["U"], "roles": [], "produced_mana": [], "img": None,
            "img_small": None, "power": None, "toughness": None, "loyalty": None, "defense": None, **changes}


def ordinary_summary(**changes):
    return {"id": "casual/a", "kind": "casual", "space": "home", "read_only": False,
            "source": "casual/a", **changes}


class GoldenPackingTests(unittest.TestCase):
    def test_default_box_receipts_and_name_only_art_drop_only_at_exact_paths_without_mutation(self):
        base = {"assembly": {"a": {"decks": [box_participant()], "box_check_cards": {"Opt": box_art()},
                                   "cards": {"Opt": {"name": "Keep existing card metadata"}}, "totals": {"missing": 0}}},
                "deck_view": {"a@target": {"summary": ordinary_summary(), "box_checked_on": None,
                                           "owned": {"missing": 1}}}}
        original = {**base, "by_viewer": {"matt": copy.deepcopy(base)},
                    "unrelated": {"box_check": box_participant()["box_check"], "box_check_cards": {"Opt": box_art()},
                                  "box_checked_on": None}}
        before = copy.deepcopy(original)
        result = golden_packing.normalise(original)
        self.assertEqual(original, before)
        self.assertEqual(result["unrelated"], before["unrelated"])
        for mine in (result, result["by_viewer"]["matt"]):
            plan = mine["assembly"]["a"]
            self.assertEqual(plan["decks"], [{"id": "casual/a", "steps": box_participant()["steps"]}])
            self.assertNotIn("box_check_cards", plan)
            self.assertEqual(plan["cards"], base["assembly"]["a"]["cards"])
            self.assertEqual(plan["totals"], {"missing": 0})
            self.assertEqual(mine["deck_view"]["a@target"], {"summary": ordinary_summary(), "owned": {"missing": 1}})

    def test_written_nondefault_malformed_or_unbound_box_metadata_remains_visible(self):
        bad = [box_participant(checked_on="2026-10-27"), box_participant(editable=False),
               box_participant(why_not="Cannot record"), box_participant(expect="bad"),
               box_participant(expect="c" * 64), box_participant(recipe_sha256="bad"),
               box_participant(recipe_sha256="c" * 64), box_participant(unexpected="keep")]
        for key, value in (("available", False), ("sha256", "c" * 64), ("version", "future"),
                           ("card_count", True), ("card_count", 4), ("source", "invented"),
                           ("reason", "Cannot read"), ("sections", {"Deck": []})):
            participant = box_participant()
            participant["take_apart"][key] = value
            bad.append(participant)
        for participant in bad:
            with self.subTest(participant=participant):
                original = {"assembly": {"a": {"decks": [participant], "box_check_cards": {"Opt": box_art()}}}}
                found = golden_packing.normalise(original)["assembly"]["a"]
                self.assertEqual(found["decks"][0]["box_check"], participant["box_check"])
                self.assertEqual(found["box_check_cards"], {"Opt": box_art()})

    def test_art_map_with_wrong_names_unknown_facts_or_shape_remains_comparable(self):
        for art in (None, [], {"Forest": box_art(name="Forest")}, {"Opt": None},
                    {"Opt": box_art(name="Forest")}, {"Opt": box_art(quantity=3)},
                    {"Opt": box_art(cmc=True)}, {"Opt": box_art(cmc=float("inf"))},
                    {"Opt": box_art(colors="U")}, {"Opt": box_art(faces=[])},
                    {"Opt": box_art(faces=[{"name": "Opt"}])}):
            with self.subTest(art=art):
                original = {"assembly": {"a": {"decks": [box_participant()], "box_check_cards": art}}}
                self.assertEqual(golden_packing.normalise(original)["assembly"]["a"]["box_check_cards"], art)
        original = {"assembly": {"a": {"decks": [], "box_check_cards": {}}}}
        self.assertEqual(golden_packing.normalise(original), original)

    def test_only_null_date_on_actual_ordinary_home_page_is_omitted(self):
        for value, summary in (("2026-10-27", ordinary_summary()), ("invalid", ordinary_summary()),
                               (False, ordinary_summary()), (None, ordinary_summary(space="user2")),
                               (None, ordinary_summary(read_only=True)), (None, ordinary_summary(id="product/box")),
                               (None, ordinary_summary(source="casual/other")), (None, None)):
            with self.subTest(value=value, summary=summary):
                original = {"deck_view": {"x": {"summary": summary, "box_checked_on": value}}}
                self.assertEqual(golden_packing.normalise(original), original)

    def test_exact_api_paths_drop_projections_but_preserve_allocations_counts_and_input(self):
        base = {"assembly": {"a": {"decks": [{"id": "casual/a", "take_apart": {"card_count": 3},
                                               "steps": [{"need": 4, "keep": 1, "storage": 2, "missing": 1}]}],
                                      "rows": [{"name": "Opt", "missing": 1, "held_elsewhere": [
                                          {"id": "product/box/deck", "quantity": 2, "intact_product": {"id": "box"}}]}]}},
                "deck_view": {"product/box/deck@target": {"summary": product_summary(),
                    "tokens": {"needs": [{"name": "Zombie", "state": "none"}], "packed": picker()}}}}
        original = {**base, "by_viewer": {"matt": copy.deepcopy(base)},
                    "unrelated": {"take_apart": "keep", "intact_product": "keep", "packed": picker(),
                                  "holder_sha256": "a" * 64}}
        before = copy.deepcopy(original)
        found = golden_packing.normalise(original)
        self.assertEqual(original, before)
        self.assertEqual(found["unrelated"], before["unrelated"])
        for mine in (found, found["by_viewer"]["matt"]):
            plan = mine["assembly"]["a"]
            self.assertEqual(plan["decks"], [{"id": "casual/a", "steps": [{"need": 4, "keep": 1, "storage": 2, "missing": 1}]}])
            self.assertEqual(plan["rows"], [{"name": "Opt", "missing": 1, "held_elsewhere": [{"id": "product/box/deck", "quantity": 2}]}])
            page = mine["deck_view"]["product/box/deck@target"]
            self.assertEqual(page["summary"], {k: v for k, v in product_summary().items() if k != "holder_sha256"})
            self.assertEqual(page["tokens"], {"needs": [{"name": "Zombie", "state": "none"}]})

    def test_written_nonempty_malformed_and_unrecognised_picker_data_stays_comparable(self):
        values = [picker(written=True), picker(lines=[{"text": "1 Zombie"}]), picker(error="Cannot read"),
                  picker(unexpected="keep"), picker(expect="not a hash"), picker(editable="yes"),
                  picker(product={"stem": "other", "status_sha256": "a" * 64}), picker(tokens_sha256="bad"),
                  picker(expect="b" * 64, product={"stem": "box", "status_sha256": "b" * 64})]
        for choice_change in ({"packed": 1}, {"free": 4}, {"row": True}, {"row": -1}, {"front": ""}):
            value = picker()
            value["choices"][0].update(choice_change)
            values.append(value)
        for value in values:
            with self.subTest(value=value):
                original = {"deck_view": {"x": {"summary": product_summary(), "tokens": {"packed": value}}}}
                self.assertEqual(golden_packing.normalise(original)["deck_view"]["x"]["tokens"]["packed"], value)

    def test_unrelated_or_forged_product_summaries_keep_their_receipts_and_pickers(self):
        for summary in (product_summary(id="casual/a"), product_summary(source="magic/products/other.csv"),
                        product_summary(source="magic/decks/casual/a.md"), product_summary(read_only=False),
                        product_summary(holder_sha256="bad")):
            original = {"deck_view": {"x": {"summary": summary, "tokens": {"packed": picker()}}}}
            found = golden_packing.normalise(original)["deck_view"]["x"]
            self.assertEqual(found["summary"]["holder_sha256"], summary["holder_sha256"])
            self.assertEqual(found["tokens"]["packed"], picker())
