"""The gauntlet's sources and catalogue (lib/gauntlet/{edhrec,precon,forge}_source.py,
catalogue.py, edhrec.get_json): read from hand-trimmed copies of EDHREC's pages, an MTGJSON deck
file and Forge .dck files under fixtures/gauntlet/. Nothing is fetched: EDHREC's get_json is a
fake serving the fixtures, MTGJSON's fetch and urlopen fail if called."""
import io
import json
import shutil
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from decklab.lib import edhrec, gauntlet
from decklab.lib.gauntlet import catalogue, edhrec_source, forge_source, precon_source
from decklab.tests.gauntlet_sources_support import GAUNTLET, GauntletCase, fake_limits

QUEST = GAUNTLET / "quest"
YSHTOLA = "Y'shtola, Night's Blessed"


def page(name):
    return json.loads((GAUNTLET / "edhrec" / name).read_text(encoding="utf-8"))


class FakeEdhrec:
    """edhrec.get_json over the fixtures: Y'shtola's pages, NoPage for anything else."""

    def __init__(self):
        self.paths = []
        self.pages = {"commanders/year.json": page("year.json"),
                      "average-decks/yshtola-nights-blessed/core.json": page("core.json"),
                      "average-decks/yshtola-nights-blessed/upgraded.json": page("upgraded.json")}

    def __call__(self, path):
        self.paths.append(path)
        if path not in self.pages:
            raise edhrec.NoPage(f"EDHREC has no page for {path}")
        return json.loads(json.dumps(self.pages[path]))


def no_commander_page(names, refresh=False, page=None):
    raise edhrec.EdhrecError("EDHREC couldn't be reached (fixture)")


class GetJson(unittest.TestCase):
    def test_get_json_asks_politely_for_the_path(self):
        seen = []

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def urlopen(request, timeout):
            seen.append((request.full_url, request.get_header("User-agent"), timeout))
            return Response(b'{"ok": 1}')

        with mock.patch.object(edhrec, "MIN_GAP", 0), mock.patch("urllib.request.urlopen", urlopen):
            self.assertEqual(edhrec.get_json("average-decks/yshtola-nights-blessed/core.json"), {"ok": 1})
        self.assertEqual(seen, [("https://json.edhrec.com/pages/average-decks/yshtola-nights-blessed/core.json",
                                 edhrec.USER_AGENT, edhrec.TIMEOUT)])

    def test_get_json_refuses_odd_paths_without_asking(self):
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("asked")):
            for bad in ("../etc/passwd.json", "commanders/year", "https://x/y.json", "Commanders/Year.json", None):
                with self.assertRaises(edhrec.EdhrecError):
                    edhrec.get_json(bad)


class EdhrecSource(GauntletCase):
    def setUp(self):
        super().setUp()
        self.fake = FakeEdhrec()
        self.patch(edhrec, "get_json", self.fake)
        self.patch(edhrec, "fetch", no_commander_page)

    def test_parse_top_keeps_good_rows_and_the_next_page(self):
        rows, more = edhrec_source.parse_top(page("year.json"))
        self.assertEqual([r["slug"] for r in rows],
                         ["yshtola-nights-blessed", "edgar-markov", "frodo-adventurous-hobbit-sam-loyal-attendant"])
        self.assertEqual(rows[0], {"name": YSHTOLA, "slug": "yshtola-nights-blessed", "rank": 1, "decks": 58631})
        self.assertEqual(more, "commanders/year-past2years-1.json")

    def test_parse_average(self):
        read = edhrec_source.parse_average(page("core.json"))
        self.assertEqual(read["commanders"], [YSHTOLA])
        self.assertEqual(read["decks"], 2027)
        self.assertIn([6, "Island"], read["cards"])
        self.assertEqual(sum(q for q, _ in read["cards"]), 21)
        self.assertEqual(read["themes"][0], {"slug": "control", "name": "Control", "decks": 209})

    def test_parse_average_refuses_a_page_without_its_deck(self):
        for broken in ({}, {"deck": {"commander": [], "cards": {}}},
                       {"deck": {"commander": ["X"], "cards": {"Land": [["Island", "six"]]}}}):
            with self.assertRaises(edhrec.EdhrecError):
                edhrec_source.parse_average(broken)

    def test_decks_both_tiers_and_why_others_are_missing(self):
        records, excluded = edhrec_source.decks(top=2, log=lambda *a: None)
        self.assertEqual([r["id"] for r in records], ["gauntlet:edhrec/yshtola-nights-blessed-core",
                                                      "gauntlet:edhrec/yshtola-nights-blessed-upgraded"])
        self.assertEqual([i for i, _ in excluded], ["gauntlet:edhrec/edgar-markov-core",
                                                    "gauntlet:edhrec/edgar-markov-upgraded"])
        core = records[0]
        self.assertEqual(core["source"]["kind"], "edhrec")
        self.assertEqual(core["source"]["url"], "https://edhrec.com/average-decks/yshtola-nights-blessed/core")
        self.assertEqual(core["source"]["rank"], 1)
        self.assertEqual(core["themes"], [])          # no theme reaches 25% of the core page's 2027 decks
        self.assertNotIn("commanders/year-past2years-1.json", self.fake.paths)

    def test_themes_from_the_commander_page(self):
        found = {"themes": [{"slug": "control", "name": "Control", "decks": 20000},
                            {"slug": "lifegain", "name": "Lifegain", "decks": 2000}], "decks": 58631, "stale": None}
        self.patch(edhrec, "fetch", lambda names, refresh=False: dict(found))
        records, _ = edhrec_source.decks(top=1, log=lambda *a: None)
        self.assertEqual(records[0]["themes"], ["Control"])

    def test_cached_pages_are_reused_and_a_dry_run_fetches_nothing(self):
        edhrec_source.decks(top=1, log=lambda *a: None)
        asked = len(self.fake.paths)
        edhrec_source.decks(top=1, log=lambda *a: None)
        self.assertEqual(len(self.fake.paths), asked)
        self.patch(edhrec, "get_json", mock.Mock(side_effect=AssertionError("fetched in a dry run")))
        records, _ = edhrec_source.decks(top=1, offline=True, log=lambda *a: None)
        self.assertEqual(len(records), 2)

    def test_a_failed_fetch_keeps_the_old_copy(self):
        edhrec_source.decks(top=1, log=lambda *a: None)
        old = datetime.now(timezone.utc) - timedelta(days=40)
        path = "average-decks/yshtola-nights-blessed/core.json"
        edhrec_source._write_cache(path, old, page("core.json"))
        self.patch(edhrec, "get_json", mock.Mock(side_effect=edhrec.EdhrecError("EDHREC answered 500")))
        found, fetched, note = edhrec_source.cached_page(path, edhrec_source.AVERAGE_MAX_AGE)
        self.assertEqual(found["header"], page("core.json")["header"])
        self.assertIn("copy from before", note)
        self.assertEqual(fetched, old.isoformat(timespec="seconds"))


