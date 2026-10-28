"""EDHREC ideas for a Commander deck (E9-S07, lib/edhrec.py and lib/api/edhrec.py): the commander's slug,
the page reduced and cached on the PC with the date it was fetched, a failure that keeps an older copy
(or says so plainly), and each card marked in the deck, free, in use or to buy for the deck's space,
only for a viewer who may see that space's inventory.

EDHREC is never reached: lib/edhrec._get is replaced by a fake page (PAGE, in EDHREC's layout as
checked on 2026-10-28), and the cache is a temporary folder.

Run from the repo root: python -m unittest decklab.tests.test_edhrec
"""
import contextlib
import io
import json
import tempfile
import unittest
import urllib.error
from datetime import timedelta
from pathlib import Path
from unittest import mock

from decklab.lib import edhrec, pool
from decklab.lib.api import edhrec as edhrec_api
from decklab.tests.test_editor import EditorTestCase


def view(name, decks, of=1000, synergy=0.1):
    return {"id": "x", "name": name, "sanitized": "x", "url": "/cards/x", "num_decks": decks,
            "potential_decks": of, "synergy": synergy, "lift": 1.0, "trend_zscore": 0.0}


# Ghalta's page: two of the deck's own cards, one it could add, white and banned cards EDHREC
# wouldn't list (checked anyway), a basic land, the commander, and a name Scryfall doesn't know.
PAGE = {"header": "Ghalta, Primal Hunger (Commander)", "panels": {}, "container": {"json_dict": {
    "card": {"name": "Ghalta, Primal Hunger", "num_decks": 1000},
    "cardlists": [
        {"header": "High Synergy Cards", "tag": "highsynergycards",
         "cardviews": [view("Llanowar Elves", 800), view("Elvish Mystic", 640), view("Pick Your Poison", 255)]},
        {"header": "Utility Artifacts", "tag": "utilityartifacts",
         "cardviews": [view("Sol Ring", 990), view("Black Lotus", 5), view("Wrath of God", 3)]},
        {"header": "Lands", "tag": "lands",
         "cardviews": [view("Forest", 999), view("Ghalta, Primal Hunger", 1), view("Not A Real Card", 9),
                       {"name": 7}]},
        {"header": "Empty", "cardviews": []}]}}}


