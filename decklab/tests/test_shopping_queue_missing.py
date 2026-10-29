"""Queue missing cards… (E5-S25) over the API sandbox's disposable files inventory.

The review writes nothing; add_many saves the reviewed cards as one watchlist change, dedupes
against copies already queued for the deck, never counts token rows, refuses a stale review
and is offered to home admins only.
"""
import csv
import io
import json
import sys
from types import SimpleNamespace
from unittest import mock

from decklab.lib import access, config, feature_routes, inventory, purchases
from decklab.lib import forge as real_forge      # imported before a sandbox installs its stand-in
from decklab.lib.api import shopping_queue, shopping_queue_missing as sqm
from decklab.lib.api.common import ApiError
from decklab.lib.inventory import files
from decklab.lib.inventory.model import QUEUE_FIELDS
from decklab.tests.test_api import ApiTestCase, _write
from decklab.tests.test_collection_edit import ROLES
from decklab.tests.test_inventory_orders import CLAUDE

DECK_ID = "casual/elf-plan"
PLAN = """# Elf Plan

- **Format:** Casual 60-card, 1v1
- **Played by:** user
- **Status:** building

## Decklist

```
Deck
4 Llanowar Elves (FDN) 227
3 Elvish Mystic (CMM) 648
2 Wrath of God (8ED) 58
1 Rhystic Study (WOT) 25
20 Forest

Sideboard
2 Pick Your Poison (MKM) 170
```
"""
USER2_DECK = PLAN.replace("# Elf Plan", "# Their Elves").replace("- **Played by:** user\n", "")


class QueueMissingTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        box = self.box
        _write(box.root / "config.json", json.dumps(ROLES))
        _write(box.magic / "decks" / "casual" / "elf-plan.md", PLAN)
        (box.magic / "decks" / "casual" / "broken.md").unlink()     # an unreadable deck stops every count
        _write(box.magic / "people" / "user2" / "decks" / "casual" / "their-elves.md", USER2_DECK)
        patcher = mock.patch.object(config, "REPO", box.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.backend = box.inventory
        self.writes = []
        real = self.backend.apply

        def apply(op, actor, message, reason=None, expected_revision=None):
            self.writes.append((op.kind, actor.id, message, expected_revision))
            return real(op, actor, message, reason=reason, expected_revision=expected_revision)
        self.backend.apply = apply
        self.queue([])
        self.enterContext(access.using({"profile": "matt", "email": "", "remote": True}))

    def queue(self, rows):
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=QUEUE_FIELDS, lineterminator="\n")
        writer.writeheader()
        for values in rows:
            writer.writerow({**dict.fromkeys(QUEUE_FIELDS, ""), "quantity": "1", "printing": "any",
                             "finish": "nonfoil", "state": "ready", **values})
        _write(self.box.magic / "watchlist.csv", stream.getvalue())

    def review(self, profile="matt", deck=DECK_ID):
        return sqm.review_missing(json.dumps({"profile": profile, "deck": deck}))

    def save(self, review, profile="matt", state="ready", **changes):
        cards = [{"name": row["name"], "copies": row["copies"], "joins": row["joins"]}
                 for row in review["rows"] if row["copies"]]
        data = {"profile": profile, "action": "add_many", "expect": review["revision"], "deck": DECK_ID,
                "state": state, "cards": cards, **changes}
        return shopping_queue.save_queue_state(json.dumps(data))

    def rows(self):
        return [{key: row.text(key) for key in QUEUE_FIELDS} for row in self.backend.load().watchlist.rows]

    def refused(self, status, call):
        before = files.render(self.backend.load())
        with self.assertRaises(ApiError) as caught:
            call()
        self.assertEqual(caught.exception.status, status, caught.exception.message)
        self.assertEqual(files.render(self.backend.load()), before)
        return caught.exception

    def counts(self, review):
        return {row["name"]: (row["missing"], row["queued"], row["copies"]) for row in review["rows"]}

    def test_review_lists_missing_planned_cards_and_writes_nothing(self):
        before = files.render(self.backend.load())
        review = self.review()
        self.assertTrue(review["ready"], review.get("reason"))
        self.assertEqual(review["deck"], {"id": DECK_ID, "title": "Elf Plan"})
        self.assertEqual(review["revision"], self.backend.load().revision)
        self.assertEqual(review["states"], ["ready", "long_term"])
        counts = self.counts(review)
        self.assertEqual(counts["Wrath of God"], (2, 0, 2))
        self.assertEqual(counts["Rhystic Study"], (1, 0, 1))
        self.assertTrue(all(row["joins"] is None for row in review["rows"]))     # every one a new row
        self.assertEqual(counts["Pick Your Poison"], (2, 0, 2))
        self.assertNotIn("Forest", counts)                   # plain basics are never missing
        self.assertEqual(review["totals"]["copies"], sum(c for _, _, c in counts.values()))
        self.assertEqual(files.render(self.backend.load()), before)
        self.assertEqual(self.writes, [])

    def test_save_adds_every_reviewed_card_as_one_audited_change(self):
        review = self.review()
        result = self.save(review, state="long_term")
        self.assertEqual(len(self.writes), 1)
        kind, actor, message, expected = self.writes[0]
        self.assertEqual((kind, actor, expected), ("watchlist.add_many", "matt", review["revision"]))
        self.assertTrue(message.strip())
        rows = {row["name"]: row for row in self.rows()}
        adding = {row["name"]: row["copies"] for row in review["rows"] if row["copies"]}
        self.assertEqual({name: int(row["quantity"]) for name, row in rows.items()}, adding)
        for row in rows.values():
            self.assertEqual((row["state"], row["printing"], row["finish"], row["set"], row["collector_number"]),
                             ("long_term", "any", "nonfoil", "", ""))
            self.assertEqual((row["for"], row["source"]), ("Elf Plan", "magic/decks/casual/elf-plan.md"))
            self.assertEqual(row["listed_aud"] + row["listed_at"] + row["in_stock"] + row["checked"], "")
        self.assertEqual((result["saved"], result["cards"], result["copies"]),
                         (True, len(adding), sum(adding.values())))
        self.assertEqual(result["revision"], self.backend.load().revision)
        # Everything queued now: a new review has nothing left to add.
        again = self.review()
        self.assertEqual(again["totals"], {"cards": 0, "copies": 0})

    def test_copies_already_queued_for_the_deck_are_deducted_and_identical_rows_raised_in_their_state(self):
        self.queue([{"name": "Wrath of God", "quantity": "1", "for": "Elf Plan", "state": "waiting_for_stock",
                     "source": "magic/decks/casual/elf-plan.md", "notes": "Kept note"},
                    {"name": "Rhystic Study", "quantity": "1", "for": "Elf Plan"},       # by title alone
                    {"name": "Pick Your Poison", "quantity": "2", "for": "Another deck"},
                    # A token printing named like a card never counts as a card queued.
                    {"name": "Llanowar Elves", "set": "ttsr", "collector_number": "12", "printing": "exact",
                     "finish": "", "for": "Elf Plan", "notes": "token card"}])
        review = self.review()
        counts = self.counts(review)
        self.assertEqual(counts["Wrath of God"], (2, 1, 1))
        self.assertEqual(counts["Rhystic Study"], (1, 1, 0))
        self.assertEqual(counts["Pick Your Poison"], (2, 0, 2))       # queued for another deck only
        self.assertEqual(counts["Llanowar Elves"][1:], (0, counts["Llanowar Elves"][0]))
        self.assertGreater(counts["Llanowar Elves"][0], 0)
        joins = {row["name"]: row["joins"] for row in review["rows"]}
        # The review says the Wrath copies join the waiting row, keeping its state, not the one chosen.
        self.assertEqual(joins["Wrath of God"], "waiting_for_stock")
        self.assertIsNone(joins["Rhystic Study"])                     # nothing to add
        self.assertIsNone(joins["Pick Your Poison"])                  # another deck's row is never raised
        self.assertIsNone(joins["Llanowar Elves"])
        # A save that doesn't send back the state it joins saves nothing.
        cards = [{"name": row["name"], "copies": row["copies"], "joins": None}
                 for row in review["rows"] if row["copies"]]
        self.refused(409, lambda: self.save(review, cards=cards))
        self.save(review)
        rows = self.rows()
        wrath = [row for row in rows if row["name"] == "Wrath of God"]
        self.assertEqual(len(wrath), 1)                              # raised, not a duplicate request
        self.assertEqual((wrath[0]["quantity"], wrath[0]["state"], wrath[0]["notes"]),
                         ("2", "waiting_for_stock", "Kept note"))
        self.assertEqual([row["quantity"] for row in rows if row["name"] == "Rhystic Study"], ["1"])
        poison = sorted((row["for"], row["quantity"]) for row in rows if row["name"] == "Pick Your Poison")
        self.assertEqual(poison, [("Another deck", "2"), ("Elf Plan", "2")])
        tokens = [row for row in rows if row["set"] == "ttsr"]
        self.assertEqual(len(tokens), 1)                             # tokens are never queued here

    def test_a_stale_revision_or_a_changed_review_saves_nothing(self):
        review = self.review()
        self.refused(409, lambda: self.save(review, expect="stale"))
        changed = [{"name": "Wrath of God", "copies": 5, "joins": None}]
        self.refused(409, lambda: self.save(review, cards=changed))
        # The queue moves on between the review and the save: the review is asked for again.
        inventory.apply(inventory.Op("watchlist.set", {"add": True, "repo": str(self.box.root), "values": {
            "name": "Wrath of God", "quantity": "1", "state": "ready", "for": "Elf Plan"}}),
            CLAUDE, "Fixture concurrent change")
        error = self.refused(409, lambda: self.save(review))
        self.assertIn("Review", error.message)
        self.assertEqual(self.save(self.review())["saved"], True)

    def test_a_change_inside_the_write_is_a_conflict(self):
        review = self.review()
        real = inventory.apply

        def concurrent(op, actor, message, **kwargs):
            real(inventory.Op("watchlist.set", {"add": True, "repo": str(self.box.root), "values": {
                "name": "Rhystic Study", "quantity": "1", "state": "ready", "for": "Other"}}),
                actor, "Fixture concurrent change")
            return real(op, actor, message, **kwargs)
        with mock.patch.object(inventory, "apply", concurrent), self.assertRaises(ApiError) as caught:
            self.save(review)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual([row["for"] for row in self.rows()], ["Other"])

    def test_only_home_admins_may_review_or_save(self):
        review = self.review()
        for profile in ("user1", "user2"):
            with self.subTest(profile=profile), access.using({"profile": profile, "email": "", "remote": True}), \
                    mock.patch.object(inventory, "current") as load:
                self.refused(403, lambda: self.review(profile))
                self.refused(403, lambda: self.save(review, profile))
                load.assert_not_called()
        self.refused(403, lambda: self.review("user1"))           # naming another profile than the login
        self.assertEqual(self.writes, [])

    def test_only_an_ordinary_home_deck(self):
        self.refused(400, lambda: self.review(deck="product/fdn-beginner-box/elves"))
        self.refused(404, lambda: self.review(deck="user2/casual/their-elves"))     # hidden as a missing deck
        self.refused(404, lambda: self.review(deck="casual/no-such-deck"))
        review = self.review()
        self.refused(400, lambda: self.save(review, deck="product/fdn-beginner-box/elves"))

    def test_invalid_saves_write_nothing(self):
        review = self.review()
        for changes in ({"state": "waiting_for_stock"}, {"state": None}, {"cards": []}, {"cards": "x"},
                        {"cards": [{"name": "Wrath of God"}]}, {"cards": [{"name": "Wrath of God", "copies": 0}]},
                        {"cards": [{"name": "Wrath of God", "copies": True}]},
                        {"cards": [{"name": "Wrath of God", "copies": 1, "joins": 7}]},
                        {"cards": [{"name": "Wrath of God", "copies": 1, "joins": ""}]},
                        {"cards": [{"name": "Wrath of God", "copies": 1}, {"name": "wrath of god", "copies": 1}]},
                        {"deck": 7}, {"extra": 1}):
            with self.subTest(changes=changes):
                self.refused(400, lambda: self.save(review, **changes))

    def test_unavailable_inventory_is_a_503(self):
        review = self.review()
        with mock.patch.object(inventory, "apply", side_effect=inventory.Unavailable("down")):
            self.refused(503, lambda: self.save(review))

    def test_the_review_route_is_a_post_through_the_body_guards(self):
        body = b'{"profile":"matt","fixture":true}'
        handler = SimpleNamespace(command="POST", _allow=mock.Mock(), _no_query=mock.Mock(),
                                  _write_body=mock.Mock(return_value=body), _send_json=mock.Mock())
        with mock.patch.dict(sys.modules, {"decklab.lib.forge": real_forge}),                 mock.patch.object(sqm, "review_missing", return_value={"fixture": True}) as endpoint:
            self.assertTrue(feature_routes.dispatch(handler, ["shopping", "queue", "missing"], {}))
        handler._allow.assert_called_once_with("POST")
        endpoint.assert_called_once_with(body)
        handler._send_json.assert_called_once_with(200, {"fixture": True})

    def test_the_saved_queue_still_reads_cleanly(self):
        self.save(self.review())
        with mock.patch.object(config, "REPO", self.box.root):
            rows = purchases.read_queue()
        self.assertTrue(all(row["source"] == "magic/decks/casual/elf-plan.md" for row in rows))
