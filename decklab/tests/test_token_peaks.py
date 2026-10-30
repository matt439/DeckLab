"""The deck page's suggested token counts (E7-S08): the card log's per-game token peaks pooled over a
list's saved Forge results (saved._pooled_tokens, forge.tokenpeaks.list_token_peaks), matched to the
deck's token needs by name (tokens.peaks.annotate), and deck_view's tokens with them, only for viewers
who see the deck's Tokens part and only from results whose every side the viewer sees.

Every result is made by hand (test_forge.stored) with "cards" records in the card log's version 3
shape, so no Forge runs; the deck page tests use test_api_tokens' temp repository and
test_token_counters' card index (fixtures/tokens_cards.jsonl: Hornet Queen makes Insects).

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_token_peaks
"""
import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from decklab.lib import access, decks
from decklab.lib.api import deck_page, guard, token_peaks
from decklab.lib.forge import cardlog, common as forge_common, saved, tokenpeaks
from decklab.lib.forge.lists import card_sha
from decklab.lib.tokens import peaks
from decklab.tests import household_config
from decklab.tests import test_api_tokens as token_fixture
from decklab.tests.test_forge import stored
from decklab.tests.test_token_counters import extended_index
from decklab.tests.test_workspace_ui import NODE, WEB

LIST = "Deck\n1 Hornet Queen\n20 Forest\n"


