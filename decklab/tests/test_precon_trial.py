"""Tests for E3-S39, Try a precon before buying it: decklab.lib.decks.trial (the Trial header line,
kept by every save but a status change), the library summary's "trial", and
decklab.lib.api.precon_trial (GET/POST /api/precons/trial and POST /api/precons/trial/keep), plus
Add a precon's "trials" answer and the command line's line about them.

MTGJSON is never reached (test_precons' fixture lists in the sandbox's cache) and nothing is
written outside the sandbox's files. Runs in test_collection_edit's sandbox (roles, the user2
and user3 spaces).

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_precon_trial
"""
import contextlib
import io
import unittest

from decklab.lib import decks
from decklab.lib.api import precon_trial as api
from decklab.lib.api import precons as add
from decklab.tests.test_precons import PreconTestCase, card

# A 60-card Theme Deck: casual, and big enough to test against the 60-card field and gauntlet.
BIG_ELVES = {"data": {
    "name": "Big Elves", "code": "TST", "type": "Theme Deck",
    "mainBoard": [card("Llanowar Elves", "FDN", "227", 4), card("Elvish Mystic", "CMM", "648", 4),
                  card("Forest", "FDN", "280", 52)],
}}

TEXT = """# Trial Deck

- **Format:** Casual 60-card, 1v1
- **Status:** idea
- **Trial:** precon BigElves_TST

## Decklist

```
Deck
4 Llanowar Elves
```
"""


def parsed(text=TEXT, kind="casual"):
    return decks.parse_deck(text.encode("utf-8"), "trial-deck", kind)


class TrialLineTests(unittest.TestCase):

    def test_parse_and_format(self):
        self.assertEqual(decks.parse_trial("precon BigElves_TST"), "BigElves_TST")
        self.assertEqual(decks.parse_trial("  precon   BigElves_TST "), "BigElves_TST")
        for value in (None, "", "precon", "BigElves_TST", "precon ../escape", "precon a b", "product X"):
            with self.subTest(value=value):
                self.assertIsNone(decks.parse_trial(value))
        self.assertEqual(decks.format_trial("BigElves_TST"), "precon BigElves_TST")
        with self.assertRaises(ValueError):
            decks.format_trial("../escape")

    def test_a_trial_is_an_idea_deck_with_the_line(self):
        self.assertEqual(decks.trial_of(parsed()), "BigElves_TST")
        self.assertEqual(decks.trial_of(parsed(TEXT.replace("- **Status:** idea\n", ""))), "BigElves_TST")
        self.assertIsNone(decks.trial_of(parsed(TEXT.replace("Status:** idea", "Status:** building"))))
        self.assertIsNone(decks.trial_of(parsed(TEXT.replace("precon BigElves_TST", "precon ../x"))))
        self.assertIsNone(decks.trial_of(parsed(TEXT.replace("- **Trial:** precon BigElves_TST\n", ""))))

    def test_set_trial_adds_replaces_and_removes_only_its_line(self):
        deck = parsed()
        decks.set_trial(deck, "BigElves_TST")
        self.assertEqual(decks.render_deck_file(deck), TEXT)            # a no-op keeps it verbatim
        decks.set_trial(deck, "Other_TST")
        self.assertIn("- **Trial:** precon Other_TST\n", decks.render_deck_file(deck))
        decks.set_trial(deck, None)
        self.assertEqual(decks.render_deck_file(deck), TEXT.replace("- **Trial:** precon BigElves_TST\n", ""))
        decks.set_trial(deck, "BigElves_TST")
        self.assertIn("- **Status:** idea\n- **Trial:** precon BigElves_TST\n", decks.render_deck_file(deck))

    def test_a_status_other_than_idea_ends_the_trial(self):
        deck = parsed()
        decks.set_status(deck, "idea")
        self.assertEqual(decks.render_deck_file(deck), TEXT)
        decks.set_status(deck, "building")
        self.assertNotIn("**Trial:**", decks.render_deck_file(deck))

    def test_other_saves_keep_the_line(self):
        deck = parsed()
        decks.set_field(deck, "Archetype", "Elves")
        self.assertIn("- **Trial:** precon BigElves_TST", decks.render_deck_file(deck))


class TrialApiTestCase(PreconTestCase):

    def setUp(self):
        super().setUp()
        self.listed("BigElves_TST", BIG_ELVES, kind="Theme Deck")

    def start(self, profile="user2", space="user2", file="BigElves_TST", **data):
        with self.as_(profile):
            return self.call(api.start_trial, profile, space=space, file=file, **data)

    def view(self, profile="user2", space="user2", file="BigElves_TST"):
        with self.as_(profile):
            return api.trial_view(file, space)

    def deck_text(self, deck_id):
        space, kind, slug = deck_id.split("/") if deck_id.count("/") == 2 else ("home", *deck_id.split("/"))
        folder = self.box.magic if space == "home" else self.box.magic / "people" / space
        return (folder / "decks" / kind / f"{slug}.md").read_text(encoding="utf-8")


