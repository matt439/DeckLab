"""Deck rename read compatibility over pinned snapshots and immutable fixture history.

No database, network, live deck or saved simulation is used. The mock backend models
the database's merged lineage while preserving each revision's original deck id.
"""
import copy
import dataclasses
import json
from datetime import timedelta
from unittest import mock

from decklab.lib import access, accessories, api, config, decks, inventory, purchases
from decklab.lib.api import accessories as accessory_api
from decklab.lib.api import (assembly_standins, commits, deck_aliases, guard, history, opponents, retirement,
                             saving, shopping, wishlists)
from decklab.lib.api import play_records as play
from decklab.lib.inventory import ops_decks
from decklab.lib.inventory.model import Deck
from decklab.tests.test_api import ApiTestCase, GRUUL
from decklab.tests.test_collection_edit import ROLES
from decklab.tests.test_deck_history import SHA_A, WHEN, revision
from decklab.tests.test_play_records import PlayFixture, encoded


OLD = "casual/gruul-test"
NEW = "casual/renamed-gruul"
OLDER = "casual/earlier-gruul"
OTHER = "commander/elf-commander"
OTHER_ALIAS = "commander/old-elves"
SOURCE = "magic/decks/casual/gruul-test.md"


class AliasHistory:
    """A snapshot-only backend, with already-merged fixture revision lineage."""

    def __init__(self, inner, snapshot, revisions):
        self.inner, self.snapshot, self.revisions = inner, snapshot, revisions

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def load(self):
        return self.snapshot

    def _revisions(self, deck_id):
        return self.revisions.get(inventory.resolve_deck_id(deck_id, self.snapshot), [])

    def deck_revisions(self, deck_id):
        return [dataclasses.replace(item, text=None) for item in reversed(self._revisions(deck_id))]

    def deck_revisions_with_text(self, deck_id, limit):
        return list(reversed(self._revisions(deck_id)))[:limit]

    def deck_revision(self, deck_id, number):
        return next((item for item in self._revisions(deck_id) if item.revision == int(number)), None)

    def last_revision(self, deck_id):
        found = self.deck_revisions(deck_id)
        return found[0] if found else None


def renamed_snapshot(before, text=None, aliases=None):
    stored = before.deck(OLD)
    after = before.without_deck(OLD).with_deck(Deck("home", "casual", NEW.split("/", 1)[1], text or stored.text))
    return dataclasses.replace(after, deck_aliases=aliases or {OLD: NEW}, aliases_ready=True)