def record(games=10, tokens=None, v=3):
    """A batch's "cards" record (version 3, no rows) with tokens' peak counts per side (None: no key)."""
    out = {"v": v, "games": games, "bad": 0, "wins": [games, 0], "first": [games // 2, games - games // 2],
           "rows": [{}, {}], "commander": [{}, {}]}
    if tokens is not None:
        out["tokens"] = copy.deepcopy(tokens)
    return out


def result(*records, sha=None, other="b" * 64, key="c", opponent="casual/bbb"):
    """A saved result of LIST (side 0, sha) against another list: one batch of 10 games per record."""
    out = stored([(0, "win", i % 2) for i in range(10)])
    one = out["batches"][0]
    out["batches"] = []
    for n, rec in enumerate(records):
        batch = dict(copy.deepcopy(one), n=n, seed=n + 1)
        if rec is not None:
            batch["cards"] = rec
        out["batches"].append(batch)
    out["sides"][0]["card_sha"] = sha or card_sha(decks.parse_decklist(LIST), "constructed")
    out["sides"][1]["card_sha"] = other
    out["sides"][1]["seen_as"][0]["id"] = opponent
    out["key"] = key * 64
    return out


# ============================================================ pooling a result's batches

class PooledTokensTests(unittest.TestCase):

    def test_the_caps_agree(self):
        self.assertEqual(saved.PEAK_CAP, cardlog.PEAK_CAP)
        self.assertEqual(peaks.PEAK_CAP, cardlog.PEAK_CAP)

    def test_tallied_batches_add_up_and_the_rest_are_untallied_or_left_out(self):
        good = record(tokens=[{"Insect Token": [2, 3]}, {"Saproling Token": [1]}])
        more = record(tokens=[{"Insect Token": [1, 0, 4], "Cat Token": [1]}, {}])
        older = record()                                            # before the tally
        bad = record(tokens=[{"Insect Token": [0]}, {}])            # ends with a 0
        version1 = record(v=1)                                      # an earlier card log's: untallied too
        malformed = record(v=9)                                     # no card record of any version: left out
        pooled = saved._pooled_tokens(result(good, more, older, bad, None, version1, malformed), 0)
        self.assertEqual(pooled, {"games": 20, "batches": 2, "untallied": 30,
                                  "tokens": {"Insect Token": [3, 3, 4], "Cat Token": [1]}})
        self.assertEqual(saved._pooled_tokens(result(good), 1)["tokens"], {"Saproling Token": [1]})

    def test_malformed_tallies_dont_count(self):
        for tokens in ([{"Insect Token": [11]}, {}],                 # more games than the record's
                       [{"Insect Token": [1] * 31}, {}],              # longer than the cap
                       [{"": [1]}, {}], [{"Insect Token": [-1, 1]}, {}], [{"Insect Token": [True]}, {}],
                       [{"Insect Token": []}, {}], [{}], {"Insect Token": [1]}, [[], {}]):
            with self.subTest(tokens=tokens):
                pooled = saved._pooled_tokens(result(record(tokens=tokens)), 0)
                self.assertEqual((pooled["games"], pooled["untallied"], pooled["tokens"]), (0, 10, {}))


# ============================================================ a list over its saved results

class ListTokenPeaksTests(unittest.TestCase):

    def setUp(self):
        self.sections = decks.parse_decklist(LIST)

    def test_a_list_pools_its_results_and_a_mirror_counts_both_sides(self):
        first = result(record(tokens=[{"Insect Token": [2, 3]}, {}]), key="1")
        second = result(record(), record(tokens=[{"Insect Token": [0, 0, 1]}, {}]), key="2")
        other = result(record(tokens=[{"Insect Token": [9]}, {}]), sha="0" * 64, key="3")
        mirror = result(record(tokens=[{"Insect Token": [1]}, {"Insect Token": [0, 1]}]), key="4")
        mirror["sides"][1]["card_sha"] = mirror["sides"][0]["card_sha"]
        found = tokenpeaks.list_token_peaks(self.sections, "constructed", [first, second, other, mirror])
        self.assertEqual(found, {"games": 40, "batches": 4, "untallied": 10, "matchups": 3,
                                 "tokens": {"Insect Token": [3, 4, 1]}})

    def test_keep_leaves_a_result_out_before_anything_counts(self):
        seen = result(record(tokens=[{"Insect Token": [2]}, {}]), key="1")
        hidden = result(record(tokens=[{"Insect Token": [0, 0, 0, 5]}, {}]), key="2", opponent="user2/casual/elves")
        found = tokenpeaks.list_token_peaks(self.sections, "constructed", [seen, hidden],
                                            keep=lambda r: r["sides"][1]["seen_as"][0]["id"] != "user2/casual/elves")
        self.assertEqual((found["games"], found["tokens"]), (10, {"Insect Token": [2]}))
        self.assertIsNone(tokenpeaks.list_token_peaks(self.sections, "constructed", [hidden], keep=lambda r: False))

    def test_no_result_of_the_list_is_none_and_one_without_the_tally_has_games_0(self):
        self.assertIsNone(tokenpeaks.list_token_peaks(self.sections, "constructed", []))
        self.assertIsNone(tokenpeaks.list_token_peaks(self.sections, "constructed",
                                                      [result(record(), sha="0" * 64)]))
        found = tokenpeaks.list_token_peaks(self.sections, "constructed", [result(record(), None)])
        self.assertEqual((found["games"], found["untallied"], found["matchups"]), (0, 10, 0))

    def test_saved_results_count_only_todays_card_log_engine(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        today = result(record(tokens=[{"Insect Token": [1, 1]}, {}]), key="1")
        before = result(record(tokens=[{"Insect Token": [7]}, {}]), key="2")
        today["sides"][0]["engine_id"], before["sides"][0]["engine_id"] = "today", "before"
        for r in (today, before):
            (folder / f"{r['key']}.json").write_text(json.dumps(r), encoding="utf-8")
        with mock.patch.object(tokenpeaks, "_wanted", return_value="today") as wanted:
            found = tokenpeaks.list_token_peaks(self.sections, "constructed", results_dir=folder)
        self.assertEqual((found["games"], found["tokens"], found["other_engine_games"]),
                         (10, {"Insect Token": [1, 1]}, 10))
        self.assertNotIn("other_engine_games", tokenpeaks.list_token_peaks(self.sections, "constructed", [today]))
        with mock.patch.object(tokenpeaks, "_wanted", side_effect=AssertionError("not asked")):
            self.assertIsNone(tokenpeaks.list_token_peaks(decks.parse_decklist("Deck\n20 Forest\n"), "constructed",
                                                          results_dir=folder))
        wanted.assert_called_once()

    def test_only_another_engines_games_have_games_0_and_say_so(self):
        # Right after an engine change: the list's saved games are all another engine's, so the page
        # says they need playing again (not that there are none), as list_cards' other_engine_games.
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        before = result(record(tokens=[{"Insect Token": [7]}, {}]), record(), key="2")
        before["sides"][0]["engine_id"] = "before"
        (folder / f"{before['key']}.json").write_text(json.dumps(before), encoding="utf-8")
        with mock.patch.object(tokenpeaks, "_wanted", return_value="today"):
            found = tokenpeaks.list_token_peaks(self.sections, "constructed", results_dir=folder)
            hidden = tokenpeaks.list_token_peaks(self.sections, "constructed", results_dir=folder,
                                                 keep=lambda r: False)
        self.assertEqual(found, {"games": 0, "batches": 0, "untallied": 0, "tokens": {}, "matchups": 0,
                                 "other_engine_games": 20})
        self.assertIsNone(hidden)


# ============================================================ matching the deck's needs

def need(name, **fields):
    return {"key": f"id-{name}", "name": name, "kind": "token", "face_names": [name], "side": "own", "usable": 0,
            "state": "none", **fields}


class AnnotateTests(unittest.TestCase):

    def pooled(self, tokens, games=100, untallied=0):
        return {"games": games, "batches": 2, "untallied": untallied, "matchups": 2, "tokens": tokens}

    def test_a_need_gets_its_peak_and_most_games(self):
        result = {"needs": [need("Rabbit", usable=2)], "note": "x"}
        before = copy.deepcopy(result)
        out = peaks.annotate(result, self.pooled({"Rabbit Token": [4, 3, 1, 1, 0, 0, 1]}))
        self.assertEqual(result, before)                       # a copy: the cached result is untouched
        found = out["needs"][0]["forge"]
        self.assertEqual(found, {"name": "Rabbit", "games": 10, "of": 100, "peak": 7, "most": 4, "together": False,
                                 "more": 2, "words": "Forge games peaked at 7; most games at most 4 (10 games of "
                                                    "100 made one) · 2 more than the cards that fit"})
        self.assertEqual(out["forge"], {"games": 100, "matchups": 2, "untallied": 0, "note": peaks.NOTE})
        self.assertEqual(out["note"], "x")

    def test_names_match_by_face_case_and_accents_without_token(self):
        out = peaks.annotate({"needs": [need("Zombie", face_names=["Zombie", "Zombie Knight"]), need("Treasure")]},
                             self.pooled({"zombie knight token": [1], "Treasure": [0, 2], "Cat Token": [5]}))
        self.assertEqual([(n["forge"]["peak"], n["forge"]["games"]) for n in out["needs"]], [(1, 1), (2, 2)])

    def test_unmade_shared_opponent_emblem_and_copy_needs(self):
        needs = [need("Soldier", key="s1"), need("Soldier", key="s2"), need("Goblin"),
                 need("Spirit", side="opponent"), need("Elspeth Emblem", kind="emblem"), need("Copy")]
        out = peaks.annotate({"needs": needs}, self.pooled({"Soldier Token": [1, 1], "Spirit Token": [3]}))
        soldier, again, goblin, spirit, emblem, copied = out["needs"]
        self.assertTrue(soldier["forge"]["together"] and again["forge"]["together"])
        self.assertIn("every Soldier token counted together", soldier["forge"]["words"])
        self.assertEqual(goblin["forge"]["words"], "No Forge game of the 100 put one on the battlefield")
        self.assertEqual((goblin["forge"]["peak"], goblin["forge"]["more"]), (0, 0))
        for left in (spirit, emblem, copied):
            self.assertNotIn("forge", left)

    def test_a_peak_at_the_cap_says_or_more(self):
        out = peaks.annotate({"needs": [need("Rabbit")]}, self.pooled({"Rabbit Token": [0] * 29 + [3]}))
        self.assertTrue(out["needs"][0]["forge"]["words"].startswith(
            "Forge games peaked at 30 or more; most games at most 30 or more"))

    def test_no_games_and_untallied_games_say_why(self):
        for pooled, why in ((None, peaks.NO_GAMES), (self.pooled({}, games=0, untallied=40),
                                                     peaks.UNTALLIED.format(games=40)),
                            (dict(self.pooled({}, games=0), other_engine_games=20), peaks.OTHER_ENGINE.format(games=20)),
                            (dict(self.pooled({}, games=0, untallied=40), other_engine_games=20),
                             peaks.OLDER.format(games=60))):
            out = peaks.annotate({"needs": [need("Rabbit")]}, pooled)
            self.assertEqual(out["forge"], {"games": 0, "why": why})
            self.assertNotIn("forge", out["needs"][0])
        for empty in ({"needs": []}, {"unavailable": "x"}, None):
            self.assertIs(peaks.annotate(empty, self.pooled({})), empty)


# ============================================================ the deck page

class DeckPageTests(token_fixture.TokensApiTestCase):
    """Only the Tokens part's viewers get the counts, and only from results whose sides they see."""

    @classmethod
    def setUpClass(cls):
        cls.loaded = extended_index()

    def index(self):
        return self.loaded

    def setUp(self):
        household_config.use(self)
        super().setUp()
        self.write("decks/casual/hive.md", token_fixture.deck_md("Hive", deck=LIST))
        self.results = self.root / "forge-data" / "results"
        self.results.mkdir(parents=True)
        for target, name, value in ((forge_common, "DATA_DIR", self.root / "forge-data"),
                                    (tokenpeaks, "_wanted", lambda sha, kind: "today")):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def save(self, *results):
        queen = card_sha(decks.load_deck("casual/queen", "target"), "constructed")
        for r in results:
            if r["sides"][1]["seen_as"][0]["id"] == "casual/queen":
                r["sides"][1]["card_sha"] = queen
            r["sides"][0]["engine_id"] = "today"
            (self.results / f"{r['key']}.json").write_text(json.dumps(r), encoding="utf-8")

    def view(self, profile):
        with access.using({"profile": profile, "email": "", "remote": True}), access.answering(False), \
                mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home"})), \
                mock.patch.object(guard, "public_spaces", return_value=frozenset()), \
                mock.patch.object(guard, "public_owners", return_value=frozenset()), \
                mock.patch.object(deck_page, "_deck_stats", return_value=None), \
                mock.patch.object(deck_page, "_deck_practice", return_value=None), \
                mock.patch.object(deck_page, "usual_opponents", return_value=[]):
            return deck_page.deck_view("casual/hive", omit=("matchups",))

    def insect(self, answer):
        return next(n for n in answer["tokens"]["needs"] if n["name"] == "Insect")

    def test_home_sees_counts_from_visible_matchups_only_and_a_member_gets_no_token_part(self):
        self.save(result(record(tokens=[{"Insect Token": [5, 4, 1]}, {}]), key="1", opponent="casual/queen"),
                  result(record(tokens=[{"Insect Token": [0] * 19 + [9]}, {}]), key="2", opponent="user2/casual/elves"))
        answer = self.view("matt")
        found = self.insect(answer)["forge"]
        self.assertEqual((found["peak"], found["most"], found["games"], found["of"]), (3, 2, 10, 10))
        self.assertEqual(found["more"], max(2 - self.insect(answer)["usable"], 0))
        self.assertEqual(answer["tokens"]["forge"]["games"], 10)
        member = self.view("user2")          # the deck is public; home's inventory isn't
        self.assertNotIn("tokens", member)
        serialized = json.dumps(member)
        for private in ("Forge games peaked", peaks.NOTE[:40], peaks.NO_GAMES[:30]):
            self.assertNotIn(private, serialized)

    def test_no_saved_games_says_why_and_a_failure_leaves_the_part(self):
        answer = self.view("matt")
        self.assertEqual(answer["tokens"]["forge"], {"games": 0, "why": peaks.NO_GAMES})
        self.assertNotIn("forge", self.insect(answer))
        with mock.patch.object(tokenpeaks, "list_token_peaks", side_effect=RuntimeError("broken")):
            failed = self.view("matt")
        self.assertEqual(failed["tokens"]["forge"], {"games": 0, "why": token_peaks.FAILED})
        self.assertEqual(self.insect(failed)["state"], self.insect(answer)["state"])
        self.assertTrue(any("token peaks" in line for line in self.logs))


# ============================================================ the page's pieces (token-peaks.js)

# Runs token-peaks.js with el() and plural() standing in as plain objects, and prints what each piece made.
SCRIPT = """
const fs = require("fs"), vm = require("vm");
const [web, cases] = JSON.parse(fs.readFileSync(0, "utf8"));
const context = {
  el: (tag, attrs, ...children) => ({ tag, class: attrs.class || null, text: attrs.text || null,
    children: children.flat().filter((c) => c !== null && c !== undefined) }),
  plural: (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`,
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(web + "/token-peaks.js", "utf8"), context);
const line = vm.runInContext("tokenPeakLine", context), part = vm.runInContext("tokenPeaksPart", context);
process.stdout.write(JSON.stringify(cases.map(([which, value]) => (which === "line" ? line : part)(value))));
"""


def texts(node):
    """Every text in a made node, in order."""
    if not isinstance(node, dict):
        return [node] if isinstance(node, str) else []
    return ([node["text"]] if node["text"] else []) + [t for child in node["children"] for t in texts(child)]


@unittest.skipUnless(NODE, "Node.js isn't installed")
class PageTests(unittest.TestCase):

    def run_page(self, cases):
        done = subprocess.run([NODE, "-e", SCRIPT], input=json.dumps([str(WEB), cases]), capture_output=True,
                              text=True, encoding="utf-8", timeout=20)
        if done.returncode:
            raise AssertionError(done.stderr)
        return json.loads(done.stdout)

    def test_the_lines_say_estimate_from_simulated_games(self):
        made = self.run_page([
            ["line", {"words": "Forge games peaked at 7; most games at most 4 (10 games of 100 made one)"}],
            ["line", None],
            ["part", {"games": 100, "matchups": 2, "untallied": 40, "note": peaks.NOTE}],
            ["part", {"games": 0, "why": peaks.NO_GAMES}],
            ["part", None]])
        self.assertEqual(texts(made[0]), ["Estimate from simulated games: Forge games peaked at 7; most games at most 4 "
                                          "(10 games of 100 made one)"])
        self.assertIsNone(made[1])
        self.assertEqual(texts(made[2]), ["Suggested counts from 100 simulated Forge games in 2 matchups (40 earlier "
                                          "games didn't count tokens): approximate", peaks.NOTE])
        self.assertEqual(texts(made[3]), [peaks.NO_GAMES])
        self.assertIsNone(made[4])


if __name__ == "__main__":
    unittest.main()
