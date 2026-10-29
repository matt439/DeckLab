"""Api decks tests; shared fixtures remain in test_api."""
import hashlib
import json
import unittest
import sys
from pathlib import Path, PureWindowsPath
from unittest import mock
from decklab.lib import accessories, api, cards, config, decks, inventory, pool, tokens
from decklab.lib.inventory import rules
from decklab.tests import pre_db
from decklab.tests.test_api import (
    ApiTestCase, COLLECTION, FIXTURES, GRUUL, _write,
)
from decklab.tests.test_tokens import (
    HEADER as TOKENS_HEADER, INSECT, MONARCH, MTGMATE, RABBIT, REAL_TOKENS, deck_md as token_deck_md,
)

_REAL_INCOMING = tokens.incoming
_patches = []


def setUpModule():
    # Keep every test here off the real order records: nothing on the way,
    # unless a test sets it up (TokenTestCase). The token cards are the
    # sandbox's inventory's (none unless a test writes them).
    for target, name, value in ((tokens, "incoming", lambda: ([], [])),):
        patcher = mock.patch.object(target, name, value)
        patcher.start()
        _patches.append(patcher)


def tearDownModule():
    while _patches:
        _patches.pop().stop()
    tokens.clear_cache()


class DecksIndexTests(ApiTestCase):

    def test_every_deck_with_missing_counts(self):
        index = api.decks_index()
        by_id = {d["id"]: d for d in index["decks"]}
        self.assertEqual(set(by_id), {
            "casual/broken", "casual/gruul-test", "commander/elf-commander", "product/fdc-test-precon",
            "product/fdn-beginner-box/elves", "product/fdn-beginner-box/cats",
            "product/fdn-beginner-box/goblins"})
        # Each summary is list_decks()'s, plus the missing counts; a deck file's "source" is its id
        # (the pages name a deck by its id, phase 4); a product's is where its file is in any repo
        # ("magic/products/<file>": the inventory's).
        for summary in decks.list_decks():
            if not summary["id"].startswith("product/"):
                summary["source"] = summary["id"]
            # ... and the shelf's extras (library.shelf_extras: tested in test_cover.py).
            self.assertEqual({k: v for k, v in by_id[summary["id"]].items()
                              if k not in ("missing", "on_the_way", "availability_confirmed", "kit", "tokens",
                                           "cover", "colors", "revision", "edited", "usual_opponents", "played")},
                             summary)
            self.assertEqual(by_id[summary["id"]]["usual_opponents"], [])
            # No accessories are recorded in the sandbox.
            self.assertEqual(by_id[summary["id"]]["kit"], {"sleeves": None, "deck_box": None, "short": 0})
        expected = pool.owned_vs_needed("casual/gruul-test", prices=False)["totals"]["missing"]
        self.assertEqual(by_id["casual/gruul-test"]["missing"], {"target": expected, "owned": 1})
        self.assertGreater(expected, 1)
        self.assertEqual(by_id["product/fdn-beginner-box/elves"]["missing"], {"target": 0})
        self.assertEqual(by_id["product/fdn-beginner-box/cats"]["missing"], {"target": 1})   # Pick Your Poison
        self.assertEqual(by_id["casual/broken"]["missing"], {})
        self.assertIn("error", by_id["casual/broken"])
        cards.usd_to_aud.assert_not_called()        # counts only, no prices
        json.dumps(index, allow_nan=False)

    def test_copies_still_on_the_way_are_counted(self):
        # The preordered precon's own cards haven't arrived: nothing is missing, but the
        # library must not call it "all owned".
        by_id = {d["id"]: d for d in api.decks_index()["decks"]}
        for deck_id in ("product/fdc-test-precon", "casual/gruul-test"):
            result = pool.owned_vs_needed(deck_id, prices=False)
            expected = sum(q for r in result["rows"] for _, q in pool.row_labels(r)["on_the_way"])
            self.assertEqual(by_id[deck_id]["on_the_way"]["target"], expected)
        self.assertGreater(by_id["product/fdc-test-precon"]["on_the_way"]["target"], 0)
        self.assertEqual(by_id["product/fdn-beginner-box/elves"]["on_the_way"], {"target": 0})
        self.assertEqual(by_id["casual/broken"]["on_the_way"], {})

    def test_halves_for_the_pairing_picker(self):
        self.assertEqual(api.decks_index()["halves"], [
            {"id": "product/fdn-beginner-box/elves", "title": "Elves"},
            {"id": "product/fdn-beginner-box/cats", "title": "Cats"},
            {"id": "product/fdn-beginner-box/goblins", "title": "Goblins"}])

    def test_pool_warnings_are_passed_on(self):
        _write(self.box.magic / "products" / "extra.csv", "name,quantity\nOpt,1\n")
        self.assertIn("Product extra has no status, so it counts as owned and not intact",
                      api.decks_index()["warnings"])

    def test_an_unreadable_pool_leaves_the_counts_out(self):
        _write(self.box.magic / "collection.csv", COLLECTION + "Opt,fdn,512,nonfoil,lots,NM,en,\n")
        index = api.decks_index()
        self.assertEqual({d["id"]: d["missing"] for d in index["decks"]}["casual/gruul-test"],
                         {"target": None, "owned": None})
        self.assertTrue(any("bad quantity 'lots'" in w for w in index["warnings"]))

    def test_a_locked_collection_file_leaks_no_path(self):
        # Excel holds collection.csv open exclusively: the page still loads, and the
        # warning names the file, not where it is on the PC.
        path = str(self.box.magic / "collection.csv")
        locked = PermissionError(13, "Permission denied", path)
        with mock.patch.object(pool, "load_pool", side_effect=locked):
            warnings = api.decks_index()["warnings"] + api.deck_view("casual/gruul-test")["warnings"]
        self.assertIn("Owned vs needed can't be worked out: collection.csv: Permission denied "
                      "(is it open in Excel?)", warnings)
        for warning in warnings:
            self.assertNotIn(str(self.box.root), warning)
        self.assertTrue(any("Permission denied" in line and path.replace("\\", "\\\\") in line
                            for line in self.box.logs))

    def test_warnings_from_the_pool_and_stats_leak_no_path(self):
        inside = str(config.REPO / "magic" / "orders" / "x.csv")
        outside = str(self.box.root / "data" / "oracle_tags.jsonl.gz")
        real = pool.load_pool

        def load_pool():
            p = real()
            p.warnings.append(f"x.csv can't be read: [Errno 13] Permission denied: {inside!r}")
            return p
        self.box.stats.side_effect = lambda sections, kind: {
            "warnings": [f"Scryfall's oracle tags couldn't be read ([Errno 2] No such file: {outside!r})"]}
        with mock.patch.object(pool, "load_pool", side_effect=load_pool):
            view = api.deck_view("casual/gruul-test")
            index = api.decks_index()
        relative = str(Path("magic", "orders", "x.csv"))         # as the OS writes it: \\ on Windows
        self.assertIn(f"x.csv can't be read: [Errno 13] Permission denied: {relative!r}", view["owned"]["warnings"])
        self.assertIn(f"x.csv can't be read: [Errno 13] Permission denied: {relative!r}", index["warnings"])
        self.assertEqual(view["stats"]["warnings"],
                         ["Scryfall's oracle tags couldn't be read ([Errno 2] No such file: "
                          "'oracle_tags.jsonl.gz')"])
        text = json.dumps([view, index])
        self.assertNotIn(json.dumps(str(config.REPO))[1:-1], text)
        self.assertNotIn(json.dumps(str(self.box.root))[1:-1], text)

    def test_strip_paths(self):
        repo = str(config.REPO)
        self.assertEqual(api._strip_paths(repo + "\\magic\\collection.csv is locked"),
                         "magic\\collection.csv is locked")
        self.assertEqual(api._strip_paths(config.REPO.as_posix() + "/magic/x.md: bad"), "magic/x.md: bad")
        self.assertEqual(api._strip_paths(r"No card index at C:\Users\someone\AppData\x\index.json.gz. Run it"),
                         "No card index at index.json.gz. Run it")
        self.assertEqual(api._strip_paths(r"'C:\\Users\\someone\\x.csv' and \\server\share\y.txt"),
                         "'x.csv' and y.txt")
        # The Unix way a hook's shell (Git for Windows' sh), WSL or Cygwin writes them (a repo on a drive only).
        if PureWindowsPath(config.REPO).drive:
            msys = "/" + config.REPO.as_posix()[0].lower() + config.REPO.as_posix()[2:]
            for form in (msys, "/mnt" + msys, "/cygdrive" + msys):
                self.assertEqual(api._strip_paths(form + "/magic/x.md: bad"), "magic/x.md: bad")
        self.assertEqual(api._strip_paths("see /c/Users/someone/lint/report.txt and /tmp/claude/abc/y.log"),
                         "see report.txt and y.log")
        self.assertEqual(api._strip_paths("(/home/matt/x.log) and /Users/matt/.hooks/z"), "(x.log) and z")
        for text in ("Fire // Ice (APC) 999", "{T}: Add {G}.", "see https://scryfall.com/a/b", "1★",
                     "the hash /api/deck/edit gave", "magic/decks/casual/x.md", "{B/G} and/or 1/2", "/c/ alone",
                     "see ~/lint/x.txt"):
            self.assertEqual(api._strip_paths(text), text)
        self.assertEqual(api.ApiError(500, rf"{repo}\magic\x.csv can't be read").message, "magic\\x.csv can't be read")