class AliasReadFixture(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.text = GRUUL.replace("# Gruul Test", "# Renamed Gruul")
        self.snapshot = renamed_snapshot(inventory.current(), self.text)
        self.revisions = [revision(OLD, 1, GRUUL, op="A", commit=SHA_A),
                          revision(NEW, 2, self.text, at=WHEN + timedelta(days=1), message="Rename Gruul")]
        self.backend = AliasHistory(self.box.inventory, self.snapshot, {NEW: self.revisions})
        self.enterContext(inventory.use(self.backend))

    def assertMetadata(self, value, requested, *, summary=False, aliases=None):
        self.assertEqual(value["summary"]["id"] if summary else value["id"], NEW)
        self.assertEqual(value["aliases"], aliases or [OLD])
        if requested == NEW:
            self.assertNotIn("requested_id", value)
        else:
            self.assertEqual(value["requested_id"], requested)


class DeckAliasReadTests(AliasReadFixture):
    def test_snapshot_exact_key_and_public_read_lookup_have_different_jobs(self):
        with inventory.pinned(self.snapshot):
            self.assertIsNone(inventory.current().deck(OLD))
            self.assertEqual(inventory.current().deck(NEW).text, self.text)
            self.assertEqual(decks.find_summary(OLD)["id"], NEW)
            self.assertEqual(decks.load_deck(OLD), decks.load_deck(NEW))
            self.assertEqual(decks.load_deck(OLD, "owned"), decks.load_deck(NEW, "owned"))
            self.assertIsNone(decks.find_summary("casual/not-an-alias"))

    def test_deck_and_editor_reads_return_current_identity_without_duplicate_library_rows(self):
        with inventory.pinned(self.snapshot):
            for requested in (OLD, NEW):
                with self.subTest(requested=requested):
                    page = api.deck_view(requested, omit=("matchups",))
                    self.assertMetadata(page, requested, summary=True)
                    edit = api.edit_view(requested)
                    self.assertMetadata(edit, requested)
                    self.assertEqual(edit["sha256"], self.snapshot.deck(NEW).sha256)
                    self.assertEqual(edit["source"], NEW)
            ids = [item["id"] for item in api.decks_index()["decks"]]
        self.assertNotIn(OLD, ids)
        self.assertEqual(ids.count(NEW), 1)

    def test_history_and_number_or_commit_revision_links_keep_original_evidence(self):
        before = copy.deepcopy(self.revisions)
        with inventory.pinned(self.snapshot):
            for requested in (OLD, NEW):
                with self.subTest(requested=requested):
                    listed = history.deck_history(requested)
                    self.assertMetadata(listed, requested)
                    self.assertEqual([row["revision"] for row in listed["revisions"]], [2, 1])
                    self.assertFalse(listed["retired"])
                    for number in (1, "1", SHA_A):
                        selected = history.deck_revision(requested, number)
                        self.assertMetadata(selected, requested)
                        self.assertEqual(selected["revision"], 1)
                        self.assertEqual(selected["title"], "Gruul Test")
                        self.assertEqual(selected["current"]["id"], NEW)
                        self.assertEqual(selected["current"]["title"], "Renamed Gruul")
        self.assertEqual(self.revisions, before)
        self.assertEqual(self.revisions[0].deck_id, OLD)
        self.assertEqual(self.revisions[0].text, GRUUL)

    def test_repeated_renames_report_all_old_ids_once_in_stable_order(self):
        snapshot = dataclasses.replace(self.snapshot, deck_aliases={OLD: NEW, OLDER: NEW})
        aliases = sorted([OLD, OLDER])
        with inventory.pinned(snapshot):
            for requested in (OLDER, OLD, NEW):
                with self.subTest(requested=requested):
                    self.assertMetadata(api.edit_view(requested), requested, aliases=aliases)
                    self.assertMetadata(history.deck_history(requested), requested, aliases=aliases)
            untouched = api.edit_view(OTHER)
        self.assertNotIn("aliases", untouched)
        self.assertNotIn("requested_id", untouched)

    def test_old_alias_keeps_readable_history_after_current_deck_is_retired(self):
        snapshot = self.snapshot.without_deck(NEW)
        self.backend.snapshot = snapshot
        self.revisions.append(revision(NEW, 3, None, op="D", at=WHEN + timedelta(days=2)))
        with inventory.pinned(snapshot), mock.patch.object(inventory, "apply") as apply:
            for requested in (OLD, NEW):
                with self.subTest(requested=requested):
                    listed = history.deck_history(requested)
                    self.assertMetadata(listed, requested)
                    self.assertTrue(listed["retired"])
                    self.assertFalse(listed["may_save"])
                    self.assertTrue(listed["may_restore"])
                    self.assertIsNone(listed["sha256"])
                    self.assertEqual(listed["retired_revision"], 3)
                    old = history.deck_revision(requested, SHA_A)
                    self.assertMetadata(old, requested)
                    self.assertTrue(old["retired"])
                    self.assertIsNone(old["current"])
                    self.assertEqual(old["title"], "Gruul Test")
            apply.assert_not_called()
        self.assertIsNone(snapshot.deck(OLD))
        self.assertIsNone(snapshot.deck(NEW))

    def test_hidden_alias_reads_never_disclose_current_id_or_lineage(self):
        with inventory.pinned(self.snapshot), mock.patch.object(guard, "sees_deck", return_value=False):
            for function, args in ((api.deck_view, (OLD,)), (api.edit_view, (OLD,)),
                                   (history.deck_history, (OLD,)), (history.deck_revision, (OLD, 1))):
                with self.subTest(function=function.__name__):
                    error = self.assertApiError(404, function, *args)
                    self.assertNotIn(NEW, error.message)
                    self.assertNotIn("canonical_id", error.extra)
                    self.assertNotIn("aliases", error.extra)

    def test_stale_write_is_rejected_even_when_rename_left_the_text_hash_unchanged(self):
        same = renamed_snapshot(self.box.inventory.load())
        self.assertEqual(same.deck(NEW).sha256, self.box.inventory.load().deck(OLD).sha256)
        with inventory.pinned(same), mock.patch.object(inventory, "apply") as apply:
            error = self.assertApiError(409, commits._stored, OLD, same.deck(NEW).sha256)
            self.assertEqual(error.extra["canonical_id"], NEW)
            self.assertEqual(error.extra["requested_id"], OLD)
            self.assertEqual(error.extra["conflict"], {"reason": "renamed", "canonical_id": NEW})
            apply.assert_not_called()

    def test_visibility_and_edit_rights_precede_alias_conflict_metadata(self):
        with inventory.pinned(self.snapshot):
            with mock.patch.object(guard, "sees_deck", return_value=False):
                error = self.assertApiError(404, commits._stored, OLD)
                self.assertEqual(error.extra, {})
            denied = api.ApiError(403, "You cannot change this deck")
            with mock.patch.object(guard, "require", side_effect=denied):
                error = self.assertApiError(403, commits._stored, OLD)
                self.assertEqual(error.extra, {})
                self.assertNotIn(NEW, error.message)

    def test_cli_alias_reads_resolve_but_mutable_lookup_requires_current_exact_id(self):
        from decklab.db import inv_decks
        with inventory.pinned(self.snapshot), mock.patch.object(inv_decks, "_say") as say:
            self.assertEqual(inv_decks._deck(OLD, resolve=True), self.snapshot.deck(NEW))
            say.assert_not_called()
            self.assertIsNone(inv_decks._deck(OLD))
            self.assertIn(f"{OLD} was renamed to {NEW}", say.call_args.args[0])
            self.assertEqual(inv_decks._deck(NEW), self.snapshot.deck(NEW))

    def test_kit_alias_read_uses_current_holder_without_counting_it_as_another_deck(self):
        text = self.text.replace("- **Status:** building", "- **Status:** built\n- **Built version:** target\n"
                                 "- **Sleeves:** fixture-sleeves\n- **Deck box:** fixture-box")
        snapshot = self.snapshot.with_deck(self.snapshot.deck(NEW).replace(text=text)).with_accessories([
            {"id": "fixture-sleeves", "kind": "sleeves", "owner": "shared", "name": "Fixture sleeves",
             "quantity": "100"},
            {"id": "fixture-box", "kind": "deck_box", "owner": "shared", "name": "Fixture box",
             "quantity": "1", "capacity": "100"}])
        with inventory.pinned(snapshot):
            old, current = accessories.kit(OLD), accessories.kit(NEW)
            need = accessories.sleeve_need(decks.load_deck(NEW))
        self.assertEqual(old, current)
        self.assertEqual((old["holder"], old["need"], old["short"], old["spare"]), (NEW, need, 0, 100 - need))
        self.assertEqual(old["shared_with"], [])
        self.assertEqual(old["warnings"], [])

    def test_library_reports_current_revision_and_aliases_only_for_visible_current_rows(self):
        snapshot = dataclasses.replace(self.snapshot, decks_revision="rename-fixture-2",
                                       deck_aliases={OLDER: NEW, OLD: NEW})
        with inventory.pinned(snapshot):
            value = api.decks_index()
            by_id = {item["id"]: item for item in value["decks"]}
            # The viewer's own (E10-S30): over the decks it may see, not the inventory's decks_revision.
            self.assertRegex(value["decks_revision"], "^[0-9a-f]{64}$")
            self.assertEqual(by_id[NEW]["aliases"], sorted([OLD, OLDER]))
            self.assertNotIn("requested_id", by_id[NEW])
            self.assertNotIn(OLD, by_id)
            self.assertNotIn(OLDER, by_id)
            self.assertNotIn("aliases", by_id[OTHER])

            def visible(item, profile=False):
                return (item.get("id") if isinstance(item, dict) else item) != NEW

            with mock.patch.object(guard, "sees_deck", side_effect=visible):
                hidden = api.decks_index()
            self.assertNotEqual(hidden["decks_revision"], value["decks_revision"])
        # A hidden deck isn't listed at all (E10-S30), so neither are its old ids.
        self.assertNotIn(NEW, [item["id"] for item in hidden["decks"]])
        self.assertNotIn(OLD, json.dumps(hidden))
        self.assertNotIn(OLDER, json.dumps(hidden))


class DeckAliasRaceTests(AliasReadFixture):
    def setUp(self):
        super().setUp()
        self.before = self.box.inventory.load()
        self.profile = ROLES["profiles"][0]
        self.refusal = ops_decks.DeckRefused("The old deck is gone", code=404, ids=[OLD])

    def test_failed_save_reloads_fresh_alias_without_replacing_the_requests_old_pin(self):
        callback = saving._deck_refused(OLD, "Gruul Test", self.profile)
        with inventory.pinned(self.before), mock.patch.object(self.backend, "load", return_value=self.snapshot) as load, \
                mock.patch.object(inventory, "apply") as apply:
            self.assertEqual(inventory.resolve_deck_id(OLD), OLD)
            result = callback(self.refusal)
            self.assertEqual(result.status, 409)
            self.assertEqual(result.extra["canonical_id"], NEW)
            self.assertEqual(result.extra["conflict"]["reason"], "renamed")
            self.assertIs(inventory.current(), self.before)
            self.assertEqual(inventory.resolve_deck_id(OLD), OLD)
            load.assert_called_once_with()
            apply.assert_not_called()

    def test_failed_save_checks_fresh_visibility_and_rights_before_returning_current_id(self):
        callback = saving._deck_refused(OLD, "Gruul Test", self.profile)
        for hidden, status in ((True, 404), (False, 403)):
            with self.subTest(hidden=hidden), inventory.pinned(self.before), \
                    mock.patch.object(self.backend, "load", return_value=self.snapshot), \
                    mock.patch.object(guard, "sees_deck", return_value=not hidden), \
                    mock.patch.object(guard, "require", side_effect=api.ApiError(403, "Cannot edit this deck")), \
                    mock.patch.object(inventory, "apply") as apply:
                result = callback(self.refusal)
                self.assertEqual(result.status, status)
                self.assertEqual(result.extra, {})
                self.assertNotIn(NEW, result.message)
                self.assertIs(inventory.current(), self.before)
                apply.assert_not_called()

    def test_failed_extra_read_falls_back_to_the_original_save_conflict(self):
        callback = saving._deck_refused(OLD, "Gruul Test", self.profile)
        original = api.ApiError(409, "Original deletion conflict", conflict={"reason": "deleted"})
        with inventory.pinned(self.before), \
                mock.patch.object(self.backend, "load", side_effect=inventory.Unavailable("Fixture offline")), \
                mock.patch.object(saving, "_conflict", return_value=original) as conflict, \
                mock.patch.object(inventory, "apply") as apply:
            self.assertIsNone(deck_aliases.after_refusal(OLD, self.profile))
            self.assertIs(callback(self.refusal), original)
            conflict.assert_called_once_with(OLD, "Gruul Test", deleted=True, viewer=self.profile)
            self.assertIs(inventory.current(), self.before)
            apply.assert_not_called()

    def test_retirement_and_kit_failed_writes_report_fresh_rename(self):
        operation = inventory.Op("deck.delete", {"deck_id": OLD})
        for target in ("retirement", "kit"):
            with self.subTest(target=target), inventory.pinned(self.before), \
                    mock.patch.object(self.backend, "load", return_value=self.snapshot), \
                    mock.patch.object(inventory, "apply", side_effect=self.refusal) as apply:
                if target == "retirement":
                    result = self.assertApiError(409, retirement._apply, operation, self.profile, "Retire fixture")
                else:
                    result = self.assertApiError(409, accessory_api._apply, operation, self.profile, "Clear fixture",
                                                 mock.Mock(side_effect=AssertionError("ordinary kit conflict")))
                self.assertEqual(result.extra["canonical_id"], NEW)
                self.assertEqual(result.extra["conflict"]["reason"], "renamed")
                self.assertIs(inventory.current(), self.before)
                self.assertEqual(apply.call_count, 1)

    def test_kit_failed_write_checks_current_private_kit_owner_before_disclosing_rename(self):
        operation = inventory.Op("kit.set", {})
        denied = api.ApiError(403, "These sleeves belong to another person")
        with inventory.pinned(self.before), mock.patch.object(self.backend, "load", return_value=self.snapshot), \
                mock.patch.object(guard, "require_kit_choice", side_effect=denied) as kit_choice, \
                mock.patch.object(inventory, "apply", side_effect=self.refusal):
            result = self.assertApiError(403, accessory_api._apply, operation, self.profile, "Clear fixture",
                                        mock.Mock(side_effect=AssertionError("ordinary kit conflict")))
            self.assertEqual(result.extra, {})
            self.assertNotIn(NEW, result.message)
            self.assertEqual(kit_choice.call_args.args[1]["id"], NEW)
            self.assertIs(inventory.current(), self.before)


class DeckAliasSourceTests(AliasReadFixture):
    def test_old_purchase_source_resolves_without_rewriting_or_reading_retired_history(self):
        row = {"name": "Sol Ring", "quantity": 2, "source": SOURCE, "for": "Gruul Test"}
        original = copy.deepcopy(row)
        (self.box.root / SOURCE).unlink()
        with inventory.pinned(self.snapshot), mock.patch.object(inventory, "last_revision") as latest:
            self.assertTrue(purchases.source_exists(self.box.root, SOURCE, inv=self.snapshot))
            shopping._link_decks([row], decks.list_decks())
        self.assertEqual(row["deck"], {"id": NEW, "title": "Renamed Gruul"})
        self.assertEqual({key: row[key] for key in original}, original)
        self.assertFalse((self.box.root / SOURCE).exists())
        latest.assert_not_called()

    def test_wishlist_enrichment_follows_old_source_and_leaves_saved_entry_intact(self):
        entry = {"name": "Sol Ring", "set": "", "number": "", "notes": "For my old plan", "source": SOURCE}
        original = copy.deepcopy(entry)
        with inventory.pinned(self.snapshot):
            value = wishlists._view("matt", [entry], [])
        self.assertEqual(value["entries"][0]["source"], SOURCE)
        self.assertEqual(value["entries"][0]["source_deck"], {"id": NEW, "title": "Renamed Gruul"})
        self.assertEqual(entry, original)

    def test_hidden_alias_source_does_not_get_an_enriched_link(self):
        row = {"name": "Sol Ring", "source": SOURCE, "for": "Gruul Test"}
        with inventory.pinned(self.snapshot), mock.patch.object(guard, "sees_deck", return_value=False):
            self.assertIsNone(wishlists._source_deck(SOURCE, self.snapshot))
            shopping._link_decks([row], decks.list_decks())
        self.assertIsNone(row["deck"])
        self.assertEqual(row["source"], SOURCE)


class DeckAliasStaleWriteTests(AliasReadFixture):
    def requests(self):
        sha = self.snapshot.deck(NEW).sha256
        return [("stand-ins", assembly_standins.save_standins,
                 {"profile": "matt", "id": OLD, "version": "target", "sha256": sha, "rows": []}),
                ("opponents", opponents.save_opponents,
                 {"profile": "matt", "id": OLD, "sha256": sha, "opponents": []}),
                ("retirement", retirement.retire_deck,
                 {"profile": "matt", "id": OLD, "sha256": sha, "revision": 2, "reason": "Retire this idea"}),
                ("kit clear", accessory_api.assign_accessory,
                 {"profile": "matt", "holder": OLD, "field": "sleeves", "id": None, "holder_sha256": sha})]

    def test_old_metadata_and_kit_requests_cannot_succeed_as_no_ops(self):
        self.snapshot = renamed_snapshot(self.box.inventory.load())
        self.backend.snapshot = self.snapshot
        with inventory.pinned(self.snapshot), mock.patch.object(inventory, "apply") as apply:
            for label, function, payload in self.requests():
                with self.subTest(request=label):
                    error = self.assertApiError(409, function, encoded(payload))
                    self.assertEqual(error.extra["canonical_id"], NEW)
                    self.assertEqual(error.extra["conflict"]["reason"], "renamed")
            apply.assert_not_called()

    def test_malformed_ids_are_bad_requests_before_alias_resolution_or_any_write(self):
        with inventory.pinned(self.snapshot), mock.patch.object(inventory, "apply") as apply:
            for malformed in (None, [], {}, True, "", "casual/../secret"):
                with self.subTest(id=malformed):
                    self.assertApiError(400, deck_aliases.reject_alias, malformed)
                for label, function, payload in self.requests():
                    payload["holder" if "holder" in payload else "id"] = malformed
                    with self.subTest(request=label, id=malformed):
                        self.assertApiError(400, function, encoded(payload))
                self.assertApiError(400, retirement.restore_deck,
                                    encoded({"profile": "matt", "id": malformed, "retired_revision": 3}))
            apply.assert_not_called()

    def test_hidden_stale_requests_have_no_alias_conflict_or_current_id(self):
        with inventory.pinned(self.snapshot), mock.patch.object(guard, "sees_deck", return_value=False), \
                mock.patch.object(inventory, "apply") as apply:
            for label, function, payload in self.requests():
                with self.subTest(request=label):
                    error = self.assertApiError(404, function, encoded(payload))
                    self.assertEqual(error.extra, {})
                    self.assertNotIn(NEW, error.message)
            apply.assert_not_called()

    def test_old_move_from_holder_cannot_be_cleared_by_assigning_to_another_deck(self):
        payload = {"profile": "matt", "holder": OTHER, "field": "deck_box", "id": "fixture-box",
                   "holder_sha256": self.snapshot.deck(OTHER).sha256, "move_from": OLD}
        with inventory.pinned(self.snapshot), mock.patch.object(inventory, "apply") as apply:
            error = self.assertApiError(409, accessory_api.assign_accessory, encoded(payload))
        self.assertEqual(error.extra["canonical_id"], NEW)
        apply.assert_not_called()

    def test_private_kit_owner_is_checked_before_current_identity_is_disclosed(self):
        private = self.snapshot.with_deck(self.snapshot.deck(NEW).replace(
            text=self.text.replace("- **Played by:** either", "- **Played by:** wife")))
        self.backend.snapshot = private
        (self.box.root / "config.json").write_text(json.dumps(ROLES), encoding="utf-8")
        payload = {"profile": "matt", "holder": OLD, "field": "sleeves", "id": None,
                   "holder_sha256": private.deck(NEW).sha256}
        with inventory.pinned(private), access.using({"profile": "matt", "email": "", "remote": True}), \
                mock.patch.object(inventory, "apply") as apply:
            error = self.assertApiError(403, accessory_api.assign_accessory, encoded(payload))
        self.assertEqual(error.extra, {"reason": "kit_ownership"})
        self.assertNotIn(NEW, error.message)
        apply.assert_not_called()

    def test_restoration_uses_current_id_and_exact_last_text_preserving_old_alias(self):
        snapshot = self.snapshot.without_deck(NEW)
        self.backend.snapshot = snapshot
        self.revisions.append(revision(NEW, 3, None, op="D", at=WHEN + timedelta(days=2)))
        applied = []

        def fixture_apply(operation, profile, message, reason=None, expected_revision=None):
            self.assertEqual(expected_revision, snapshot.revision)
            after, summary = operation.run(snapshot)
            applied.append(after)
            return after, summary

        with inventory.pinned(snapshot), mock.patch.object(inventory, "apply") as write:
            old = self.assertApiError(409, retirement.restore_deck,
                                     encoded({"profile": "matt", "id": OLD, "retired_revision": 3}))
            self.assertEqual(old.extra["canonical_id"], NEW)
            with mock.patch.object(retirement, "_apply", side_effect=fixture_apply):
                value = retirement.restore_deck(encoded({"profile": "matt", "id": NEW, "retired_revision": 3}))
            write.assert_not_called()
        self.assertEqual(value["id"], NEW)
        self.assertTrue(value["restored"])
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0].deck(NEW).text, self.text)
        self.assertIsNone(applied[0].deck(OLD))
        self.assertEqual(dict(applied[0].deck_aliases), {OLD: NEW})


