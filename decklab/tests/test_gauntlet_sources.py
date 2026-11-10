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

    def test_every_duel_version_and_the_precons(self):
        records, excluded = forge_source.constructed_decks(QUEST, log=lambda *a: None)
        self.assertEqual([r["id"] for r in records], ["gauntlet:forge/duels/agent-k-1", "gauntlet:forge/duels/agent-k-2",
                                                      "gauntlet:forge/precons/aerodoom"])
        self.assertEqual([r["duel_title"] for r in records[:2]], ["Agent K", "Agent K"])
        self.assertEqual(records[1]["tier"], "medium")
        self.assertEqual(records[2]["tier"], "precon")
        self.assertEqual(excluded, [])
        self.assertEqual(records[1]["cards"][0], [24, "Swamp"])

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
        self.assertEqual(by_id["gauntlet:forge/duels/agent-k-1"]["duel_title"], "Agent K")
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

    def test_no_source_of_the_format_refuses(self):
        with self.assertRaises(catalogue.GauntletError):
            catalogue.build("constructed", sources=("edhrec",), log=self.log.append)
        with self.assertRaises(catalogue.GauntletError):
            catalogue.build("commander", sources=("forge",), log=self.log.append)
        self.assertIsNone(catalogue.load("constructed"))

    def test_a_source_that_gives_no_deck_keeps_the_saved_catalogue(self):
        before = catalogue.build("constructed", log=self.log.append)
        self.patch(forge_source, "constructed_decks", lambda *a: ([], [("gauntlet:forge", "unreadable")]))
        with self.assertRaises(catalogue.GauntletError) as raised:
            catalogue.build("constructed", log=self.log.append)
        self.assertIn("kept as it was", str(raised.exception))
        self.assertEqual(catalogue.load("constructed"), before)

    def test_edhrec_unreachable_keeps_the_commander_catalogue(self):
        shutil.copytree(GAUNTLET / "mtgjson", self.tmp / "mtgjson")
        before = catalogue.build("commander", top=2, log=self.log.append)
        self.patch(edhrec, "get_json", lambda path: (_ for _ in ()).throw(edhrec.EdhrecError("down")))
        shutil.rmtree(gauntlet.sources_dir("edhrec"))         # no cached copy to fall back on
        with self.assertRaises(catalogue.GauntletError):
            catalogue.build("commander", top=2, log=self.log.append)
        self.assertEqual(catalogue.load("commander"), before)

    def test_a_build_of_one_source_keeps_the_others_decks(self):
        shutil.copytree(GAUNTLET / "mtgjson", self.tmp / "mtgjson")
        catalogue.build("commander", top=2, log=self.log.append)
        built = catalogue.build("commander", sources=("edhrec",), top=2, log=self.log.append)
        ids = {d["id"] for d in built["decks"]}
        self.assertIn("gauntlet:precon/AhoyMateys_LCC", ids)
        self.assertIn("gauntlet:edhrec/yshtola-nights-blessed-core", ids)
        self.assertIn("gauntlet:precon/SpellcraftScions_FDC", {e["id"] for e in built["excluded"]})
        self.assertEqual(catalogue.load("commander"), built)

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

    def test_tagging_is_tags_tag(self):
        from decklab.lib.gauntlet import tags
        listed = {"Commander": [[1, YSHTOLA]], "Main": [[1, "Counterspell"]]}
        tagged = catalogue._tag("commander", listed, ["Control"])
        self.assertEqual(tagged, tags.tag("commander", listed, ["Control"]))
        self.assertEqual(tagged["identity"], "WUB")
        self.assertEqual(tagged["style"]["themes"], ["Control"])


