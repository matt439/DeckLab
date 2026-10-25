"""E10-S37: public-deck history subjects and actors are masked by both API readers.

Disposable inventory/history fixtures only; the public-deck hook publishes no real data.
"""
import dataclasses
import json
from unittest import mock

from decklab.lib import access, inventory
from decklab.lib.api import guard, history
from decklab.lib.inventory import refresh
from decklab.tests.test_api import GRUUL
from decklab.tests.test_api_permissions import PermissionTestCase
from decklab.tests.test_deck_history import SHA_A, install, revision


TABLE = ("## Owned vs needed\n\n"
         "| Card | Need | Owned | Missing | ~AUD each | ~AUD missing | Notes |\n"
         "|---|---|---|---|---|---|---|\n"
         "| Llanowar Elves | 4 | 0 | 4 | | | |\n\n")
ORDER = "2026-10-05-private-shipment"


def _as(who):
    return access.using({"profile": who, "email": "", "remote": True})


class HistoryPrivacyTests(PermissionTestCase):
    def setUp(self):
        super().setUp()
        self.deck_id = "casual/gruul-test"
        self.path = self.box.magic / "decks/casual/gruul-test.md"
        self.initial = GRUUL.replace("## Substitutes", TABLE + "## Substitutes")
        self.ordered = self.initial.replace("| 4 | 0 | 4 |", "| 4 | 0 | 2 |")
        self.edited = self.ordered.replace("4 Llanowar Elves (FDN) 227", "3 Llanowar Elves (FDN) 227", 1)
        self.received = self.edited.replace("| 4 | 0 | 2 |", "| 4 | 2 | 2 |")
        self.revisions = [
            revision(self.deck_id, 1, self.initial, op="A", actor="claude", commit=SHA_A,
                     message="Private migrated git subject\n\nPrivate body and trailers"),
            revision(self.deck_id, 2, self.ordered, actor="matt", message=f"Record order {ORDER}"),
            revision(self.deck_id, 3, self.edited, actor="user1", message="Private page-save message"),
            revision(self.deck_id, 4, self.received, actor="matt", message=f"receive {ORDER}"),
        ]
        self.path.write_text(self.received, encoding="utf-8")
        self.backend = install(self.box, {self.deck_id: self.revisions})
        public = mock.patch.object(guard, "public_deck_spaces", return_value=frozenset({"home", "user2"}))
        public.start()
        self.addCleanup(public.stop)

    def test_public_history_hides_messages_and_outside_profile_actors_on_the_server(self):
        with _as("user2"):
            value = history.deck_history(self.deck_id)
        rows = value["revisions"]
        self.assertEqual([r["subject"] for r in rows],
                         ["Tables refreshed", "Saved the deck", "Tables refreshed", "Created the deck"])
        self.assertEqual([(r["actor"], r["author"]) for r in rows],
                         [(None, "someone"), (None, "someone"), (None, "someone"), ("claude", "Claude")])
        self.assertEqual(rows[-1]["commit"], SHA_A[:7])
        self.assertEqual(rows[1]["change"]["kind"], "cards")
        self.assertFalse(value["may_save"])
        encoded = json.dumps(value)
        for private in (ORDER, "Private", "matt", "Matt", "user1", "User1"):
            self.assertNotIn(private, encoded)

    def test_selected_revision_metadata_has_the_same_rule_including_git_links(self):
        with _as("user2"):
            listed = {r["revision"]: r for r in history.deck_history(self.deck_id)["revisions"]}
            for number in (1, 2, 3, 4, SHA_A):
                with self.subTest(number=number):
                    value = history.deck_revision(self.deck_id, number)
                    selected = value["history"]
                    self.assertEqual(selected, {k: v for k, v in listed[value["revision"]].items() if k != "change"})
                    self.assertNotIn(ORDER, json.dumps(value))
                    self.assertNotIn("Private", json.dumps(value))

    def test_own_space_and_scripts_keep_the_first_line_and_kit_privacy(self):
        self.revisions.append(revision(self.deck_id, 5, self.received, actor="user1", kit=True,
                                       message="Private sleeves message"))
        for who in ("matt", "user1", None):
            with self.subTest(who=who), access.using(None) if who is None else _as(who):
                rows = history.deck_history(self.deck_id)["revisions"]
                self.assertEqual(rows[0]["subject"], None if who == "matt" else "Private sleeves message")
                self.assertEqual([r["subject"] for r in rows[1:]],
                                 [r.message.split("\n", 1)[0] for r in reversed(self.revisions[:-1])])
                self.assertEqual((rows[1]["actor"], rows[1]["author"]), ("matt", "Matt"))
                self.assertEqual(history.deck_revision(self.deck_id, 1)["history"]["subject"],
                                 "Private migrated git subject")

    def test_admin_outside_a_public_member_space_has_no_message_or_actor_override(self):
        deck_id = "user2/casual/r-elves"
        text = (self.box.magic / "people/user2/decks/casual/r-elves.md").read_text(encoding="utf-8")
        self.backend.revisions[deck_id] = [revision(deck_id, 1, text, op="A", actor="user2",
                                                   message="Private member subject")]
        with _as("matt"):
            listed = history.deck_history(deck_id)["revisions"][0]
            selected = history.deck_revision(deck_id, 1)["history"]
        for row in (listed, selected):
            self.assertEqual((row["subject"], row["actor"], row["author"]), ("Created the deck", None, "someone"))
        with _as("user2"):
            row = history.deck_history(deck_id)["revisions"][0]
        self.assertEqual((row["subject"], row["actor"], row["author"]),
                         ("Private member subject", "user2", "User2"))

    def test_a_public_retired_deck_keeps_the_same_privacy_rule(self):
        self.path.unlink()
        self.revisions.append(revision(self.deck_id, 5, None, op="D", actor="user1",
                                       message=f"Retire after receiving {ORDER}"))
        with _as("user2"):
            value = history.deck_history(self.deck_id)
            selected = history.deck_revision(self.deck_id, 4)
        self.assertTrue(value["retired"])
        self.assertEqual((value["revisions"][0]["subject"], value["revisions"][0]["author"]),
                         ("Retired the deck", "someone"))
        self.assertEqual(selected["history"]["subject"], "Tables refreshed")
        self.assertIsNone(selected["current"])
        self.assertNotIn(ORDER, json.dumps([value, selected]))

    def test_actor_attribution_does_not_make_an_outside_decks_subject_readable(self):
        for actor, expected in (("user2", ("user2", "User2")), ("zed", (None, "someone")),
                                ("system", ("system", "System"))):
            with self.subTest(actor=actor):
                self.revisions[-1] = dataclasses.replace(self.revisions[-1], actor=actor)
                with _as("user2"):
                    row = history.deck_history(self.deck_id)["revisions"][0]
                self.assertEqual((row["actor"], row["author"]), expected)
                self.assertEqual(row["subject"], "Tables refreshed")

    def test_refresh_of_only_generated_substitute_words_still_names_no_order(self):
        newer = self.received.replace("### Owned-only version", refresh.HEADING + "\n\n" + refresh.substitute_note())
        self.revisions.append(revision(self.deck_id, 5, newer, actor="matt", message=f"Another order {ORDER}"))
        with _as("user2"):
            self.assertEqual(history.deck_history(self.deck_id)["revisions"][0]["subject"], "Tables refreshed")
            self.assertEqual(history.deck_revision(self.deck_id, 5)["history"]["subject"], "Tables refreshed")

    def test_unreadable_missing_or_deleted_predecessor_never_exposes_a_message(self):
        for older in (None, "not a deck"):
            with self.subTest(older=older):
                self.revisions[-2] = revision(self.deck_id, 3, older, op="D" if older is None else "M")
                with _as("user2"):
                    self.assertEqual(history.deck_history(self.deck_id)["revisions"][0]["subject"], "Saved the deck")
                    self.assertEqual(history.deck_revision(self.deck_id, 4)["history"]["subject"], "Saved the deck")
        del self.revisions[-2]
        with _as("user2"):
            self.assertEqual(history.deck_history(self.deck_id)["revisions"][0]["subject"], "Saved the deck")
            self.assertEqual(history.deck_revision(self.deck_id, 4)["history"]["subject"], "Saved the deck")

    def test_hidden_decks_still_refuse_before_any_history_read(self):
        with _as("user2"), mock.patch.object(guard, "public_deck_spaces", return_value=frozenset()), \
                mock.patch.object(inventory, "deck_revisions_with_text", side_effect=AssertionError("read history")), \
                mock.patch.object(inventory, "deck_revision", side_effect=AssertionError("read revision")):
            self.assertApiError(404, history.deck_history, self.deck_id)
            self.assertApiError(404, history.deck_revision, self.deck_id, 4)