class CacheTestCase(unittest.TestCase):

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.cache = Path(folder.name)
        self.get = mock.Mock(return_value=PAGE)
        for name, value in (("CACHE", self.cache), ("_get", self.get), ("_failed", {}), ("MIN_GAP", 0)):
            patcher = mock.patch.object(edhrec, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def age(self, slug, **delta):
        """Make the cached copy of slug that much older."""
        path = self.cache / f"{slug}.json"
        kept = json.loads(path.read_text(encoding="utf-8"))
        kept["fetched"] = (edhrec._now() - timedelta(**delta)).isoformat(timespec="seconds")
        path.write_text(json.dumps(kept), encoding="utf-8")


class SlugTests(unittest.TestCase):

    def test_names_as_edhrec_writes_them(self):
        for name, slug in (("Atraxa, Praetors' Voice", "atraxa-praetors-voice"),
                           ("Lim-Dûl the Necromancer", "lim-dul-the-necromancer"),
                           ("Y’shtola, Night’s Blessed", "yshtola-nights-blessed"),
                           ("Esika, God of the Tree // The Prismatic Bridge", "esika-god-of-the-tree"),
                           ("Kenrith, the Returned King", "kenrith-the-returned-king")):
            with self.subTest(name=name):
                self.assertEqual(edhrec.name_slug(name), slug)

    def test_two_commanders_are_tried_in_both_orders(self):
        self.assertEqual(edhrec.commander_slugs(["Tymna the Weaver", "Thrasios, Triton Hero"]),
                         ["thrasios-triton-hero-tymna-the-weaver", "tymna-the-weaver-thrasios-triton-hero"])
        self.assertEqual(edhrec.commander_slugs(["Ghalta, Primal Hunger"]), ["ghalta-primal-hunger"])
        self.assertEqual(edhrec.commander_slugs(["''"]), [])


class FetchTests(CacheTestCase):

    def test_the_page_is_reduced_and_kept_with_its_date(self):
        got = edhrec.fetch(["Ghalta, Primal Hunger"])
        self.get.assert_called_once_with("ghalta-primal-hunger")
        self.assertEqual((got["commander"], got["decks"], got["url"], got["stale"]),
                         ("Ghalta, Primal Hunger", 1000, "https://edhrec.com/commanders/ghalta-primal-hunger", None))
        self.assertEqual([g["header"] for g in got["lists"]], ["High Synergy Cards", "Utility Artifacts", "Lands"])
        self.assertEqual(got["lists"][0]["cards"][0], {"name": "Llanowar Elves", "decks": 800, "of": 1000, "synergy": 0.1})
        self.assertEqual(got["fetched"][:10], edhrec._now().date().isoformat())
        self.assertTrue((self.cache / "ghalta-primal-hunger.json").is_file())
        # A second ask, and another a few days on, read the copy; a week on, it's fetched again.
        edhrec.fetch(["Ghalta, Primal Hunger"])
        self.age("ghalta-primal-hunger", days=6)
        edhrec.fetch(["Ghalta, Primal Hunger"])
        self.assertEqual(self.get.call_count, 1)
        self.age("ghalta-primal-hunger", days=8)
        edhrec.fetch(["Ghalta, Primal Hunger"])
        self.assertEqual(self.get.call_count, 2)

    def test_refresh_waits_an_hour(self):
        edhrec.fetch(["Ghalta, Primal Hunger"])
        edhrec.fetch(["Ghalta, Primal Hunger"], refresh=True)
        self.assertEqual(self.get.call_count, 1)
        self.age("ghalta-primal-hunger", hours=2)
        edhrec.fetch(["Ghalta, Primal Hunger"], refresh=True)
        self.assertEqual(self.get.call_count, 2)

    def test_a_failure_keeps_the_older_copy_and_rests(self):
        edhrec.fetch(["Ghalta, Primal Hunger"])
        self.age("ghalta-primal-hunger", days=8)
        self.get.side_effect = edhrec.EdhrecError("EDHREC couldn't be reached (timed out)")
        got = edhrec.fetch(["Ghalta, Primal Hunger"])
        self.assertIn("timed out", got["stale"])
        self.assertEqual(len(got["lists"]), 3)
        # Not asked again for a few minutes.
        got = edhrec.fetch(["Ghalta, Primal Hunger"])
        self.assertEqual(self.get.call_count, 2)
        self.assertIn("a few minutes ago", got["stale"])

    def test_a_failure_with_nothing_cached_says_so(self):
        self.get.side_effect = edhrec.EdhrecError("EDHREC answered 500")
        with self.assertRaises(edhrec.EdhrecError) as caught:
            edhrec.fetch(["Ghalta, Primal Hunger"])
        self.assertNotIsInstance(caught.exception, edhrec.NoPage)
        with self.assertRaisesRegex(edhrec.EdhrecError, "a few minutes ago"):
            edhrec.fetch(["Ghalta, Primal Hunger"])
        self.assertEqual(self.get.call_count, 1)

    def test_no_page_tries_the_other_order_and_is_remembered(self):
        def get(slug):
            if slug.startswith("thrasios"):
                raise edhrec.NoPage("none")
            return PAGE
        self.get.side_effect = get
        got = edhrec.fetch(["Tymna the Weaver", "Thrasios, Triton Hero"])
        self.assertEqual(got["slug"], "tymna-the-weaver-thrasios-triton-hero")
        self.assertEqual([c.args[0] for c in self.get.call_args_list],
                         ["thrasios-triton-hero-tymna-the-weaver", "tymna-the-weaver-thrasios-triton-hero"])
        edhrec.fetch(["Tymna the Weaver", "Thrasios, Triton Hero"])
        self.assertEqual(self.get.call_count, 2)        # both answers kept: neither asked again
        self.get.side_effect = edhrec.NoPage("none")
        with self.assertRaises(edhrec.NoPage):
            edhrec.fetch(["Ghalta, Primal Hunger"])

    def test_an_unreadable_page_is_refused(self):
        for page in ({}, {"container": {"json_dict": {"cardlists": "no"}}},
                     {"container": {"json_dict": {"cardlists": [{"header": "X", "cardviews": []}]}}}):
            with self.subTest(page=page), self.assertRaises(edhrec.EdhrecError):
                edhrec.reduce_page(page, "x", edhrec._now())

    def test_the_request_names_deck_lab_and_only_the_commander(self):
        sent = []

        class Answer(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def urlopen(request, timeout):
            sent.append((request.full_url, request.get_header("User-agent"), timeout))
            return Answer(json.dumps(PAGE).encode())
        with mock.patch("urllib.request.urlopen", urlopen):
            got = edhrec_real_get("ghalta-primal-hunger")
        self.assertEqual(got["header"], PAGE["header"])
        self.assertEqual(sent, [("https://json.edhrec.com/pages/commanders/ghalta-primal-hunger.json",
                                 edhrec.USER_AGENT, edhrec.TIMEOUT)])
        self.assertIn("DeckLab", edhrec.USER_AGENT)

        def refused(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)
        with mock.patch("urllib.request.urlopen", refused), self.assertRaises(edhrec.NoPage):
            edhrec_real_get("no-such-commander")
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")),                 self.assertRaisesRegex(edhrec.EdhrecError, "couldn't be reached"):
            edhrec_real_get("ghalta-primal-hunger")


_REAL_GET = edhrec._get


def edhrec_real_get(slug):
    with mock.patch.object(edhrec, "MIN_GAP", 0):
        return _REAL_GET(slug)


class IdeasTests(EditorTestCase):
    """ideas() and GET /api/deck/edhrec in the editor's sandbox: commander/elf-commander (Ghalta, with
    Llanowar Elves and Sol Ring), whose collection has Llanowar Elves, Elvish Mystic and Black Lotus."""

    def setUp(self):
        super().setUp()
        self.cache = Path(tempfile.mkdtemp(dir=self.box.root))
        self.get = mock.Mock(return_value=PAGE)
        for name, value in (("CACHE", self.cache), ("_get", self.get), ("_failed", {}), ("MIN_GAP", 0)):
            patcher = mock.patch.object(edhrec, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def cards(self, answer):
        return {c["name"]: c for g in answer["groups"] for c in g["cards"]}

    def test_cards_are_marked_for_the_decks_space(self):
        p = pool.load_pool()
        answer = edhrec.ideas("commander/elf-commander", p)
        self.assertEqual((answer["commanders"], answer["identity"]), (["Ghalta, Primal Hunger"], "G"))
        got = self.cards(answer)
        # The commander and the basic land aren't ideas; white, banned and unknown cards are left out.
        self.assertEqual(set(got), {"Llanowar Elves", "Elvish Mystic", "Pick Your Poison", "Sol Ring"})
        self.assertEqual(answer["left_out"], [
            {"name": "Black Lotus", "why": "not legal in Commander"},
            {"name": "Not A Real Card", "why": "not a card Deck Lab knows"},
            {"name": "Wrath of God", "why": "outside the commander's colour identity"}])
        self.assertEqual([g["header"] for g in answer["groups"]], ["High Synergy Cards", "Utility Artifacts"])
        self.assertEqual((got["Llanowar Elves"]["status"], got["Llanowar Elves"]["inclusion"]), ("in_deck", 80))
        self.assertEqual(got["Sol Ring"]["status"], "in_deck")
        mystic = got["Elvish Mystic"]
        free = pool.free_copies(p, pool.self_ids("commander/elf-commander")).get("Elvish Mystic", 0)
        self.assertEqual(mystic["free"], free)
        self.assertEqual(mystic["status"], "free" if free else "in_use")
        poison = got["Pick Your Poison"]
        self.assertEqual((poison["status"], poison["free"], poison["inclusion"]), ("to_buy", 0, 26))
        self.assertIsNotNone(poison["aud_each"])
        self.assertIsNone(mystic["aud_each"])            # only a card to buy is priced
        self.assertIsNotNone(answer["rate"])
        self.assertEqual(answer["source"]["decks"], 1000)

    def test_a_decks_considering_cards_say_so(self):
        text = self.text("commander/elf-commander") + "\n## Considering\n\n```\n1 Pick Your Poison\n```\n"
        self.path("commander/elf-commander").write_bytes(text.encode("utf-8"))
        got = self.cards(edhrec.ideas("commander/elf-commander", pool.load_pool()))
        self.assertTrue(got["Pick Your Poison"]["considering"])
        self.assertFalse(got["Elvish Mystic"]["considering"])

    def test_the_command_line_prints_them_grouped(self):
        out = io.StringIO()
        with mock.patch("decklab.lib.inventory.entry.command", contextlib.nullcontext), \
                contextlib.redirect_stdout(out):
            self.assertEqual(edhrec.main(["commander/elf-commander"]), 0)
        text = out.getvalue()
        self.assertIn("EDHREC ideas for Ghalta, Primal Hunger (G): https://edhrec.com/commanders/ghalta-primal-hunger", text)
        self.assertIn("High Synergy Cards", text)
        self.assertIn(" 26%  Pick Your Poison  [to buy, ~A$", text)
        self.assertNotIn("Llanowar Elves", text)           # in the deck: only with --all
        self.assertIn("Left out: 3 card(s)", text)
        out = io.StringIO()
        with mock.patch("decklab.lib.inventory.entry.command", contextlib.nullcontext), \
                contextlib.redirect_stdout(out):
            edhrec.main(["commander/elf-commander", "--all", "--no-prices"])
        self.assertIn(" 80%  Llanowar Elves  [in the deck]", out.getvalue())
        err = io.StringIO()
        with mock.patch("decklab.lib.inventory.entry.command", contextlib.nullcontext), \
                contextlib.redirect_stderr(err):
            self.assertEqual(edhrec.main(["casual/gruul-test"]), 1)
            self.get.side_effect = edhrec.EdhrecError("EDHREC couldn't be reached (offline)")
            for path in self.cache.glob("*.json"):
                path.unlink()
            self.assertEqual(edhrec.main(["commander/elf-commander"]), 3)
        self.assertIn("Commander decks", err.getvalue())
        self.assertIn("offline", err.getvalue())

    def test_the_page_gets_marks_only_with_the_inventory(self):
        from decklab.lib.api.settings import _config_profiles
        matt = next(p for p in _config_profiles() if p["id"] == "matt")
        with mock.patch("decklab.lib.api.guard.viewer", return_value=matt):
            answer = edhrec_api.edhrec_view("commander/elf-commander")
        self.assertTrue(answer["marks"] and answer["may_add"])
        self.assertEqual(answer["sha256"], self.sha("commander/elf-commander"))
        self.assertNotIn("deck", answer)
        poison = self.cards(answer)["Pick Your Poison"]
        self.assertEqual(poison["status"], "to_buy")
        self.assertEqual(poison["card"]["name"], "Pick Your Poison")
        json.dumps(answer, allow_nan=False)
        with mock.patch("decklab.lib.api.guard.sees_inventory", return_value=False):
            hidden = edhrec_api.edhrec_view("commander/elf-commander")
        self.assertFalse(hidden["marks"] or hidden["may_add"])
        for c in self.cards(hidden).values():
            self.assertFalse({"status", "free", "on_the_way", "aud_each", "priced_printing"} & set(c), c)
        self.assertIsNone(hidden["rate"])
        self.assertTrue(self.cards(hidden)["Sol Ring"]["in_deck"])     # the deck's own list it may see

    def test_refusals(self):
        with mock.patch("decklab.lib.api.guard.sees_deck", return_value=False):
            self.assertApiError(404, edhrec_api.edhrec_view, "commander/elf-commander")
        self.assertApiError(404, edhrec_api.edhrec_view, "commander/no-such-deck")
        self.assertApiError(400, edhrec_api.edhrec_view, "casual/gruul-test", contains="Commander decks")
        self.assertApiError(400, edhrec_api.edhrec_view, None)
        self.get.side_effect = edhrec.NoPage("none")
        self.assertApiError(404, edhrec_api.edhrec_view, "commander/elf-commander", contains="no page")
        edhrec._failed.clear()
        for path in self.cache.glob("*.json"):
            path.unlink()
        self.get.side_effect = edhrec.EdhrecError("EDHREC couldn't be reached (offline)")
        self.assertApiError(502, edhrec_api.edhrec_view, "commander/elf-commander", contains="Try again later")

    def test_the_route_is_registered(self):
        from decklab.lib import feature_routes
        self.assertIn('("deck", "edhrec"): (edhrec.edhrec_view, ("id",))',
                      Path(feature_routes.__file__).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
