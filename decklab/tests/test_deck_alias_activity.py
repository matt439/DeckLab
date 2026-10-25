"""Pure audit projections for renamed deck ids and their retained old links."""
import copy
import json
import unittest

from decklab.lib.api import activity
from decklab.tests.test_activity import ALL, BY_ID, HOME, USER2S, _change, _deck, _row


OLD, NEW, LATEST = "casual/gruul", "casual/green-ramp", "casual/forest-ramp"
R_OLD, R_NEW = "user2/casual/elves", "user2/casual/green-elves"


def alias_row(alias_id=OLD, deck_id=NEW, *, op="INSERT", previous=None, **extra):
    after = {"alias_id": alias_id, "deck_id": deck_id, **extra}
    if op == "DELETE":
        return _row("deck_alias", op, {"alias_id": alias_id}, before=after)
    return _row("deck_alias", op, {"alias_id": alias_id}, before=previous, after=after)


def rename_row(before_id=OLD, after_id=NEW, before_title="Gruul", after_title="Green Ramp", **fields):
    return _row("deck", "UPDATE", {"id": after_id},
                before=_deck(deck_id=before_id, title=before_title, **fields),
                after=_deck(deck_id=after_id, title=after_title, **fields))


class AliasActivityTests(unittest.TestCase):
    def show(self, rows, scope=ALL, *, actor="matt", **kwargs):
        return activity.visible_change(_change(rows, actor=actor, source="web", message="Rename deck",
                                               reason="Make this name clearer"), scope, BY_ID, **kwargs)

    def test_alias_rows_follow_exact_allowed_spaces(self):
        for alias_id, target, owner, outsider in ((OLD, NEW, HOME, USER2S),
                                                (R_OLD, R_NEW, USER2S, HOME)):
            row = alias_row(alias_id, target)
            with self.subTest(alias=alias_id):
                shown = self.show([row], owner)
                self.assertEqual(shown["rows"][0]["after"], {"alias_id": alias_id, "deck_id": target})
                self.assertEqual(shown["kinds"], ["decks"])
                self.assertIsNone(self.show([row], outsider))
                self.assertIsNotNone(self.show([row], ALL))
        self.assertIsNone(self.show([alias_row(R_OLD, R_NEW)], ALL, spaces=["home"], me="matt"))
        self.assertIsNone(self.show([alias_row()], ALL, spaces=[]))

    def test_alias_before_and_after_send_only_the_two_id_fields(self):
        before = {"alias_id": OLD, "deck_id": NEW, "secret": "private-before", "owner": "matt"}
        row = alias_row(OLD, LATEST, op="UPDATE", previous=before, secret="private-after",
                        text="private deck text", notes="private notes", revision=7)
        original = copy.deepcopy(row)
        shown = self.show([row], HOME)["rows"][0]
        self.assertEqual(shown, {"table": "deck_alias", "op": "UPDATE",
                                "summary": f"Updated old deck link {OLD} to {LATEST}",
                                "before": {"alias_id": OLD, "deck_id": NEW},
                                "after": {"alias_id": OLD, "deck_id": LATEST}})
        self.assertNotIn("private", json.dumps(shown))
        self.assertEqual(row, original)

    def test_malformed_or_missing_alias_endpoints_are_omitted_even_for_all(self):
        malformed = (None, 7, [], {}, "", "casual/", "casual/../secret", "casual/a/b", "casual/a\\b",
                     "casual/a\nsecret", "casual/a:secret", "user2/casual/../secret", "not-a-deck")
        for bad in malformed:
            for field in ("alias_id", "deck_id"):
                with self.subTest(field=field, value=bad):
                    row = alias_row()
                    row["after"][field] = bad
                    self.assertIsNone(self.show([row]))
        for record in (None, [], "bad", {}, {"alias_id": OLD}, {"deck_id": NEW}):
            with self.subTest(record=record):
                row = _row("deck_alias", "INSERT", {"alias_id": OLD}, after=record)
                self.assertIsNone(self.show([row]))

    def test_aliases_never_bridge_spaces_kinds_or_product_pairing_ids(self):
        invalid = ((OLD, R_NEW), (R_OLD, NEW), (OLD, "commander/green-ramp"),
                   ("product/precon", NEW), (OLD, "product/precon"), ("pairing/cats+elves", NEW),
                   (OLD, "pairing/cats+elves"))
        for alias_id, target in invalid:
            with self.subTest(alias=alias_id, target=target):
                for scope in (ALL, HOME, USER2S):
                    self.assertIsNone(self.show([alias_row(alias_id, target)], scope))

    def test_update_cannot_hide_a_cross_space_or_kind_before_image(self):
        for before in ({"alias_id": R_OLD, "deck_id": R_NEW},
                       {"alias_id": "commander/old", "deck_id": "commander/new"},
                       {"alias_id": OLD, "deck_id": "pairing/cats+elves"}):
            with self.subTest(before=before):
                self.assertIsNone(self.show([alias_row(op="UPDATE", previous=before)], ALL))
                self.assertIsNone(self.show([alias_row(op="UPDATE", previous=before)], HOME))

    def test_insert_delete_and_retarget_rows_describe_their_own_exact_audit_evidence(self):
        for operation, verb, before, after in (("INSERT", "Kept", None, {"alias_id": OLD, "deck_id": NEW}),
                                               ("DELETE", "Removed", {"alias_id": OLD, "deck_id": NEW}, None)):
            with self.subTest(operation=operation):
                row = self.show([alias_row(op=operation)], HOME)["rows"][0]
                self.assertEqual(row["summary"], f"{verb} old deck link {OLD} to {NEW}")
                self.assertEqual((row["before"], row["after"]), (before, after))

    def test_title_change_is_a_rename_with_current_deck_link(self):
        rows = [rename_row(), alias_row()]
        original = copy.deepcopy(rows)
        shown = self.show(rows, HOME)
        self.assertEqual((shown["headline"], shown["link"], shown["kinds"]),
                         ("Matt renamed Gruul to Green Ramp", {"deck": NEW}, ["decks"]))
        self.assertNotIn("saved", shown["headline"])
        self.assertNotIn("deleted", shown["headline"])
        self.assertEqual(rows, original)

    def test_same_title_slug_change_is_a_rename_rather_than_saved_text(self):
        shown = self.show([rename_row(after_title="Gruul"), alias_row()], HOME)
        self.assertEqual(shown["headline"], f"Matt renamed the id of Gruul from {OLD} to {NEW}")
        self.assertEqual(shown["link"], {"deck": NEW})
        self.assertEqual(shown["kinds"], ["decks"])

    def test_repeated_rename_lists_retargeted_old_alias_without_a_duplicate_deck_headline(self):
        rows = [rename_row(NEW, LATEST, "Green Ramp", "Forest Ramp"),
                alias_row(OLD, LATEST, op="UPDATE", previous={"alias_id": OLD, "deck_id": NEW}),
                alias_row(NEW, LATEST)]
        shown = self.show(rows, HOME)
        self.assertEqual(shown["headline"], "Matt renamed Green Ramp to Forest Ramp")
        self.assertEqual(shown["link"], {"deck": LATEST})
        aliases = [row for row in shown["rows"] if row["table"] == "deck_alias"]
        self.assertEqual(len(aliases), 2)
        self.assertEqual(aliases[0]["before"], {"alias_id": OLD, "deck_id": NEW})
        self.assertEqual(aliases[0]["after"], {"alias_id": OLD, "deck_id": LATEST})
        self.assertEqual(aliases[1]["after"], {"alias_id": NEW, "deck_id": LATEST})

    def test_kit_version_privacy_still_hides_rename_message_and_reason_from_other_home_viewer(self):
        deck = rename_row()
        deck["after"]["kit_version"] = 1
        change = _change([deck, alias_row()], actor="user1", source="web",
                         message="Rename while moving private-pink sleeves", reason="private-pink box")
        for scope, me, expected in ((ALL, "matt", False), (HOME, None, True), (ALL, None, True)):
            with self.subTest(scope=scope, me=me):
                shown = activity.visible_change(change, scope, BY_ID, me=me)
                self.assertEqual(shown["message"], change["message"] if expected else None)
                self.assertEqual(shown["reason"], change["reason"] if expected else None)
                self.assertEqual(shown["headline"], "User1 renamed Gruul to Green Ramp")
                self.assertNotIn("kit_version", json.dumps(shown))
                if not expected:
                    self.assertNotIn("private-pink", json.dumps(shown))
        self.assertIsNone(activity.visible_change(change, USER2S, BY_ID))

    def test_store_kit_flag_applies_even_when_only_alias_rows_are_available(self):
        change = _change([alias_row()], actor="user1", source="web",
                         message="Private kit move", reason="Private reason") | {"kit": True}
        shown = activity.visible_change(change, ALL, BY_ID, me="matt")
        self.assertEqual((shown["message"], shown["reason"]), (None, None))
        own = activity.visible_change(change, HOME, BY_ID)
        self.assertEqual((own["message"], own["reason"]), (change["message"], change["reason"]))