class TrialViewTests(TrialApiTestCase):

    def test_a_testable_precon_with_no_trial_yet(self):
        view = self.view()
        self.assertEqual(view["deck"]["file"], "BigElves_TST")
        self.assertEqual((view["kind"], view["title"], view["cards"]), ("casual", "Big Elves", 60))
        self.assertEqual((view["trial"], view["owned_deck"], view["may_create"]), (None, None, True))
        self.assertEqual((view["testable"], view["why_not_testable"]), (True, None))

    def test_a_commander_precon_is_testable_and_a_small_list_isnt(self):
        dinos = self.view(file="TestDinos_TST")
        self.assertEqual((dinos["kind"], dinos["title"], dinos["testable"]), ("commander", "Ghalta: Test Dinos", True))
        elves = self.view(file="ElfTheme_TST")
        self.assertEqual((elves["kind"], elves["testable"]), ("casual", False))
        self.assertEqual(elves["why_not_testable"], "Its 8-card list is too small to test against 60-card decks.")

    def test_it_names_a_trial_the_viewer_sees(self):
        made = self.start()
        self.assertEqual(self.view()["trial"], {"id": made["id"], "title": "Big Elves"})
        # Another space's trial of the same precon is never named.
        self.assertIsNone(self.view("user3", "user3")["trial"])

    def test_a_space_the_viewer_cant_see_or_a_bad_file(self):
        for profile, space in (("user2", "user3"), ("matt", "user2"), ("user2", "home")):
            with self.subTest(profile=profile, space=space):
                self.assertApiError(403, self.view, profile, space)
        self.assertApiError(404, self.view, file="Nothing_TST")
        self.assertApiError(400, self.view, file="../escape")
        with self.as_("user1"):
            self.assertFalse(api.trial_view("BigElves_TST", "home")["trial"])


class StartTrialTests(TrialApiTestCase):

    def test_a_trial_deck_in_the_members_own_space(self):
        before = self.rows("user2")
        made = self.start()
        self.assertEqual(made["id"], "user2/casual/big-elves")
        self.assertEqual(self.rows("user2"), before)            # nothing goes into the collection
        self.assertEqual(self.last_write(), ("new deck Big Elves", "User2"))
        text = self.deck_text(made["id"])
        self.assertIn("- **Status:** idea\n", text)
        self.assertIn("- **Trial:** precon BigElves_TST\n", text)
        self.assertIn("A trial of the Big Elves precon (Test Commander, Theme Deck), which this space doesn't own, "
                      "made on 2026-10-10 by User2 to test it in Forge against our decks and popular decks before "
                      "buying it.", text)
        self.assertIn("Add a precon offers to remove it once it's bought. The list is MTGJSON's.", text)
        summary = decks.find_summary(made["id"])
        self.assertEqual((summary["trial"], summary["status"]), ("BigElves_TST", "idea"))
        # The deck page's summary carries it too.
        from decklab.lib.api import deck_page
        with self.as_("user2"):
            self.assertEqual(deck_page.deck_view(made["id"])["summary"]["trial"], "BigElves_TST")

    def test_a_home_member_at_home_and_a_title(self):
        made = self.start("user1", "home", title="Her Trial")
        self.assertEqual(made["id"], "casual/her-trial")
        self.assertIn("- **Played by:** wife", self.deck_text(made["id"]))

    def test_a_second_trial_is_409_with_the_existing_one(self):
        made = self.start()
        before = self.writes_made()
        error = self.assertApiError(409, self.start, title="Another")
        self.assertEqual(error.extra, {"existing": made["id"]})
        self.assertEqual(self.writes_made(), before)
        # Another precon, or another space's trial of this one, is no conflict.
        self.start(file="TestDinos_TST")
        self.start("user3", "user3")

    def test_a_taken_title_is_409_with_the_conflict(self):
        with self.as_("user2"):
            from decklab.lib.api import precon_coverage
            self.call(precon_coverage.start_deck, "user2", space="user2", file="ElfTheme_TST", title="Big Elves")
        error = self.assertApiError(409, self.start)
        self.assertEqual(error.extra["conflict"]["id"], "user2/casual/big-elves")

    def test_refused_as_creating_a_deck_is(self):
        for profile, space in (("user2", "user3"), ("user2", "home"), ("matt", "user2")):
            with self.subTest(profile=profile, space=space):
                before = self.writes_made()
                error = self.assertApiError(403, self.start, profile, space)
                self.assertEqual(error.extra, {})
                self.assertEqual(self.writes_made(), before)

    def test_signed_out_is_refused(self):
        before = self.writes_made()
        from decklab.lib.api.common import ApiError
        with self.as_(None):
            for body in (b'{"file": "BigElves_TST"}', b'{"profile": null, "file": "BigElves_TST"}'):
                with self.subTest(body=body), self.assertRaises(ApiError) as caught:
                    api.start_trial(body)
                self.assertIn(caught.exception.status, (400, 403))
        self.assertEqual(self.writes_made(), before)

    def test_not_testable_or_unmatched_cards_is_400(self):
        before = self.writes_made()
        error = self.assertApiError(400, self.start, file="ElfTheme_TST")
        self.assertIn("too small to test against 60-card decks", str(error))
        error = self.assertApiError(400, self.start, file="Unfinished_TST")
        self.assertTrue(error.extra["problems"])
        self.assertIn("A trial can't be made of Unfinished yet", str(error))
        self.assertEqual(self.writes_made(), before)
        self.assertApiError(404, self.start, file="Nothing_TST")