class PreconSource(GauntletCase):
    def mtgjson_cache(self):
        shutil.copytree(GAUNTLET / "mtgjson", self.tmp / "mtgjson")

    def test_newest_commander_decks_from_mtgjson(self):
        self.mtgjson_cache()
        records, excluded = precon_source.decks(log=lambda *a: None)
        self.assertEqual([i for i, _ in excluded], ["gauntlet:precon/SpellcraftScions_FDC"])
        (ahoy,) = records
        self.assertEqual(ahoy["id"], "gauntlet:precon/AhoyMateys_LCC")
        self.assertEqual(ahoy["commanders"], ["Admiral Brass, Unsinkable"])
        self.assertEqual(sum(q for q, _ in ahoy["cards"]), 99)
        self.assertEqual(ahoy["source"]["rank"], 2)     # the newer Spellcraft Scions is 1
        self.assertEqual(ahoy["tier"], "precon")

    def test_forge_stands_in_under_the_same_id(self):
        records, excluded = precon_source.decks(root=QUEST, log=lambda *a: None)
        self.assertEqual(excluded, [])
        (ahoy,) = records
        self.assertEqual(ahoy["id"], "gauntlet:precon/AhoyMateys_LCC")
        self.assertEqual(ahoy["source"], {"kind": "forge", "file": "res/quest/commanderprecons/Ahoy Mateys [LCC] [2023].dck",
                                          "fetched": None, "rank": 1, "decks": None})
        self.assertEqual(ahoy["commanders"], ["Admiral Brass, Unsinkable"])

    def test_mtgjson_stem(self):
        self.assertEqual(precon_source.mtgjson_stem("Wretched Ranks", "fdc"), "WretchedRanks_FDC")


class ForgeSource(GauntletCase):
    def test_parse_dck_strips_sets_and_adds_up_names(self):
        parsed = forge_source.read_dck(QUEST / "precons" / "Aerodoom.dck")
        self.assertEqual(parsed["meta"]["Set"], "BTD")
        self.assertEqual(parsed["cards"]["Main"][:2], [[11, "Island"], [11, "Swamp"]])
        self.assertIn([4, "Counterspell"], parsed["cards"]["Main"])        # "Counterspell+|TMP": foil
        self.assertEqual(sum(q for q, _ in parsed["cards"]["Main"]), 60)

    def test_one_duel_per_title_and_the_precons(self):
        records, excluded = forge_source.constructed_decks(QUEST, log=lambda *a: None)
        self.assertEqual([r["id"] for r in records], ["gauntlet:forge/duels/agent-k-2", "gauntlet:forge/precons/aerodoom"])
        self.assertEqual([r["tier"] for r in records], ["medium", "precon"])
        self.assertEqual(excluded, [("gauntlet:forge/duels/agent-k-1", "another version of Agent K (medium) is kept")])
        self.assertEqual(records[0]["cards"][0], [24, "Swamp"])

    def test_short_main_deck_is_a_problem(self):
        parsed = forge_source.parse_dck("[metadata]\nName=Tiny\n[main]\n20 Swamp\n")
        record = forge_source._record("precons", QUEST / "precons" / "Tiny.dck", QUEST, parsed, "precon")
        self.assertIn("needs at least 60", record["problems"][0])