class DeckAliasOpponentTests(AliasReadFixture):
    def relations_snapshot(self):
        declared = self.text.replace("- **Status:** building", "- **Status:** building\n"
                                    f"- **Usual opponents:** {OTHER_ALIAS}, {OTHER}, {OLD}")
        snapshot = self.snapshot.with_deck(Deck("home", "casual", NEW.split("/", 1)[1], declared))
        return dataclasses.replace(snapshot, deck_aliases={OLD: NEW, OTHER_ALIAS: OTHER})

    def test_old_headers_collapse_duplicates_remove_self_and_keep_reciprocal_links(self):
        snapshot = self.relations_snapshot()
        original = snapshot.deck(NEW).text
        with inventory.pinned(snapshot):
            own = opponents.opponents_view(OLD)
            self.assertEqual(own["id"], NEW)
            self.assertEqual(own["opponents"], [OTHER])
            self.assertEqual(opponents.usual_opponents(NEW), [{"id": OTHER, "title": "Elf Commander"}])
            self.assertEqual(opponents.usual_opponents(OLD), opponents.usual_opponents(NEW))
            other = opponents.opponents_view(OTHER_ALIAS)
            self.assertEqual(other["inherited"], [{"id": NEW, "title": "Renamed Gruul"}])
            self.assertNotIn(OLD, {item["id"] for item in other["choices"]})
        self.assertEqual(snapshot.deck(NEW).text, original)

    def test_chosen_aliases_are_canonical_and_cannot_circumvent_self_check(self):
        with inventory.pinned(self.relations_snapshot()):
            own = decks.find_summary(NEW)
            catalog = opponents._catalog()
            self.assertEqual(opponents._chosen([OTHER_ALIAS, OTHER], own, catalog), [OTHER])
            self.assertApiError(400, opponents._chosen, [OLD], own, catalog, contains="own usual opponent")

    def test_hidden_opponents_stay_hidden_after_old_headers_resolve(self):
        def visible(item, profile=False):
            return (item.get("id") if isinstance(item, dict) else item) != OTHER

        with inventory.pinned(self.relations_snapshot()), mock.patch.object(guard, "sees_deck", side_effect=visible):
            value = opponents.opponents_view(OLD)
        self.assertEqual(value["opponents"], [])
        self.assertNotIn(OTHER_ALIAS, json.dumps(value))
        self.assertNotIn(OTHER, json.dumps(value))