class KeepTrialTests(TrialApiTestCase):

    def keep(self, deck_id, sha, profile="user2"):
        with self.as_(profile):
            return self.call(api.keep_trial, profile, id=deck_id, expected_sha=sha)

    def test_keep_removes_only_the_trial_line(self):
        made = self.start()
        text = self.deck_text(made["id"])
        answer = self.keep(made["id"], made["sha256"])
        after = self.deck_text(made["id"])
        self.assertEqual(after, text.replace("- **Trial:** precon BigElves_TST\n", ""))
        self.assertEqual(answer, {"ok": True, "id": made["id"], "sha256": decks.text_sha(after)})
        self.assertEqual(self.last_write(), ("keep Big Elves as a deck idea, no longer a trial", "User2"))
        self.assertIsNone(decks.find_summary(made["id"])["trial"])
        # Not a trial any more: 400.
        self.assertApiError(400, self.keep, made["id"], answer["sha256"])

    def test_a_stale_sha_another_space_or_no_edit_right(self):
        made = self.start()
        before = self.writes_made()
        self.assertApiError(409, self.keep, made["id"], "0" * 64)
        self.assertApiError(404, self.keep, made["id"], made["sha256"], "user3")
        self.assertApiError(400, self.keep, made["id"], "short")
        self.assertEqual(self.writes_made(), before)
        home = self.start("matt", "home")            # Played by user: Matt's
        self.assertApiError(403, self.keep, home["id"], home["sha256"], "user1")


class AddAfterTrialTests(TrialApiTestCase):

    def test_add_a_precon_names_its_trials(self):
        trial = self.start("user2", "user2", file="TestDinos_TST", title="Dinos Trial")
        with self.as_("user2"):
            planned = add.plan_add("user2", "TestDinos_TST", None, None, {"id": "user2", "name": "User2",
                                                                           "role": "member", "space": "user2"},
                                   "User2")
        self.assertEqual(planned["trials"], [{"id": trial["id"], "title": "Dinos Trial"}])
        with self.as_("user2"):
            answer = self.add("TestDinos_TST", "user2")
        self.assertEqual(answer["trials"], [{"id": trial["id"], "title": "Dinos Trial"}])
        # The bought deck is built and no trial; the trial stays until it's retired.
        self.assertIsNone(decks.find_summary(answer["deck"]["id"])["trial"])
        with self.as_("user3"):
            self.assertEqual(self.add("TestDinos_TST", "user3")["trials"], [])

    def test_a_trial_with_the_default_title_leaves_add_a_precon_a_free_one(self):
        trial = self.start("user2", "user2", file="TestDinos_TST")
        self.assertEqual(trial["title"], "Ghalta: Test Dinos")          # Add a precon's own suggestion
        with self.as_("user2"):
            preview = add.precon_preview("TestDinos_TST", "user2")
            self.assertEqual((preview["title"], preview["exists"]), ("Ghalta: Test Dinos 2", None))
            answer = self.add("TestDinos_TST", "user2")
            self.assertEqual(answer["trials"], [{"id": trial["id"], "title": "Ghalta: Test Dinos"}])
            self.assertEqual(answer["deck"]["id"], "user2/commander/ghalta-test-dinos-2")
            again = add.precon_preview("TestDinos_TST", "user2")      # while the trial stays, a free one again
        self.assertEqual((again["title"], again["exists"]), ("Ghalta: Test Dinos 3", None))

    def test_coverage_says_whether_it_can_be_tried(self):
        from decklab.lib.api import precon_coverage
        with self.as_("user2"):
            big = precon_coverage.coverage_deck("BigElves_TST", "user2")
            small = precon_coverage.coverage_deck("ElfTheme_TST", "user2")
        self.assertEqual((big["testable"], big["why_not_testable"]), (True, None))
        self.assertEqual((small["testable"], small["why_not_testable"]),
                         (False, "Its 8-card list is too small to test against 60-card decks."))

    def test_the_command_line_says_to_retire_it(self):
        from decklab.db.__main__ import main
        trial = self.start("user2", "user2", file="TestDinos_TST", title="Dinos Trial")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["collection", "add-precon", "TestDinos_TST", "--space", "user2", "-m", "bought it"])
        self.assertEqual(code, 0, err.getvalue())
        lines = out.getvalue().rstrip().splitlines()
        self.assertEqual(lines[-1], f"The trial deck {trial['id']} of this precon is still in the library: "
                                    "retire it on its deck page.")
        self.assertTrue(lines[-2].startswith("Added "))


if __name__ == "__main__":
    unittest.main()