class Catalogue(GauntletCase):
    def setUp(self):
        super().setUp()
        self.patch(catalogue, "FORGE_ROOT", QUEST)
        self.patch(catalogue, "LIMITS", fake_limits())
        self.patch(edhrec, "get_json", FakeEdhrec())
        self.patch(edhrec, "fetch", no_commander_page)
        self.log = []

    def test_constructed_build_saves_and_loads(self):
        built = catalogue.build("constructed", log=self.log.append)
        self.assertEqual(catalogue.load("constructed"), built)
        self.assertEqual(gauntlet.catalogue_path("constructed").parent, self.tmp / "gauntlet")
        by_id = {d["id"]: d for d in built["decks"]}
        agent = by_id["gauntlet:forge/duels/agent-k-2"]
        self.assertTrue(agent["playable"])
        self.assertEqual(agent["kind"], "constructed")
        self.assertIsNone(agent["bracket"])
        self.assertEqual(agent["identity"], "B")
        self.assertEqual(agent["cards"]["Commander"], [])
        aero = by_id["gauntlet:forge/precons/aerodoom"]
        self.assertFalse(aero["playable"])
        self.assertIn("Not Scryfall cards: Fog Elemental.", aero["problems"])
        self.assertEqual(built["sha"], catalogue.catalogue_sha(built["decks"]))
        self.assertEqual(built["card_data"], "2026-11-01")
        self.assertTrue(any(line.startswith("Left out: gauntlet:forge/duels/agent-k-1") for line in self.log))
        self.assertTrue(any(line.startswith("Not playable: gauntlet:forge/precons/aerodoom") for line in self.log))

    def test_commander_build(self):
        shutil.copytree(GAUNTLET / "mtgjson", self.tmp / "mtgjson")
        built = catalogue.build("commander", top=2, log=self.log.append)
        by_id = {d["id"]: d for d in built["decks"]}
        self.assertEqual(sorted(by_id), ["gauntlet:edhrec/yshtola-nights-blessed-core",
                                         "gauntlet:edhrec/yshtola-nights-blessed-upgraded",
                                         "gauntlet:precon/AhoyMateys_LCC"])
        for deck in built["decks"]:
            self.assertTrue(deck["playable"], deck["problems"])
            self.assertEqual(sum(q for q, _ in deck["cards"]["Commander"] + deck["cards"]["Main"]), 100)
        upgraded = by_id["gauntlet:edhrec/yshtola-nights-blessed-upgraded"]
        self.assertIn("Dropped 1 Lightning Bolt: outside the commander's colour identity.", upgraded["fixes"])
        self.assertEqual(upgraded["bracket"]["game_changers"], ["Cyclonic Rift", "Rhystic Study"])
        self.assertEqual(upgraded["tier"], "upgraded")
        self.assertEqual(by_id["gauntlet:precon/AhoyMateys_LCC"]["fixes"], [])
        self.assertEqual(by_id["gauntlet:precon/AhoyMateys_LCC"]["identity"], "UBR")
        self.assertEqual({e["id"] for e in built["excluded"]},
                         {"gauntlet:edhrec/edgar-markov-core", "gauntlet:edhrec/edgar-markov-upgraded",
                          "gauntlet:precon/SpellcraftScions_FDC"})

    def test_dry_run_saves_nothing(self):
        catalogue.build("constructed", dry_run=True, log=self.log.append)
        self.assertIsNone(catalogue.load("constructed"))

    def test_load_refuses_another_format_or_kind(self):
        built = catalogue.build("constructed", log=self.log.append)
        catalogue.save("commander", built)
        self.assertIsNone(catalogue.load("commander"))
        catalogue.save("constructed", dict(built, format=2))
        self.assertIsNone(catalogue.load("constructed"))

    def test_same_cards_same_sha(self):
        one = catalogue.build("constructed", log=self.log.append)
        two = catalogue.build("constructed", log=self.log.append)
        self.assertEqual(one["sha"], two["sha"])

    def test_unknown_format_or_source(self):
        with self.assertRaises(catalogue.GauntletError):
            catalogue.build("modern")
        with self.assertRaises(catalogue.GauntletError):
            catalogue.build("constructed", sources=("moxfield",))

    def test_fallback_tagging(self):
        tagged = catalogue.fallback_tag("commander", {"Commander": [[1, YSHTOLA]], "Main": [[1, "Counterspell"]]},
                                        ["Control"])
        self.assertEqual(tagged, {"identity": "WUB", "colours": "WUB", "metrics": {},
                                  "style": {"primary": "midrange", "tags": [], "themes": ["Control"]}})


if __name__ == "__main__":
    unittest.main()