class DeckAliasPlayTests(PlayFixture, ApiTestCase):
    def setUp(self):
        super().setUp()
        self.write_decks()

    def test_canonical_and_old_filters_find_unchanged_historical_games_and_plans(self):
        game = self.save(self.game())
        plan = self.save(self.plan(), play.save_sideboard)
        before_games = copy.deepcopy(self.box.state.play_list("games"))
        before_plans = copy.deepcopy(self.box.state.play_list("sideboards"))
        before_audit = copy.deepcopy(self.box.state.changes())
        snapshot = renamed_snapshot(inventory.current())
        with inventory.pinned(snapshot):
            for requested in (NEW, OLD):
                with self.subTest(requested=requested):
                    value = play.play_overview(requested)
                    self.assertEqual(value["games"], [{"record": game["record"], "sha256": game["sha256"],
                                                       "can": {"sides": [True, True], "result": True}}])
                    self.assertEqual(value["sideboards"][0]["record"], plan["record"])
                    self.assertEqual(value["sideboards"][0]["sha256"], plan["sha256"])
                    self.assertEqual(value["games"][0]["record"]["sides"][0]["id"], OLD)
                    self.assertIn(NEW, {item["id"] for item in value["lists"]})
                    self.assertNotIn(OLD, {item["id"] for item in value["lists"]})
            self.assertEqual(play.play_overview("casual/absent")["games"], [])
        self.assertEqual(self.box.state.play_list("games"), before_games)
        self.assertEqual(self.box.state.play_list("sideboards"), before_plans)
        self.assertEqual(self.box.state.changes(), before_audit)

    def test_renamed_home_game_is_not_exposed_to_a_person_space_viewer(self):
        self.save(self.game())
        (self.box.root / "config.json").write_text(json.dumps(ROLES), encoding="utf-8")
        self.enterContext(mock.patch.object(config, "REPO", self.box.root))
        with inventory.pinned(renamed_snapshot(inventory.current())), \
                access.using({"profile": "user2", "email": "", "remote": True}):
            for requested in (OLD, NEW):
                self.assertEqual(play.play_overview(requested)["games"], [])