class BuildDifference(GauntletCase):
    """E3-S43: before saving, a build prints what it would change against the saved catalogue."""

    def setUp(self):
        super().setUp()
        self.patch(catalogue, "FORGE_ROOT", QUEST)
        self.patch(catalogue, "LIMITS", fake_limits())
        self.log = []

    @staticmethod
    def deck(n, sha=None, tier="medium", playable=True):
        colour = "WUBRG"[n % 5]
        return {"id": f"gauntlet:forge/duels/d{n:02d}", "title": f"Duel {n}", "kind": "constructed",
                "card_sha": sha or f"{n:064x}", "tier": tier, "identity": colour, "colours": colour,
                "style": {"primary": "aggro"}, "playable": playable, "source": {"kind": "forge"}, "cards": {}}

    def cat(self, decks, built="2026-08-01T10:00:00+00:00"):
        return {"format": 1, "kind": "constructed", "built": built, "sha": catalogue.catalogue_sha(decks),
                "decks": decks, "excluded": []}

    def test_no_saved_catalogue(self):
        lines = catalogue.difference(None, self.cat([self.deck(1)]), "constructed")
        self.assertEqual(lines, ["There's no saved constructed catalogue yet, so no saved results depend on one."])

    def test_the_same_catalogue_changes_nothing(self):
        old = self.cat([self.deck(n) for n in range(3)])
        new = self.cat([self.deck(n) for n in range(3)], built="2026-11-10T00:00:00+00:00")
        self.assertEqual(catalogue.difference(old, new, "constructed"), [
            f"Against the saved catalogue (built 2026-08-01, {old['sha'][:8]}): 0 opponents' lists changed, "
            "0 joined and 0 left.",
            "The standard sample would keep its 3 opponents and their lists, so its saved results still count."])

    def test_changed_joined_and_left_are_counted_with_the_standard_sample(self):
        old = self.cat([self.deck(n) for n in range(4)])
        new = self.cat([self.deck(0), self.deck(1, sha="f" * 64), self.deck(2), self.deck(4), self.deck(5)])
        lines = catalogue.difference(old, new, "constructed")
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].endswith("1 opponent's list changed, 2 joined and 1 left."), lines[0])
        # Every playable medium deck fits the 24-deck standard sample here: 3 leaves, 4 and 5 join, 1 changed.
        self.assertEqual(lines[1], "The standard sample would change: 1 of its 4 opponents would leave, 2 would "
                         "join, and 1 that stay would have a changed list. Saved results against the 2 opponents "
                         "that stay unchanged still count; the others are set aside until those opponents are "
                         "played again.")

    def test_a_change_outside_the_standard_sample_keeps_its_results(self):
        # An easy deck is never in the 60-card standard sample (medium and hard only).
        old = self.cat([self.deck(0), self.deck(1), self.deck(2, tier="easy")])
        new = self.cat([self.deck(0), self.deck(1), self.deck(2, sha="e" * 64, tier="easy")])
        lines = catalogue.difference(old, new, "constructed")
        self.assertTrue(lines[0].endswith("1 opponent's list changed, 0 joined and 0 left."), lines[0])
        self.assertEqual(lines[1], "The standard sample would keep its 2 opponents and their lists, so its saved "
                         "results still count.")

    def test_a_deck_no_longer_playable_leaves_the_standard_sample(self):
        # The catalogue's sha (ids and lists) is the same: only the screen changed, as a new Forge's would.
        old = self.cat([self.deck(0), self.deck(1)])
        new = self.cat([self.deck(0), self.deck(1, playable=False)])
        self.assertEqual(old["sha"], new["sha"])
        lines = catalogue.difference(old, new, "constructed")
        self.assertIn("1 of its 2 opponents would leave, 0 would join", lines[1])

    def test_a_damaged_saved_catalogue_never_stops_the_comparison(self):
        # load() checks only that "decks" is a list: entries that aren't decks are left out, not raised on.
        old = self.cat([self.deck(0), self.deck(1)])
        old["decks"] += ["junk", {"title": "no id"}, {"id": ["a list"]}, None]
        new = self.cat([self.deck(0), self.deck(1, sha="f" * 64)])
        lines = catalogue.difference(old, new, "constructed")
        self.assertTrue(lines[0].endswith("1 opponent's list changed, 0 joined and 0 left."), lines[0])
        self.assertIn("0 of its 2 opponents would leave, 0 would join, and 1 that stay", lines[1])
        # A deck without what sampling reads: the first line still prints, and the second says it couldn't.
        broken = self.cat([self.deck(0)])
        broken["decks"].append({"id": "gauntlet:forge/duels/odd", "playable": True, "tier": "medium",
                                "style": "aggro", "identity": 5})
        lines = catalogue.difference(broken, new, "constructed")
        self.assertEqual(len(lines), 2)
        self.assertIn("joined and 1 left.", lines[0])

    def test_a_build_prints_it_before_saving_and_a_dry_run_too(self):
        order = []
        real_save = catalogue.save

        def save(fmt, cat):
            order.append("saved")
            real_save(fmt, cat)
        self.patch(catalogue, "save", save)
        first = catalogue.build("constructed", log=order.append)
        said = next(i for i, line in enumerate(order) if line.startswith("There's no saved constructed catalogue"))
        self.assertLess(said, order.index("saved"))
        del order[:]
        catalogue.build("constructed", log=order.append)
        said = next(i for i, line in enumerate(order) if "0 opponents' lists changed" in line)
        self.assertIn(first["sha"][:8], order[said])
        self.assertLess(said, order.index("saved"))
        # A dry run compares too, and saves nothing.
        changed = dict(first, decks=first["decks"][1:])
        changed["sha"] = catalogue.catalogue_sha(changed["decks"])
        real_save("constructed", changed)
        del order[:]
        catalogue.build("constructed", dry_run=True, log=order.append)
        self.assertTrue(any("lists changed, 1 joined and 0 left." in line for line in order), order)
        self.assertNotIn("saved", order)
        self.assertEqual(catalogue.load("constructed")["sha"], changed["sha"])

    def test_a_failed_build_prints_no_difference(self):
        catalogue.build("constructed", log=self.log.append)
        del self.log[:]
        self.patch(forge_source, "constructed_decks", lambda *a: ([], [("gauntlet:forge", "unreadable")]))
        with self.assertRaises(catalogue.GauntletError):
            catalogue.build("constructed", log=self.log.append)
        self.assertFalse(any("saved catalogue" in line for line in self.log), self.log)


if __name__ == "__main__":
    unittest.main()