class DeckViewTests(ApiTestCase):

    def lines(self, view, section="Deck"):
        return view["sections"][section]

    def test_shape(self):
        view = api.deck_view("casual/gruul-test")
        self.assertEqual(set(view), {"summary", "version", "versions", "sections", "stats", "owned", "practice",
                                     "matchups", "guide", "tokens", "table", "warnings", "info", "usual_opponents", "standins", "swaps",
                                     "box_checked_on", "considering", "played"})
        self.assertIsNone(view["box_checked_on"])
        self.assertEqual(view["considering"]["lines"], [])        # E2-S23: none written in this deck
        self.assertEqual(view["usual_opponents"], [])
        self.assertEqual((view["version"], view["versions"]), ("target", ["target", "owned"]))
        # Gruul Test has no owned-vs-needed table; products and pairings have no file table at all.
        self.assertEqual(view["table"]["has_table"], False)
        self.assertIsNone(api.deck_view("pairing/cats+elves")["table"])
        self.assertEqual(view["summary"]["id"], "casual/gruul-test")
        self.assertEqual(view["summary"]["title"], "Gruul Test")
        self.assertEqual(list(view["sections"]), ["Deck", "Sideboard"])     # only those present
        first = self.lines(view)[0]
        self.assertEqual(first, {
            "qty": 4, "name": "Llanowar Elves", "set": "fdn", "number": "227", "finish": "nonfoil",
            "card": {"name": "Llanowar Elves", "mana_cost": "{G}", "cmc": 1.0,
                     "type_line": "Creature — Elf Druid", "colors": ["G"], "color_identity": ["G"],
                     "roles": ["ramp"], "img": "/img/fdn/227/normal", "img_small": "/img/fdn/227/small",
                     "oracle_text": "{T}: Add {G}.", "power": "1", "toughness": "1", "loyalty": None, "defense": None}})
        self.assertEqual(self.lines(view, "Sideboard")[0]["card"]["name"], "Pick Your Poison")
        json.dumps(view, allow_nan=False)

    def test_images(self):
        images = {(l["name"], l["set"], l["number"]): l["card"] and l["card"]["img"]
                  for l in self.lines(api.deck_view("casual/gruul-test"))}
        # No set: the newest paper printing (the digital pana and gold-bordered
        # wc00 printings are skipped); a set alone: the newest in that set.
        self.assertEqual(images[("Elvish Mystic", None, None)], "/img/cmm/648/normal")
        self.assertEqual(images[("Llanowar Elves", "m19", None)], "/img/m19/314/normal")
        self.assertEqual(images[("Black Lotus", None, None)], "/img/lea/232/normal")    # not ced
        self.assertEqual(images[("Llanowar Elves", "pdmu", "1★")], "/img/pdmu/1%E2%98%85/normal")
        self.assertEqual(images[("Murderous Rider", "eld", "97")], "/img/eld/97/normal")
        # A printing that doesn't exist, or is another card: the card's newest printing.
        self.assertEqual(images[("Fire // Ice", "apc", "999")], "/img/apc/128/normal")
        self.assertEqual(images[("Sol Ring", "mkm", "170")], "/img/ecc/57/normal")

    def test_names_resolve_like_the_pool_does(self):
        cards_by_name = {l["name"]: l["card"] for l in self.lines(api.deck_view("casual/gruul-test"))}
        self.assertEqual(cards_by_name["Murderous Rider"]["name"], "Murderous Rider // Swift End")
        self.assertEqual(cards_by_name["Murderous Rider"]["type_line"], "Creature — Zombie Knight")    # the front face

    def test_an_un_set_version_shows_its_own_printing(self):
        line = next(l for l in self.lines(api.deck_view("casual/gruul-test"))
                    if l["name"] == "Very Cryptic Command")
        self.assertEqual(line["card"]["img"], "/img/ust/49d/normal")
        self.assertEqual(line["card"]["name"], "Very Cryptic Command")

    def test_warnings_for_unknown_names_and_printings(self):
        view = api.deck_view("casual/gruul-test")
        self.assertEqual(view["warnings"], [
            "'Opt' (Deck) isn't a Scryfall card name, so there's no card data for it",
            "Fire // Ice (APC) 999: Scryfall has no printing APC 999",
            "Sol Ring (MKM) 170: MKM 170 is Pick Your Poison, not Sol Ring",
            # The fixture index has no basic lands; the real one does.
            "'Forest' (Deck) isn't a Scryfall card name, so there's no card data for it",
        ])
        opt = next(l for l in self.lines(view) if l["name"] == "Opt")
        self.assertEqual((opt["qty"], opt["set"], opt["number"], opt["card"]), (1, "fdn", "512", None))

    def test_stats_get_the_decklist_and_its_kind(self):
        view = api.deck_view("casual/gruul-test")
        sections, kind = self.box.stats.call_args.args
        self.assertEqual(sections, decks.load_deck("casual/gruul-test"))
        self.assertIsInstance(sections["Deck"][0], decks.DeckLine)
        self.assertEqual(kind, "constructed")
        # Tuples and sets come back as JSON lists.
        self.assertEqual(view["stats"], {"kind": "constructed", "cards": 25,
                                         "sections": ["Deck", "Sideboard"], "colors": ["B", "G"]})
        for deck_id in ("commander/elf-commander", "product/fdc-test-precon"):
            with self.subTest(deck_id=deck_id):
                view = api.deck_view(deck_id)
                self.assertEqual(self.box.stats.call_args.args[1], "commander")
                self.assertEqual(list(view["sections"]), ["Commander", "Deck"])
        api.deck_view("product/fdn-beginner-box/cats")
        self.assertEqual(self.box.stats.call_args.args[1], "constructed")

    def test_the_deck_still_shows_when_stats_fail(self):
        for problem in (ZeroDivisionError("bug"), lambda s, k: {"x": object()}):
            with self.subTest(problem=problem):
                self.box.stats.side_effect = problem
                view = api.deck_view("casual/gruul-test")
                self.assertIsNone(view["stats"])
                self.assertIn("The deck stats couldn't be worked out (the server log says why)",
                              view["warnings"])
                self.assertEqual(len(self.lines(view)), 11)
        self.assertIn("Traceback", self.box.logs[-1])

    def test_the_deck_still_shows_without_a_stats_module(self):
        with mock.patch.dict(sys.modules, {"decklab.lib.stats": None}):
            view = api.deck_view("casual/gruul-test")
        self.assertIsNone(view["stats"])
        self.assertIn("ModuleNotFoundError", self.box.logs[-1])

    def test_owned_vs_needed_as_json(self):
        from decklab.lib.api import shop_prices
        from decklab.tests.golden_shop_prices import ABSENT_MISSING_SNAPSHOT

        with mock.patch.object(shop_prices, "capture", return_value=None) as capture:
            view = api.deck_view("casual/gruul-test")
        capture.assert_called_once_with()
        owned = view["owned"]
        expected = pool.owned_vs_needed("casual/gruul-test")
        for row in expected["rows"]:
            row["labels"] = pool.row_labels(row)
            row.pop("incoming_sources")
            row["labels"]["incoming_sources"] = ([{
                "source": "Fdc Test Precon", "quantity": 1, "order_id": None,
                "component_id": None, "product_id": "fdc-test-precon", "status": "preordered",
            }] if row["name"] == "Sol Ring" else [])
            if type(row.get("missing")) is int and row["missing"] > 0:
                row["shop_snapshot"] = dict(ABSENT_MISSING_SNAPSHOT)
        expected["warnings"] = [api._strip_paths(w) for w in expected["warnings"]]    # no paths
        self.assertEqual(owned, json.loads(json.dumps(expected)))
        self.assertEqual((owned["rate"], owned["rate_date"], owned["price_date"]), (2.0, "2026-09-28", "2026-09-28"))
        rows = {r["name"]: r for r in owned["rows"]}
        # (deck title, copies) pairs become 2-item lists.
        self.assertEqual(rows["Llanowar Elves"]["in_use_elsewhere"],
                         [["Elves (Foundations Beginner Box)", 1], ["Cats (Foundations Beginner Box)", 1]])
        self.assertEqual(rows["Sol Ring"]["on_the_way_from"], [["fdc-test-precon, preordered", 1]])
        self.assertEqual(owned["unresolved"], [["Opt", "decklist"]])
        # The labels are the deck file's: Llanowar Elves (need 6, 5 owned, 2 in the halves)
        # is short because of the halves; the one Sol Ring is on the way.
        self.assertEqual(rows["Llanowar Elves"]["labels"], {
            "on_the_way": [], "incoming_sources": [], "in_use": [["Elves (Foundations Beginner Box)", 1],
                                         ["Cats (Foundations Beginner Box)", 1]]})
        self.assertEqual(rows["Sol Ring"]["labels"], {"on_the_way": [["fdc-test-precon, preordered", 1]],
            "in_use": [], "incoming_sources": [{"source": "Fdc Test Precon", "quantity": 1,
                "order_id": None, "component_id": None, "product_id": "fdc-test-precon", "status": "preordered"}]})

    def test_labels_count_only_the_copies_this_deck_relies_on(self):
        # One Sol Ring here and one on the way, for a deck needing one: nothing to wait for.
        # Ten Llanowar Elves: the halves hold two, but that leaves the deck plenty.
        _write(self.box.magic / "collection.csv", COLLECTION.replace(",5,NM", ",10,NM")
               + "Sol Ring,ecc,57,nonfoil,1,NM,en,\n")
        rows = {r["name"]: r for r in api.deck_view("casual/gruul-test")["owned"]["rows"]}
        sol, elves = rows["Sol Ring"], rows["Llanowar Elves"]
        self.assertEqual((sol["owned"], sol["on_the_way"], sol["missing"]), (2, 1, 0))
        self.assertEqual(sol["labels"], {"on_the_way": [], "in_use": [], "incoming_sources": []})
        self.assertEqual((elves["missing"], len(elves["in_use_elsewhere"])), (0, 2))
        self.assertEqual(elves["labels"], {"on_the_way": [], "in_use": [], "incoming_sources": []})

    def test_lines_with_no_printing_show_one_from_the_decks_set(self):
        # A deck mostly of M19 cards shows its unprinted Llanowar Elves as M19's, not
        # the newer FDN one (for basic lands: the deck's Forests, not a Secret Lair's).
        _write(self.box.magic / "decks" / "casual" / "m19-elves.md",
               "# M19 Elves\n\n- **Status:** idea\n\n## Decklist\n\n```\nDeck\n1 Llanowar Elves\n"
               "3 Llanowar Elves (M19) 314\n```\n")
        lines = self.lines(api.deck_view("casual/m19-elves"))
        self.assertEqual([l["card"]["img"] for l in lines], ["/img/m19/314/normal"] * 2)

    def test_shown_printing_prefers_the_ordinary_frame(self):
        def fake(set_code, number, set_type, released="2025-01-01", paper=True):
            return {"set": set_code, "collector_number": number, "set_type": set_type,
                    "released_at": released, "digital": False, "games": ["paper"] if paper else ["arena"],
                    "oversized": False, "image_normal": "x", "image_small": "x"}
        printings = [fake("trk", "326", "expansion", "2099-01-01"),      # not released yet
                     fake("sld", "2120", "box"),                          # Secret Lair
                     fake("hob", "198", "expansion"), fake("hob", "193", "expansion"),
                     fake("pana", "271", "promo", paper=False),
                     fake("fdn", "291", "core"), fake("fdn", "290", "core"),
                     fake("fdn", "281", "core"), fake("fdn", "280", "core")]
        found = {(p["set"], p["collector_number"]): p for p in printings}
        card = {"printings": [(p["set"], p["collector_number"]) for p in printings]}
        with mock.patch.object(cards, "printing", side_effect=lambda s, n: found.get((s, n))):
            pick = lambda *prefer: (lambda p: (p["set"], p["collector_number"]))(api._shown_printing(card, prefer))
            self.assertEqual(pick("fdn"), ("fdn", "280"))                # the deck's set, lowest number
            self.assertEqual(pick(None, "fdn"), ("fdn", "280"))
            self.assertEqual(pick(), ("hob", "193"))                     # newest released expansion
            self.assertEqual(pick("zzz"), ("hob", "193"))
            self.assertEqual(pick("sld"), ("sld", "2120"))               # only when the line names it
        self.assertEqual(sorted(["280", "12a", "9", "1★", "ABC"], key=api._number_key),
                         ["1★", "9", "12a", "280", "ABC"])

    def test_the_owned_only_version(self):
        view = api.deck_view("casual/gruul-test", "owned")
        self.assertEqual(view["version"], "owned")
        self.assertEqual([(l["qty"], l["name"]) for l in self.lines(view)], [(4, "Llanowar Elves")])
        self.assertEqual((view["owned"]["version"], view["owned"]["totals"]["missing"]), ("owned", 1))

    def test_pairings_in_either_order(self):
        view = api.deck_view("pairing/cats+elves")
        self.assertEqual(view["summary"]["id"], "pairing/elves+cats")
        self.assertEqual(view["summary"]["halves"], ["product/fdn-beginner-box/elves",
                                                      "product/fdn-beginner-box/cats"])
        names = {l["name"]: l["qty"] for l in self.lines(view)}
        self.assertEqual(names["Llanowar Elves"], 2)
        # The pairing doesn't count its own halves as holding its cards.
        self.assertEqual(view["owned"]["conflicts"], [])
        self.assertEqual(view, api.deck_view("pairing/elves+cats"))
        self.assertApiError(404, api.deck_view, "pairing/cats+cats")
        self.assertApiError(404, api.deck_view, "pairing/cats+dragons")

    def test_an_unreadable_pool_still_shows_the_deck(self):
        _write(self.box.magic / "collection.csv", COLLECTION + "Opt,fdn,512,nonfoil,lots,NM,en,\n")
        view = api.deck_view("casual/gruul-test")
        self.assertIsNone(view["owned"])
        self.assertTrue(any("bad quantity 'lots'" in w for w in view["warnings"]))
        self.assertEqual(len(self.lines(view)), 11)

    def test_errors(self):
        self.assertApiError(404, api.deck_view, "casual/nope")
        self.assertApiError(404, api.deck_view, "product/fdn-beginner-box/dragons")
        self.assertApiError(404, api.deck_view, "commander/elf-commander", "owned", contains="no owned list")
        self.assertApiError(404, api.deck_view, "product/fdc-test-precon", "owned")
        self.assertApiError(400, api.deck_view, "casual/gruul-test", "Owned")
        self.assertApiError(400, api.deck_view, "casual/gruul-test", None)
        self.assertApiError(500, api.deck_view, "casual/broken",
                            contains="casual/broken can't be read: no fenced decklist")

    def test_malformed_ids_are_400(self):
        for deck_id in ("", "casual", "casual/", "../../CLAUDE", "casual/../../CLAUDE", "casual/..",
                        "casual/../gruul-test", "casual/.gruul-test", "casual\\gruul-test",
                        "casual/gruul-test/x", "decks/casual/gruul-test", "product/a/b/c",
                        "pairing/cats+elves/x", "casual/C:gruul", "casual/gruul\x00", "casual/gruul\n",
                        "/casual/gruul-test", "casual/" + "a" * 200, None, 7):
            with self.subTest(deck_id=deck_id):
                self.assertApiError(400, api.deck_view, deck_id)
        self.box.stats.assert_not_called()

    def test_a_hand_named_file_can_be_opened(self):
        _write(self.box.magic / "decks" / "casual" / "Gruul_Copy.md", GRUUL)
        view = api.deck_view("casual/Gruul_Copy")
        self.assertEqual(view["summary"]["read_only"], True)
        self.assertEqual(len(self.lines(view)), 11)



