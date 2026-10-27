"""Tests for decklab.lib.precon_coverage and decklab.lib.api.precon_coverage (E1-S24): MTGJSON's
precons ranked by how much of each a space's free pool covers, one precon's missing cards with
their AUD estimates, and a new idea deck started from its list.

MTGJSON is never reached: test_precons' fixture lists are in the sandbox's cache, its deck
archive is a small tar.xz made here (_open_archive), and a refresh runs straight away instead of
in a thread (_start). Runs in test_collection_edit's sandbox (roles and the user2 and user3 spaces).

Run from the repo root: python -m unittest decklab.tests.test_precon_coverage
"""
import contextlib
import io
import json
import tarfile
import time
import urllib.error
from unittest import mock

from decklab.lib import precon_coverage as coverage
from decklab.lib import precons
from decklab.lib.api import precon_coverage as api
from decklab.lib.inventory import entry
from decklab.tests.test_precons import DINOS, ELVES, PreconTestCase


def archive(decks):
    """A tar.xz like MTGJSON's AllDeckFiles: AllDeckFiles/<file>.json for each {file: data}."""
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:xz") as tar:
        for file, data in decks.items():
            raw = json.dumps(data).encode("utf-8")
            member = tarfile.TarInfo(f"AllDeckFiles/{file}.json")
            member.size = len(raw)
            tar.addfile(member, io.BytesIO(raw))
    return out.getvalue()


# The archive has the two finished decks (and a Secret Lair drop, never indexed); Unfinished_TST,
# released after it was built, is read on its own from the copy Add a precon cached.
ARCHIVE = archive({"TestDinos_TST": DINOS, "ElfTheme_TST": ELVES,
                   "SomeDrop_SLD": {"data": {"mainBoard": [{"name": "Sol Ring", "setCode": "SLD", "number": "1",
                                                            "count": 1}]}}})


class CoverageTestCase(PreconTestCase):

    def setUp(self):
        super().setUp()
        self.opened = mock.Mock(side_effect=lambda: io.BytesIO(ARCHIVE))
        for target, name, value in ((coverage, "_open_archive", self.opened), (coverage, "_start", lambda work: work()),
                                    (coverage, "_state", {"running": False, "failed": None, "error": None}),
                                    (coverage, "_kept", {}), (coverage, "_needs", {}), (coverage, "PAUSE", 0),
                                    (api.add, "_added_on", lambda: "2026-10-28")):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def ranked(self, space="user2", **params):
        return api.coverage_view(space, **params)

    def files(self, view):
        return [(d["file"], d["covered"], d["cards"]) for d in view["decks"]]


