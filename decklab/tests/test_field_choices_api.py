"""Home's field-choice preview and save (E3-S23) over a memory store and a fixture deck source.

No PostgreSQL, configured inventory, server, Forge or card data is used: the memory store
reads only the supplied FixtureSource. Run through scripts/test_fixtures.py.
"""
import json
from unittest import mock

from decklab.lib import access, feature_routes, state
from decklab.lib.api import field_choices
from decklab.lib.state import field_policy_source as source, pg_field_policy
from decklab.lib.state.memory import MemoryStore
from decklab.tests.test_api_permissions import PermissionTestCase
from decklab.tests.test_field_policy_store import TEXT, FixtureSource, capture

ID = "casual/fixture"


class FieldChoicesApiTests(PermissionTestCase):
    def setUp(self):
        super().setUp()
        self.source = FixtureSource(capture(ID))
        self.box.state = MemoryStore(mode=None, field_source=self.source)
        self.addCleanup(state.use(self.box.state))

    def preview(self, profile="matt", *, deck_id=ID, version="target", mode="include", **other):
        return field_choices.preview(self.body(profile, id=deck_id, version=version, mode=mode, **other))

    def save(self, reviewed, profile="matt", *, mode=None, **other):
        body = {"format": reviewed["format"], "revision": reviewed["expect"]["revision"],
                "proof": reviewed["expect"]["proof"], "mode": mode or reviewed["proposed"]["mode"], **other}
        return field_choices.save(self.body(profile, **body))

    def policy(self):
        return self.box.state.field_policy("Constructed")

    def test_preview_writes_nothing_and_save_is_one_audited_change_the_next_preview_reads(self):
        reviewed = self.preview()
        self.assertEqual(reviewed["format"], "Constructed")
        self.assertEqual(reviewed["deck"], {"id": ID, "version": "target"})
        self.assertEqual(reviewed["current"], {"mode": "legacy"})
        self.assertEqual(reviewed["proposed"], {"mode": "include", "version": "target"})
        self.assertTrue(reviewed["changed"])
        self.assertTrue(reviewed["ready"])
        self.assertIsNone(reviewed["message"])
        self.assertFalse(reviewed["reason_required"])
        self.assertEqual(reviewed["expect"]["revision"], "0")
        self.assertEqual(reviewed["expect"]["proof"]["receipt"]["deck_id"], ID)
        json.dumps(reviewed, allow_nan=False)
        self.assertEqual(self.policy()["revision"], 0)
        self.assertEqual(self.box.state.changes(), [])
        saved = self.save(reviewed)
        self.assertEqual(saved, {"changed": True, "format": "Constructed", "revision": "1"})
        change, = self.box.state.changes()
        self.assertEqual(change["actor"], "matt")
        self.assertEqual(change["message"], "Include casual/fixture's Planned list in the Constructed field")
        self.assertEqual(self.policy()["rules"], [{"epoch": reviewed["expect"]["proof"]["epoch"],
                                                  "mode": "include", "version": "target"}])
        again = self.preview()
        self.assertEqual(again["current"], {"mode": "include", "version": "target"})
        self.assertFalse(again["changed"])
        self.assertEqual(again["expect"]["revision"], "1")
        self.assertEqual(self.save(again), {"changed": False, "format": "Constructed", "revision": "1"})
        self.assertEqual(len(self.box.state.changes()), 1)

    def test_play_now_include_and_use_rules_keep_their_reviewed_versions(self):
        owned = self.preview(version="owned")
        self.assertEqual(owned["proposed"], {"mode": "include", "version": "owned"})
        self.save(owned)
        rules = self.preview(mode="rules")
        self.assertEqual(rules["current"], {"mode": "include", "version": "owned"})
        self.assertEqual(rules["proposed"], {"mode": "rules"})
        self.assertEqual(self.save(rules)["revision"], "2")
        self.assertEqual(self.box.state.changes()[-1]["message"],
                         "Let the field rules choose casual/fixture's list in the Constructed field")

    def test_exclude_needs_a_private_reason_kept_out_of_message_and_policy(self):
        reviewed = self.preview(mode="exclude")
        self.assertTrue(reviewed["reason_required"])
        self.assertApiError(400, lambda: self.save(reviewed))
        self.assertApiError(400, lambda: self.save(reviewed, reason="   "))
        self.assertEqual(self.box.state.changes(), [])
        self.save(reviewed, reason="PRIVATE fixture reason")
        change, = self.box.state.changes()
        self.assertEqual(change["reason"], "PRIVATE fixture reason")
        self.assertEqual(change["message"], "Leave casual/fixture out of the Constructed field")
        self.assertNotIn("PRIVATE", json.dumps(self.policy()))

    def test_stale_revision_and_changed_list_conflict_without_writing(self):
        first, second = self.preview(), self.preview(mode="exclude")
        self.save(first)
        self.assertApiError(409, lambda: self.save(second, reason="Fixture"))
        reviewed = self.preview(mode="exclude")
        self.source.value = capture(ID, revision=2, text=TEXT + "\nChanged fixture prose.\n")
        self.assertApiError(409, lambda: self.save(reviewed, reason="Fixture"))
        self.assertEqual(len(self.box.state.changes()), 1)
        self.assertEqual(self.policy()["revision"], 1)

    def test_members_and_requests_naming_nobody_are_refused_before_any_store_read(self):
        reviewed = self.preview()
        refused = mock.patch.multiple(self.box.state, field_policy=mock.DEFAULT, field_policy_review=mock.DEFAULT,
                                      field_policy_apply=mock.DEFAULT)
        with refused as calls:
            for name, call in calls.items():
                call.side_effect = AssertionError(f"store read {name}")
            for who in ("user1", "user2", "local"):
                self.assertEqual(self.status(who, lambda p: self.preview(p)), 403)
                self.assertEqual(self.status(who, lambda p: self.save(reviewed, p)), 403)
            with access.using(None), access.viewing(None), access.answering(False):
                self.assertApiError(403, lambda: field_choices.preview(json.dumps(
                    {"id": ID, "version": "target", "mode": "include"}).encode()))
        for who in ("matt", "script"):         # the script alias names Matt in its body
            self.assertEqual(self.status(who, lambda p: self.preview(p)), 200)
        self.assertEqual(self.box.state.changes(), [])

    def test_an_outside_admin_is_refused_with_words_naming_nobody(self):
        from decklab.lib import permissions
        outside = {"id": "user2", "name": "User2", "role": "admin", "space": "user2"}
        self.assertEqual(permissions.reason(outside, "field.edit"), permissions.FIELD_EDIT_ADMINS)
        self.assertIsNone(permissions.reason({"id": "matt", "role": "admin", "space": "home"}, "field.edit"))
        self.assertEqual(permissions.reason(None, "field.edit"), "Choose who you are first.")
        self.assertIsNone(permissions.reason(None, "field.edit", script=True))
        self.assertNotIn("home", permissions.FIELD_EDIT_ADMINS)

    def test_hidden_member_lists_products_and_bad_inputs_never_reach_the_store(self):
        with mock.patch.object(self.box.state, "field_policy_review",
                               side_effect=AssertionError("store read")):
            with access.viewing("matt"):        # a member's deck is hidden from Matt: a missing deck's 404
                self.assertApiError(404, lambda: self.preview(deck_id="user2/casual/r-elves"))
            for deck_id in ("product/fixture", "pairing/a+b", "", 7):
                self.assertApiError(400, lambda: self.preview(deck_id=deck_id))
            self.assertApiError(400, lambda: self.preview(version="other"))
            self.assertApiError(400, lambda: self.preview(mode="remove"))
            self.assertApiError(400, lambda: self.preview(extra=True))
            self.assertApiError(413, lambda: field_choices.preview(b" " * (field_choices.MAX_BODY + 1)))

    def test_save_refuses_malformed_revisions_formats_and_proofs(self):
        reviewed = self.preview()
        for revision in ("01", "-1", "1.0", 0, None, str(2 ** 63)):
            with self.subTest(revision=revision):
                self.assertApiError(400, lambda: self.save({**reviewed, "expect": {**reviewed["expect"],
                                                                                 "revision": revision}}))
        self.assertApiError(400, lambda: self.save({**reviewed, "format": "Commander"}))
        self.assertApiError(400, lambda: self.save({**reviewed, "format": "Modern"}))
        proof = reviewed["expect"]["proof"]
        for status, bad in ((400, None), (400, []), (400, {**proof, "receipt": None}),
                            (400, {**proof, "version": "x"}), (404, {**proof, "receipt": {
                                **proof["receipt"], "deck_id": "user2/casual/r-elves"}}),
                            (409, {**proof, "card_sha": "0" * 64})):
            with self.subTest(proof=bad), access.viewing("matt"):
                self.assertApiError(status, lambda: self.save({**reviewed, "expect": {**reviewed["expect"],
                                                                                     "proof": bad}}))
        self.assertEqual(self.box.state.changes(), [])

    def test_missing_policy_table_previews_as_today_and_save_names_the_migrate_command(self):
        missing = pg_field_policy._MissingSchema(pg_field_policy.MIGRATE)
        with mock.patch.object(self.box.state, "field_policy", side_effect=missing), \
                mock.patch.object(self.box.state, "field_policy_apply", side_effect=missing):
            reviewed = self.preview()
            self.assertFalse(reviewed["ready"])
            self.assertEqual(reviewed["message"], field_choices.MIGRATE)
            self.assertEqual(reviewed["current"], {"mode": "legacy"})
            self.assertEqual(reviewed["expect"]["revision"], "0")
            error = self.assertApiError(503, lambda: self.save(reviewed))
        self.assertIn("python -m decklab.db migrate", error.message)
        self.assertEqual(self.box.state.changes(), [])

    def test_unproved_list_and_down_database_answer_503_with_fixed_words(self):
        self.source.value["complete"] = False
        error = self.assertApiError(503, self.preview)
        self.assertEqual(error.message, source.UNAVAILABLE)
        self.source.value = capture(ID)
        reviewed = self.preview()
        self.box.state.down = True
        error = self.assertApiError(503, lambda: self.save(reviewed))
        self.assertNotIn("fixture", error.message.casefold())
        self.assertEqual(self.box.state.changes(), [])

    def test_editable_is_true_only_for_a_named_home_admin_on_a_home_field(self):
        with access.viewing("matt"):
            self.assertTrue(field_choices.editable("home"))
            self.assertFalse(field_choices.editable("user2"))
        for who in ("user1", "user2"):
            with access.using({"profile": who, "email": "", "remote": True}):
                self.assertFalse(field_choices.editable("home"))
        with access.using(None), access.viewing(None):
            self.assertFalse(field_choices.editable("home"))     # a script naming nobody uses no controls

    def test_routes_load_the_adapter_only_for_their_posts(self):
        for route, name in ((["field", "policy", "preview"], "preview"), (["field", "policy"], "save")):
            handler = mock.Mock(command="POST")
            handler._write_body.return_value = b"{}"
            with mock.patch.object(field_choices, name, return_value={"fixture": True}) as call:
                self.assertTrue(feature_routes.dispatch(handler, route, {}))
            handler._allow.assert_called_once_with("POST")
            handler._write_body.assert_called_once_with(field_choices.MAX_BODY)
            call.assert_called_once_with(b"{}")
            handler._send_json.assert_called_once_with(200, {"fixture": True})