class DeckKitTests(ApiTestCase):
    """The library's and deck page's sleeves and deck box (accessories.kit)."""

    def setUp(self):
        super().setUp()
        from decklab.tests.test_editor import sandbox_accessories
        sandbox_accessories(self)
        _write(self.box.magic / "accessories.csv",
               "id,kind,brand,name,colour,quantity,image,link,image_source,notes\n"
               "dragon-shield-matte-black,sleeves,Dragon Shield,Matte,black,100,,,,\n"
               "katana-black,sleeves,KMC,Katana,Black,20,,,,\n")
        self.gruul = self.box.magic / "decks" / "casual" / "gruul-test.md"
        _write(self.gruul, GRUUL.replace("- **Status:** building\n",
                                         "- **Status:** built\n- **Built version:** target\n"
                                         "- **Sleeves:** katana-black\n- **Deck box:** Shoebox\n"))

    def test_the_library_shows_each_kit_in_brief(self):
        by_id = {d["id"]: d for d in api.decks_index()["decks"]}
        self.assertEqual(by_id["casual/gruul-test"]["kit"], {
            "sleeves": {"name": "KMC Katana (Black)", "image_url": None, "state": "linked"},
            "deck_box": {"name": "Shoebox", "image_url": None, "state": "text"}, "short": 5})
        self.assertEqual(by_id["commander/elf-commander"]["kit"], {"sleeves": None, "deck_box": None, "short": 0})
        _write(self.box.magic / "products" / "status.csv",
               "file,status,intact,sleeves,deck_box,notes\n"
               "fdn-beginner-box.csv,owned,yes,dragon-shield-matte-black,,kept as its decks\n"
               "fdc-test-precon.csv,preordered,,,,due soon\n")
        by_id = {d["id"]: d for d in api.decks_index()["decks"]}
        for half in ("elves", "cats", "goblins"):
            self.assertEqual(by_id[f"product/fdn-beginner-box/{half}"]["kit"]["sleeves"]["name"],
                             "Dragon Shield Matte (black)")
        self.assertIsNone(by_id["product/fdc-test-precon"]["kit"]["sleeves"])

    def test_the_deck_page_counts_the_built_version(self):
        view = api.deck_view("casual/gruul-test", "owned")
        kit = view["summary"]["kit"]
        self.assertEqual((kit["holder"], kit["need"], kit["short"]), ("casual/gruul-test", 25, 5))
        self.assertIn("Not enough sleeves: this deck needs 25 (23 in the deck, 2 in the sideboard) and KMC Katana "
                      "(Black) has 20. Get 5 more of the same sleeves, or fix the count on the Accessories page.",
                      view["warnings"])
        self.assertEqual(view["info"], ["“Shoebox” isn't in the accessories list, so Deck Lab can't check "
                                        "it's free."])
        self.assertEqual(view["summary"]["holder_sha256"], hashlib.sha256(self.gruul.read_bytes()).hexdigest())
        json.dumps(view, allow_nan=False)

    def test_a_deck_that_isnt_built_counts_the_shown_version(self):
        _write(self.gruul, GRUUL)
        kit = api.deck_view("casual/gruul-test", "owned")["summary"]["kit"]
        self.assertEqual((kit["need"], kit["sleeves"], kit["deck_box"], kit["warnings"]), (4, None, None, []))

    def test_a_product_kept_intact(self):
        view = api.deck_view("product/fdn-beginner-box/elves")
        kit = view["summary"]["kit"]
        self.assertEqual(kit["holder"], "product/fdn-beginner-box")
        self.assertTrue(any(w.endswith(f"is kept intact: choose its sleeves (it needs {kit['need']}).")
                            for w in view["warnings"]), view["warnings"])
        self.assertEqual(view["summary"]["holder_sha256"], accessories.status_sha256())
        self.assertIsNone(api.deck_view("pairing/elves+cats")["summary"]["holder_sha256"])
        # E8-S21: one box label for the whole product, its code opening the first deck's page.
        label = view["box_label"]
        self.assertEqual(label["link"], label["decks"][0]["id"])
        self.assertIn("product/fdn-beginner-box/elves", [d["id"] for d in label["decks"]])
        self.assertEqual(api.deck_view("product/fdn-beginner-box/cats")["box_label"], label)
        self.assertNotIn("box_label", api.deck_view("casual/gruul-test"))