class RankingTests(CoverageTestCase):

    def test_best_covered_first(self):
        # User2 owns 2 Llanowar Elves: 2 of Test Dinos' 5 non-basic cards (its 20 Forests left out), 2 of
        # Elf Theme's 10, none of Unfinished's 2 (its unreadable Sol Ring and full-art Forests aren't counted).
        view = self.ranked()
        self.assertEqual(self.files(view), [("TestDinos_TST", 2, 5), ("ElfTheme_TST", 2, 10), ("Unfinished_TST", 0, 2)])
        dinos = view["decks"][0]
        self.assertEqual((dinos["share"], dinos["missing"], dinos["kind"], dinos["name"], dinos["set_name"]),
                         (0.4, 3, "commander", "Test Dinos", "Test Commander"))
        self.assertEqual((view["date"], view["total"], view["types"]), ("2026-10-08", 3, ["Commander Deck", "Theme Deck"]))
        self.assertEqual({k: view["status"][k] for k in ("listed", "indexed", "updating", "error")},
                         {"listed": 3, "indexed": 3, "updating": False, "error": None})
        self.assertTrue(view["may_start"])

    def test_filtered_by_format_and_type(self):
        self.assertEqual([d["file"] for d in self.ranked(format="commander")["decks"]], ["TestDinos_TST", "Unfinished_TST"])
        casual = self.ranked(format="casual")
        self.assertEqual(([d["file"] for d in casual["decks"]], casual["types"]), (["ElfTheme_TST"], ["Theme Deck"]))
        self.assertEqual([d["file"] for d in self.ranked(type="Theme Deck")["decks"]], ["ElfTheme_TST"])
        self.assertEqual(self.ranked(limit="1")["total"], 3)
        self.assertEqual(len(self.ranked(limit="1")["decks"]), 1)
        for params in ({"format": "modern"}, {"type": "Secret Lair Drop"}, {"limit": "0"}, {"limit": "201"}):
            with self.subTest(params=params):
                self.assertApiError(400, self.ranked, **params)

    def test_copies_built_decks_hold_arent_free(self):
        # User3 adds Elf Theme as a built deck: the collection has all its cards, but none is free.
        with self.as_("user3"):
            self.add("ElfTheme_TST", "user3", profile="user3", title="Elves")
            view = self.ranked("user3")
        # Equal shares: the fewest cards to buy first.
        self.assertEqual(self.files(view), [("Unfinished_TST", 0, 2), ("TestDinos_TST", 0, 5), ("ElfTheme_TST", 0, 10)])

    def test_the_lists_are_read_once_and_kept(self):
        self.ranked()
        self.ranked("home")
        self.opened.assert_called_once()
        index = json.loads((self.cache / coverage.INDEX).read_text(encoding="utf-8"))
        self.assertEqual(sorted(index["decks"]), ["ElfTheme_TST", "TestDinos_TST", "Unfinished_TST"])
        self.assertIn(["Llanowar Elves", 2], index["decks"]["TestDinos_TST"]["cards"])
        self.assertNotIn("SomeDrop_SLD", index["decks"])      # not a paper deck
        # An archive older than ARCHIVE_TTL is read again; a recent deck's list after precons.TTL.
        index["archive_at"] = time.time() - coverage.ARCHIVE_TTL - 60
        (self.cache / coverage.INDEX).write_text(json.dumps(index), encoding="utf-8")
        coverage._kept.clear()
        self.ranked()
        self.assertEqual(self.opened.call_count, 2)

    def test_a_failed_archive_falls_back_to_single_decks_and_rests(self):
        # MTGJSON's archive can't be had: each listed deck is read on its own (here the copies Add a
        # precon cached), the problem is kept for the page, and nothing is tried again for RETRY_AFTER.
        self.opened.side_effect = OSError("offline")
        view = self.ranked()
        self.assertEqual(len(view["decks"]), 3)
        self.assertIn("archive couldn't be read", view["status"]["error"])
        self.ranked()
        self.opened.assert_called_once()

    def test_one_missing_deck_file_doesnt_stop_the_others(self):
        # A 404 for one deck's file is about that file: the other due decks are still read. A
        # connection failure or a server error means MTGJSON is down, and the rest wait.
        listed = [{"file": f} for f in ("Gone_TST", "Next_TST", "Last_TST")]

        def missing(file, now):
            if file == "Gone_TST":
                raise urllib.error.HTTPError(f"https://mtgjson.com/{file}.json", 404, "Not Found", {}, None)
            return {"at": now, "cards": []}

        for error, read in ((None, ["Gone_TST", "Next_TST", "Last_TST"]),
                            (urllib.error.HTTPError("u", 503, "Unavailable", {}, None), ["Gone_TST"]),
                            (urllib.error.URLError("offline"), ["Gone_TST"])):
            with self.subTest(error=error):
                calls = []

                def read_one(file, now, error=error):
                    calls.append(file)
                    if error is not None:
                        raise error
                    return missing(file, now)

                with mock.patch.object(coverage, "_archive_due", lambda index, now: False), \
                        mock.patch.object(coverage, "_read_one", read_one), \
                        mock.patch.object(coverage, "_index", lambda: {"decks": {}}):
                    problems = coverage.refresh(listed)
                self.assertEqual(calls, read)
                self.assertEqual(len(problems), 1)
                self.assertIn("Gone_TST couldn't be read", problems[0])

    def test_unread_decks_are_counted_while_the_lists_are_read(self):
        # In the background: the ranking shows what's read so far and says so.
        with mock.patch.object(coverage, "_start", lambda work: None):
            view = self.ranked()
        self.assertEqual((view["decks"], view["status"]["indexed"], view["status"]["updating"]), ([], 0, True))

    def test_no_copy_of_mtgjsons_lists_is_a_502(self):
        (self.cache / "DeckList.json").unlink()
        with mock.patch.object(precons, "_fetch", side_effect=OSError("offline")):
            self.assertApiError(502, self.ranked, contains="couldn't be fetched")

    def test_only_the_spaces_own_people_see_it(self):
        # As the Collection page: a space's own people only, the admin included (E10-S29), and a
        # missing space answers as a hidden one, naming no one.
        for profile, space in (("user2", "user3"), ("user2", "home"), ("matt", "user2"), ("matt", "nobody")):
            with self.subTest(profile=profile, space=space), self.as_(profile):
                for call in (lambda s=space: self.ranked(s), lambda s=space: api.coverage_deck("TestDinos_TST", s)):
                    error = self.assertApiError(403, call)
                    self.assertEqual((error.message, error.extra), ("That collection isn't public.", {}))
        self.opened.assert_not_called()                     # refused before anything was read
        with self.as_("user1"):
            self.assertTrue(self.ranked("home")["may_start"])


