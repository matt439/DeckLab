"""A card's Game Changer flag and known two-card combos for the card viewer (E9-S37): combos.with_card() over the
two-card list, and GET /api/cards/combos, public card data with no deck, space or network. Fixture data only."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import combos
from decklab.lib.api import card_combos
from decklab.lib.api.card_combos import card_combos as combos_view
from decklab.lib.api.common import ApiError
from decklab.lib.feature_routes import ACCESS
from decklab.tests.test_cards import LLANOWAR, FixtureIndex
from decklab.tests.test_combos import ComboTestCase
from decklab.tests.test_server import ServerTestCase

RHYSTIC = "53236dd7-845a-444c-96d5-f41ed7325d8f"     # the fixture index's one Game Changer
TIMESTAMP = "2026-11-01T03:14:00+00:00"


def combo(combo_id, first, second, cls="infinite", standalone=True, results=("Infinite colored mana",),
          commander=(False, False)):
    return {"id": combo_id, "url": combos.COMBO_URL.format(id=combo_id),
            "cards": [{"oracle_id": first[0], "name": first[1], "must_be_commander": commander[0]},
                      {"oracle_id": second[0], "name": second[1], "must_be_commander": commander[1]}],
            "results": list(results), "class": cls, "standalone": standalone}


def write_list(path, entries, timestamp=TIMESTAMP):
    path.write_text(json.dumps({"format": combos.FORMAT, "source": combos.EXPORT_URL, "timestamp": timestamp,
                                "version": "7.3.0", "count": len(entries), "combos": entries}), encoding="utf-8")


class WithCardTests(ComboTestCase):
    def setUp(self):
        super().setUp()
        self.write_export()
        combos.reduce_export(log=self.log.append)

    def test_each_combo_the_card_is_a_piece_of_with_its_place(self):
        found = combos.with_card("oracle-8")
        self.assertEqual(found["timestamp"], "2026-10-21T03:14:00.560664+00:00")
        self.assertEqual(found["version"], "7.3.0")
        self.assertEqual([(m["id"], m["piece"]) for m in found["matches"]], [("9-8", 1), ("7-8", 1)])   # by name
        self.assertEqual([m["cards"][0]["must_be_commander"] for m in found["matches"]], [False, True])
        self.assertEqual([(m["id"], m["piece"]) for m in combos.with_card("oracle-1")["matches"]], [("1-2", 0)])

    def test_most_serious_first_as_find_orders_them(self):
        path = self.tmp / "many.json"
        write_list(path, [combo("a", ("x", "X"), ("p", "Payoff"), cls="infinite", standalone=False),
                          combo("b", ("x", "X"), ("w", "Wincon"), cls="win"),
                          combo("c", ("y", "Y"), ("x", "X"), cls="mass_land_denial", standalone=False)])
        found = combos.with_card("x", path)["matches"]
        self.assertEqual([(m["id"], m["piece"], combos.bracket_floor(m)) for m in found],
                         [("c", 1, 4), ("b", 0, 3), ("a", 0, 1)])

    def test_a_card_in_no_combo_and_a_bad_id_have_none(self):
        for oracle_id in ("oracle-404", None, 7, ""):
            with self.subTest(oracle_id=oracle_id):
                self.assertEqual(combos.with_card(oracle_id)["matches"], [])

    def test_the_list_is_left_as_it_was(self):
        before = json.dumps(combos.load()["combos"])
        combos.with_card("oracle-8")["matches"][0]["piece"] = 9
        self.assertEqual(json.dumps(combos.load()["combos"]), before)
        self.assertNotIn("piece", combos.load()["combos"][0])

    def test_an_unreadable_list_raises_never_none(self):
        combos.TWO_CARD_FILE.unlink()
        with self.assertRaises(combos.ComboListError):
            combos.with_card("oracle-8")
        combos.TWO_CARD_FILE.write_text("{not json", encoding="utf-8")
        with self.assertRaises(combos.ComboListError):
            combos.with_card("oracle-8")


class ComboListFiles:
    """A temporary two-card list for the endpoint."""

    def use_list(self):
        self.combo_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.combo_dir, True)
        for name, value in (("TWO_CARD_FILE", self.combo_dir / "two_card.json"),
                            ("_cache", {"key": None, "data": None})):
            patcher = mock.patch.object(combos, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        return combos.TWO_CARD_FILE


class EndpointTests(ComboListFiles, FixtureIndex):
    def setUp(self):
        self.path = self.use_list()

    def test_a_game_changer_and_its_combos_with_date_credit_and_bracket_floor(self):
        write_list(self.path, [
            combo("r-c", (RHYSTIC, "Rhystic Study"), ("c", "Leader"), cls="win", commander=(False, True),
                  results=("Win the game", "Infinite card draw", "Infinite mana", "Draw the game")),
            combo("p-r", ("p", "Payoff"), (RHYSTIC, "Rhystic Study"), standalone=False, commander=(False, True)),
            combo("l-x", (LLANOWAR, "Llanowar Elves"), ("x", "Other"))])
        answer = combos_view("rhystic study")
        self.assertEqual({k: answer[k] for k in ("name", "game_changer", "checked", "date", "version", "total")},
                         {"name": "Rhystic Study", "game_changer": True, "checked": True, "date": "2026-11-01",
                          "version": "7.3.0", "total": 2})
        self.assertEqual(answer["source_url"], "https://commanderspellbook.com/")
        self.assertIn("Commander Spellbook", answer["credit"])
        self.assertEqual(answer["combos"][0], {
            "id": "r-c", "url": "https://commanderspellbook.com/combo/r-c/", "class": "win", "standalone": True,
            "results": ["Win the game", "Infinite card draw", "Infinite mana"], "more_results": 1,
            "bracket_floor": 3, "must_be_commander": False,
            "others": [{"name": "Leader", "must_be_commander": True}]})
        second = answer["combos"][1]
        self.assertEqual((second["id"], second["bracket_floor"], second["must_be_commander"], second["others"]),
                         ("p-r", 1, True, [{"name": "Payoff", "must_be_commander": False}]))
        plain = combos_view("Llanowar Elves")
        self.assertEqual((plain["game_changer"], plain["total"], plain["combos"][0]["others"][0]["name"]),
                         (False, 1, "Other"))

    def test_capped_at_25_with_the_total(self):
        write_list(self.path, [combo(f"l-{i:02}", (LLANOWAR, "Llanowar Elves"), (f"o{i}", f"Other {i:02}"))
                               for i in range(31)])
        answer = combos_view("Llanowar Elves")
        self.assertEqual((answer["total"], len(answer["combos"])), (31, card_combos.MAX_SHOWN))
        self.assertEqual(card_combos.MAX_SHOWN, 25)

    def test_none_is_said_only_when_the_list_was_read(self):
        write_list(self.path, [combo("l-x", (LLANOWAR, "Llanowar Elves"), ("x", "Other"))])
        self.assertEqual((combos_view("Rhystic Study")["checked"], combos_view("Rhystic Study")["combos"]), (True, []))

    def test_a_missing_or_unreadable_list_says_combos_werent_checked(self):
        for content in (None, "{damaged", json.dumps({"format": 1, "timestamp": TIMESTAMP, "combos": []})):
            with self.subTest(content=content):
                combos._cache.update(key=None, data=None)
                if content is None:
                    self.path.unlink(missing_ok=True)
                else:
                    self.path.write_text(content, encoding="utf-8")
                answer = combos_view("Rhystic Study")
                self.assertEqual(set(answer), {"name", "game_changer", "checked", "reason"})
                self.assertEqual((answer["checked"], answer["game_changer"]), (False, True))
                self.assertIn("weren't checked", answer["reason"])
                self.assertNotIn(str(self.combo_dir), answer["reason"])

    def test_no_deck_space_inventory_or_network_is_read(self):
        write_list(self.path, [combo("l-x", (LLANOWAR, "Llanowar Elves"), ("x", "Other"))])
        with mock.patch("decklab.lib.inventory.current", side_effect=AssertionError("inventory read")), \
                mock.patch("decklab.lib.decks.find_summary", side_effect=AssertionError("deck read")), \
                mock.patch("decklab.lib.api.guard.viewer", side_effect=AssertionError("viewer read"), create=True), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")):
            self.assertEqual(combos_view("Llanowar Elves")["total"], 1)
        self.assertEqual(ACCESS[("GET", "cards/combos")], "open")

    def test_bad_and_unknown_names(self):
        for name, status in (("", 400), (None, 400), ("x" * 151, 400), ("a\nb", 400), ("Nonsense Card", 404)):
            with self.subTest(name=name), self.assertRaises(ApiError) as caught:
                combos_view(name)
            self.assertEqual(caught.exception.status, status)


class HttpTests(ComboListFiles, ServerTestCase):
    def setUp(self):
        self.path = self.use_list()

    def test_open_to_a_page_naming_nobody_and_strict_about_its_query(self):
        write_list(self.path, [combo("l-x", (LLANOWAR, "Llanowar Elves"), ("x", "Other"))])
        code, _headers, body = self.request("GET", "/api/cards/combos?name=llanowar%20elves", script=False)
        self.assertEqual(code, 200, body[:300])
        answer = json.loads(body)
        self.assertEqual((answer["name"], answer["checked"], answer["total"]), ("Llanowar Elves", True, 1))
        self.assertError("/api/cards/combos?name=Nonsense%20Card", 404)
        self.assertError("/api/cards/combos?name=x&space=home", 400)
        self.assertError("/api/cards/combos?name=Llanowar%20Elves", 405, method="POST", body=b"{}")


if __name__ == "__main__":
    unittest.main()