class TokenTestCase(ApiTestCase):
    """The sandbox with a card index built from fixtures/tokens_cards.jsonl, its
    own magic/tokens.csv (test_tokens.REAL_TOKENS) and order records, and
    these decks:

    - casual/hornets (building): Hornet Queen and Court of Grace, Hare
      Apparent in the sideboard; its owned-only list is just Hare Apparent;
    - casual/rabbits (built, owned-only version built): target Court of
      Grace, owned-only Hare Apparent;
    - casual/someday (idea): Hornet Queen."""

    @classmethod
    def setUpClass(cls):
        cls.loaded = cards._prepare(cards.build_index(FIXTURES / "tokens_cards.jsonl", FIXTURES / "oracle_tags.jsonl",
                                                      {}, log=lambda *a: None))

    def setUp(self):
        super().setUp()
        for target, name, value in ((cards, "_index", self.loaded),
                                    (tokens, "incoming", _REAL_INCOMING),
                                    (config, "REPO", self.box.root)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        tokens.clear_cache()
        self.addCleanup(tokens.clear_cache)
        _write(self.box.magic / "tokens.csv", REAL_TOKENS)
        casual = self.box.magic / "decks" / "casual"
        _write(casual / "hornets.md", token_deck_md("Hornets", deck="1 Hornet Queen\n1 Court of Grace\n",
                                                    sideboard="1 Hare Apparent\n", owned="1 Hare Apparent\n"))
        _write(casual / "rabbits.md", token_deck_md("Rabbits", "built", deck="1 Court of Grace\n",
                                                    owned="1 Hare Apparent\n", built_version="owned-only"))
        _write(casual / "someday.md", token_deck_md("Someday", "idea"))

    def order(self, rows=MTGMATE, order="2026-10-07-shop-a"):
        """A pending tokens order: its record and payload."""
        rel = f"magic/orders/tokens/{order}.csv"
        (self.box.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.box.root / rel).write_bytes(rules.csv_bytes(rows, rules.TOKEN_FIELDS))
        record = {"version": 1, "id": order, "seller": "MTGMate", "ordered_on": "2026-10-07", "sources": [],
                  "notes": "", "components": [{"id": "tokens", "kind": "tokens", "path": rel, "status": "pending",
                                               "received_on": "", "checks": []}]}
        _write(self.box.magic / "orders" / "records" / f"{order}.json", json.dumps(record))

    def need(self, result, key):
        found = [n for n in result["needs"] if n["key"] == key]
        self.assertEqual(len(found), 1, [n["key"] for n in result["needs"]])
        return found[0]


class DeckTokensTests(TokenTestCase):
    """deck_view's "tokens": what the version shown makes, against the token cards owned."""

    def test_the_tokens_the_shown_list_makes(self):
        self.order([row for row in MTGMATE if row["front"] == "Insect"])
        view = api.deck_view("casual/hornets")
        expected = tokens.deck_tokens(decks.load_deck("casual/hornets", "target"), tokens.read(),
                                      _REAL_INCOMING()[0])
        self.assertEqual(view["tokens"], expected)
        insect = self.need(view["tokens"], INSECT)
        self.assertEqual(insect["state"], "differs")
        self.assertEqual(insect["words"], "Different token: your card says no deathtouch; Hornet Queen's Insect "
                                          "has deathtouch · 2 on the way")
        self.assertEqual(self.need(view["tokens"], MONARCH)["state"], "check")
        self.assertTrue(self.need(view["tokens"], RABBIT)["sideboard_only"])
        self.assertEqual(view["tokens"]["note"], tokens.NOTE)
        # A missing or different token is never a warning.
        self.assertFalse([w for w in view["warnings"] if "token" in w.lower() or "Insect" in w], view["warnings"])
        json.dumps(view, allow_nan=False)

    def test_it_counts_the_version_shown(self):
        owned = api.deck_view("casual/hornets", "owned")["tokens"]
        self.assertEqual([n["key"] for n in owned["needs"]], [RABBIT])
        self.assertFalse(owned["needs"][0]["sideboard_only"])
        # A built deck's page still shows the version asked for, not the built one.
        target = api.deck_view("casual/rabbits", "target")["tokens"]
        self.assertNotIn(RABBIT, [n["key"] for n in target["needs"]])
        self.assertIn(MONARCH, [n["key"] for n in target["needs"]])

    def test_a_pairing_has_none(self):
        self.assertIsNone(api.deck_view("pairing/cats+elves")["tokens"])
        self.assertEqual(api.deck_view("product/fdn-beginner-box/elves")["tokens"]["needs"], [])

    def test_unreadable_rows_go_in_info(self):
        _write(self.box.magic / "tokens.csv", REAL_TOKENS + "Spirit,,,,,,none,,,\n")
        view = api.deck_view("casual/hornets")
        self.assertIn("A token cards row after row 24 couldn't be read; see the Tokens page", view["info"])
        self.assertFalse([w for w in view["warnings"] if "token cards" in w or "tokens.csv" in w])
        self.assertEqual(self.need(view["tokens"], MONARCH)["state"], "check")    # the other rows still count

    def test_a_header_problem_goes_in_info_as_written(self):
        _write(self.box.magic / "tokens.csv", "front,back,quantity,front_details,back_details,notes\n"
                                                "Insect,Goblin,1,1/1; flying,,\n")
        info = api.deck_view("casual/hornets")["info"]
        self.assertIn("The home token cards lack the printing columns; fix the header by hand before the Tokens "
                      "page can save", info)

    def test_while_the_card_data_is_rebuilt(self):
        with mock.patch.object(tokens, "cached_deck_tokens", side_effect=RuntimeError("index format 3")):
            view = api.deck_view("casual/hornets")
        self.assertEqual(view["tokens"], {"unavailable": "Token data is being rebuilt; refresh in a minute."})
        self.assertNotIn("index format 3", json.dumps(view))

    def test_any_other_failure_is_logged(self):
        with mock.patch.object(tokens, "cached_deck_tokens", side_effect=KeyError("oops")):
            view = api.deck_view("casual/hornets")
        self.assertEqual(view["tokens"], {"error": "Tokens couldn't be worked out; the server log has the details."})
        self.assertTrue(any("KeyError" in line and "casual/hornets" in line for line in self.box.logs))
        self.assertEqual(view["summary"]["title"], "Hornets")      # the page still shows
        with mock.patch.object(tokens, "read", side_effect=PermissionError(13, "Permission denied")):
            self.assertIn("error", api.deck_view("casual/hornets")["tokens"])

    def test_token_cards_change_the_answer(self):
        before = self.need(api.deck_view("casual/hornets")["tokens"], INSECT)["state"]
        _write(self.box.magic / "tokens.csv", TOKENS_HEADER + "Insect,,tc20,13,,,1,,,single-sided verified\n")
        after = self.need(api.deck_view("casual/hornets")["tokens"], INSECT)
        self.assertEqual((before, after["state"]), ("differs", "ready"))


class DeckIndexTokensTests(TokenTestCase):
    """decks_index's "tokens": a brief of the list that counts, for the library."""

    def test_briefs_of_the_list_that_counts(self):
        self.order()
        by_id = {d["id"]: d for d in api.decks_index()["decks"]}
        hornets = by_id["casual/hornets"]["tokens"]            # building: its target list
        expected = tokens.brief(tokens.deck_tokens(decks.load_deck("casual/hornets", "target"),
                                                   tokens.read(), _REAL_INCOMING()[0]))
        self.assertEqual(hornets, expected)
        self.assertEqual(hornets["differs"], ["Insect"])
        self.assertEqual(set(hornets), {"kinds", "none", "differs", "incoming", "reminders"})
        # Built with its owned-only list: only Hare Apparent's Rabbit counts.
        self.assertEqual(by_id["casual/rabbits"]["tokens"], {"kinds": 1, "none": [], "differs": [], "incoming": [], "reminders": []})
        self.assertIsNone(by_id["casual/someday"]["tokens"])   # an idea deck
        self.assertIsNone(by_id["commander/elf-commander"]["tokens"])
        self.assertIsNone(by_id["casual/broken"]["tokens"])    # can't be read
        self.assertEqual(by_id["product/fdn-beginner-box/elves"]["tokens"]["kinds"], 0)
        self.assertEqual(by_id["casual/gruul-test"]["tokens"]["kinds"], 0)
        json.dumps(by_id, allow_nan=False)

    def test_none_while_the_card_data_is_rebuilt(self):
        with mock.patch.object(tokens, "cached_deck_tokens", side_effect=RuntimeError("no index")) as made:
            index = api.decks_index()
        self.assertEqual(made.call_count, 1)                   # not tried again for every deck
        self.assertTrue(all(d["tokens"] is None for d in index["decks"]))
        self.assertFalse([line for line in self.box.logs if "tokens" in line])
        self.assertFalse([w for w in index["warnings"] if "token" in w.lower()])

    def test_a_failure_is_logged_once(self):
        with mock.patch.object(tokens, "cached_deck_tokens", side_effect=KeyError("oops")) as made:
            index = api.decks_index()
        self.assertGreater(made.call_count, 1)
        self.assertTrue(all(d["tokens"] is None for d in index["decks"]))
        self.assertEqual(len([line for line in self.box.logs if "couldn't be worked out for the library" in line]), 1)

    def test_an_unreadable_inventory_still_shows_the_library(self):
        with mock.patch.object(tokens, "read", side_effect=PermissionError(13, "Permission denied")):
            index = api.decks_index()
        self.assertTrue(all(d["tokens"] is None for d in index["decks"]))
        self.assertEqual(len([line for line in self.box.logs if "tokens couldn't be read" in line]), 1)


class FrozenDeckFileTests(ApiTestCase):
    """Every frozen copy of the real deck files goes through deck_view()."""

    def test_every_fixture_deck_and_version(self):
        with mock.patch.object(decks, "DECKS_DIR", FIXTURES / "decks"), inventory.use(pre_db.following(self.box.root)):
            summaries = [s for s in api.decks_index()["decks"] if not s["id"].startswith("product/")]
            self.assertEqual(len(summaries), 11)
            for summary in summaries:
                for version in summary["versions"]:
                    with self.subTest(deck=summary["id"], version=version):
                        view = api.deck_view(summary["id"], version)
                        expected = decks.load_deck(summary["id"], version)
                        self.assertEqual({s: len(lines) for s, lines in view["sections"].items()},
                                         {s: len(lines) for s, lines in expected.items()})
                        kind = "commander" if summary["id"].startswith("commander/") else "constructed"
                        self.assertEqual(self.box.stats.call_args.args[1], kind)
                        json.dumps(view, allow_nan=False)



if __name__ == "__main__":
    unittest.main()