class DeckTests(CoverageTestCase):

    def test_missing_cards_with_their_estimates(self):
        view = api.coverage_deck("TestDinos_TST", "user2")
        self.assertEqual((view["kind"], view["title"], view["cards"], view["covered"], view["share"]),
                         ("commander", "Ghalta: Test Dinos", 5, 2, 0.4))
        self.assertEqual(sorted(r["name"] for r in view["missing"]), ["Elvish Mystic", "Ghalta, Primal Hunger", "Sol Ring"])
        self.assertNotIn("Llanowar Elves", [r["name"] for r in view["missing"]])
        self.assertEqual(view["totals"]["missing"], 3)
        self.assertIsNotNone(view["rate"])
        self.assertRegex(view["rate_date"], r"\d{4}-\d{2}-\d{2}")
        priced = [r for r in view["missing"] if r["aud_missing"] is not None]
        self.assertEqual(view["totals"]["aud_missing"], round(sum(r["aud_missing"] for r in priced), 2))
        # The dearest first, unpriced last; every row has its card for the page's picture.
        costs = [r["aud_missing"] for r in view["missing"]]
        self.assertEqual(costs, sorted(costs, key=lambda c: (c is None, -(c or 0))))
        self.assertEqual(view["missing"][0]["card"]["name"], view["missing"][0]["name"])
        # Nothing names the decks holding copies.
        self.assertNotIn("in_use_elsewhere", view["missing"][0])
        self.assertApiError(404, api.coverage_deck, "Nothing_TST", "user2")
        self.assertApiError(400, api.coverage_deck, "../escape", "user2")

    def test_start_a_deck_from_it(self):
        before = self.rows("user2")
        with self.as_("user2"):
            answer = self.call(api.start_deck, "user2", space="user2", file="TestDinos_TST", title="Ghalta Next")
        self.assertEqual(answer["id"], "user2/commander/ghalta-next")
        self.assertEqual(self.rows("user2"), before)          # nothing goes into the collection
        self.assertEqual(self.last_write(), ("new deck Ghalta Next", "User2"))
        text = (self.box.magic / "people" / "user2" / "decks" / "commander" / "ghalta-next.md").read_text(encoding="utf-8")
        self.assertIn("- **Status:** idea", text)
        self.assertIn("Commander\n1 Ghalta, Primal Hunger (RIX) 130 *F*\n", text)
        self.assertIn("\n20 Forest\n", text)
        self.assertIn("Started in Deck Lab on 2026-10-28 by User2 from the Test Dinos precon's list", text)
        self.assertIn("| Sol Ring | 1 | 0 | **1** |", text)
        # The name is now taken: 409, naming the deck.
        with self.as_("user2"):
            error = self.assertApiError(409, self.call, api.start_deck, "user2", space="user2", file="TestDinos_TST",
                                        title="Ghalta Next")
        self.assertEqual(error.extra["conflict"]["id"], "user2/commander/ghalta-next")

    def test_starting_follows_deck_create(self):
        # deck.create on the space, as POST /api/decks: not in another's space, not the admin in a member's.
        for profile, space in (("user2", "user3"), ("user2", "home"), ("matt", "user2")):
            with self.subTest(profile=profile, space=space), self.as_(profile):
                before = self.writes_made()
                error = self.assertApiError(403, self.call, api.start_deck, profile, space=space, file="ElfTheme_TST",
                                            title="Elves")
                self.assertEqual(error.extra, {})
                self.assertEqual(self.writes_made(), before)
        with self.as_("matt"):
            self.assertTrue(self.ranked("home")["may_start"])
        with self.as_("user1"):
            answer = self.call(api.start_deck, "user1", file="ElfTheme_TST", title="Her Elves")
        self.assertEqual(answer["id"], "casual/her-elves")
        self.assertIn("- **Played by:** wife", (self.box.magic / "decks" / "casual" / "her-elves.md").read_text(encoding="utf-8"))

    def test_a_list_that_cant_be_matched_starts_nothing(self):
        before = self.writes_made()
        error = self.assertApiError(400, self.call, api.start_deck, "user2", space="user2", file="Unfinished_TST",
                                    title="Unfinished")
        self.assertTrue(error.extra["problems"])
        self.assertEqual(self.writes_made(), before)


class CommandLineTests(CoverageTestCase):

    def test_prints_the_best_covered(self):
        out = io.StringIO()
        with mock.patch.object(entry, "command", contextlib.nullcontext), contextlib.redirect_stdout(out):
            self.assertEqual(coverage.main(["--space", "user2", "--format", "commander"]), 0)
        lines = out.getvalue().splitlines()
        self.assertIn("Reading MTGJSON's precon lists", lines[0])
        self.assertEqual(lines[1].split(), ["40%", "2/5", "Test", "Dinos", "(Test", "Commander,", "Commander", "Deck,", "2026)"])
        self.assertIn("Unfinished", lines[2])
        self.assertEqual(lines[3], "2 of 2 precons' lists read; MTGJSON's lists of 2026-10-08.")
