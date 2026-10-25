"""Physical stand-in choices: isolated metadata saves, ownership checks and private projection."""
import json
from collections import Counter
from unittest import mock

from decklab.lib import access, api, config, decks, inventory, pool
from decklab.lib.api import assembly, assembly_completion, assembly_standins as endpoint, history
from decklab.lib.decks import standins
from decklab.tests import test_collection_edit as collection_tests
from decklab.tests import test_editor as editor_tests
from decklab.tests import test_deck_history as history_tests
from decklab.tests import test_server as server_tests
from decklab.tests.test_api import _write

OWN = "casual/table-test"
ROW = {"for": "Black Lotus", "using": "Aerie Mystics", "qty": 1}


class StandInFixtures(editor_tests.EditorTestCase):
    def setUp(self):
        super().setUp()
        _write(self.box.root / "config.json", json.dumps(collection_tests.ROLES))
        _write(self.box.magic / "collection.csv", collection_tests.HEADER
               + "Llanowar Elves,fdn,227,nonfoil,5,NM,en,\n"
               + "Elvish Mystic,cmm,648,nonfoil,1,NM,en,\n"
               + "Black Lotus,lea,232,nonfoil,1,NM,en,\n"
               + "Aerie Mystics,con,1,nonfoil,2,NM,en,\n")
        patcher = mock.patch.object(config, "REPO", self.box.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def choose(self, rows=None, version="target", deck_id=OWN, profile="matt", sha=None, **context):
        return endpoint.save_standins(self.body(profile, id=deck_id, version=version,
                                                sha256=sha or self.sha(deck_id), rows=[ROW] if rows is None else rows,
                                                **context))

    def parsed(self, deck_id=OWN):
        return decks.parse_deck(self.path(deck_id).read_bytes(), deck_id.rsplit("/", 1)[-1], "casual")


class StandInApiTests(StandInFixtures):
    def test_save_is_one_metadata_only_operation_and_same_choices_are_a_no_op(self):
        before = self.deck_files()
        parsed = self.parsed()
        with mock.patch.object(inventory, "apply", wraps=inventory.apply) as apply:
            answer = self.choose()
        operation, actor, message = apply.call_args.args
        self.assertEqual((apply.call_count, operation.kind, actor.id, message),
                         (1, "deck.save", "matt", "choose the stand-ins for Table Test"))
        self.assertTrue(answer["ok"] and answer["saved"])
        self.assertEqual(answer["sha256"], self.sha(OWN))
        self.assertEqual(answer["standins"]["rows"][0]["card"]["name"], "Black Lotus")
        after = self.deck_files()
        self.assertEqual([key for key in before if before[key] != after[key]], ["decks/casual/table-test.md"])
        held = self.parsed()
        self.assertEqual((held.target, held.owned, held.rows, held.total, held.changed_on),
                         (parsed.target, parsed.owned, parsed.rows, parsed.total, parsed.changed_on))
        with mock.patch.object(inventory, "apply") as apply:
            self.assertFalse(self.choose()["saved"])
        apply.assert_not_called()
        self.assertEqual(self.choose([])["standins"]["rows"], [])
        self.assertEqual(self.text(OWN), editor_tests.TABLE_DECK)

    def test_config_save_keeps_the_installed_recipe_until_explicit_repacking(self):
        deck = self.parsed()
        decks.apply_edit(deck, fields={"status": "built", "built_version": "target"})
        standins.install_stand_ins(deck, "target", [{"for": "Black Lotus", "using": None, "qty": 1}])
        _write(self.path(OWN), decks.render_deck_file(deck))
        installed = standins.installed_for(self.parsed())
        self.choose()
        self.assertEqual(standins.choices_for(self.parsed(), "target"), [ROW])
        self.assertEqual(standins.installed_for(self.parsed()), installed)

    def test_generic_spare_basic_choices_need_no_physical_inventory_read(self):
        row = dict(ROW, using=None)
        with mock.patch.object(endpoint.pool, "load_pool", side_effect=AssertionError("no named marker")):
            answer = self.choose([row])
        self.assertEqual({key: value for key, value in answer["standins"]["rows"][0].items() if key != "card"}, row)

    def test_validation_rejects_bad_rows_and_ambiguous_markers_before_writing(self):
        invalid = [None, "Opt", [{}], [dict(ROW, qty=True)], [dict(ROW, qty=0)],
                   [dict(ROW, qty=2)], [dict(ROW, using="Forest")], [dict(ROW, using="Llanowar Elves")],
                   [dict(ROW, using="Black Lotus")], [dict(ROW, using="aerie mystics")],
                   [dict(ROW, using="Nonsense Card")], [dict(ROW, **{"for": "black lotus"})],
                   [ROW, {"for": "Llanowar Elves", "using": "Aerie Mystics", "qty": 1}]]
        for rows in invalid:
            with self.subTest(rows=rows), mock.patch.object(inventory, "apply") as apply:
                # None is deliberately sent directly: choose(None) is the convenient valid default.
                body = self.body(id=OWN, version="target", sha256=self.sha(OWN), rows=rows)
                self.assertApiError(400, endpoint.save_standins, body)
                apply.assert_not_called()

    def test_quantities_across_repeated_rows_cannot_exceed_the_logical_card(self):
        self.assertApiError(400, lambda: self.choose([ROW, dict(ROW, using=None)]))

    def test_only_physically_owned_unreserved_marker_copies_count(self):
        needed = {"for": "Llanowar Elves", "using": "Aerie Mystics", "qty": 2}
        fake = pool.Pool(Counter({"Aerie Mystics": 4}), {"Aerie Mystics": [("on the way", 2)]},
                         [pool.InUse("casual/other", "Other", "built", Counter({"Aerie Mystics": 1}))])
        with mock.patch.object(endpoint.pool, "load_pool", return_value=fake):
            self.assertApiError(409, lambda: self.choose([needed]), contains="only 1 physically owned")
        # The deck may reuse its own actual holder, which has already been physically assembled.
        fake.in_use[0].id = OWN
        with mock.patch.object(endpoint.pool, "load_pool", return_value=fake):
            self.assertTrue(self.choose([needed])["saved"])

    def test_permission_precedes_metadata_card_index_and_pool_validation(self):
        _write(self.path(OWN), self.text(OWN).replace("Played by:** wife", "Played by:** user"))
        with access.using({"profile": "user1", "email": "", "remote": True}), \
                mock.patch.object(standins, "validate_rows", side_effect=AssertionError("permission first")), \
                mock.patch.object(endpoint, "_require_cards", side_effect=AssertionError("permission first")), \
                mock.patch.object(endpoint.pool, "load_pool", side_effect=AssertionError("permission first")):
            body = self.body("user1", id=OWN, version="bad", sha256="bad", rows="bad")
            self.assertApiError(403, endpoint.save_standins, body)

    def test_invalid_hash_version_missing_list_and_products_are_refused(self):
        for sha in (True, 123, "wrong", "g" * 64):
            with self.subTest(sha=sha):
                self.assertApiError(400, lambda: self.choose(sha=sha))
        self.assertApiError(400, lambda: self.choose(version="other"))
        self.assertApiError(404, lambda: self.choose(version="owned"))
        body = self.body(id="product/fdc-test-precon", version="target", sha256="0" * 64, rows=[])
        self.assertApiError(400, endpoint.save_standins, body)

    def test_missing_card_index_and_unavailable_database_never_write(self):
        with self.box.no_index(), mock.patch.object(inventory, "apply") as apply:
            self.assertApiError(503, self.choose)
            apply.assert_not_called()
        with mock.patch.object(endpoint.pool, "load_pool", side_effect=inventory.Unavailable("down")):
            self.assertApiError(503, self.choose)

    def test_stale_text_and_a_race_at_apply_preserve_current_text(self):
        old = self.sha(OWN)
        self.choose()
        self.assertApiError(409, lambda: self.choose([], sha=old))
        before = self.text(OWN)
        real = inventory.apply

        def raced(*args, **kwargs):
            _write(self.path(OWN), before + "\nConcurrent fixture note.\n")
            return real(*args, **kwargs)

        with mock.patch.object(inventory, "apply", side_effect=raced):
            self.assertApiError(409, lambda: self.choose([]))
        self.assertEqual(self.text(OWN), before + "\nConcurrent fixture note.\n")

    def test_deck_page_projection_keeps_logical_sections_and_is_private(self):
        before = api.deck_view(OWN, omit=("matchups",))
        self.choose()
        answer = api.deck_view(OWN, omit=("matchups",))
        self.assertEqual(answer["sections"], before["sections"])
        self.assertEqual(answer["standins"]["rows"][0]["card"]["name"], "Black Lotus")
        with mock.patch.object(api.deck_page.guard, "sees_inventory", return_value=False), \
                mock.patch.object(endpoint, "project", side_effect=AssertionError("inventory hidden")):
            answer = api.deck_view(OWN, omit=("matchups",))
        self.assertNotIn("standins", answer)

    def test_projection_picture_failure_preserves_mapping_and_product_has_none(self):
        self.choose()
        with mock.patch.object(endpoint, "_line_json", side_effect=RuntimeError("no image")):
            answer = endpoint.project(self.parsed(), "target")
        self.assertEqual(answer["rows"], [dict(ROW, card=None)])
        self.assertIsNone(api.deck_view("product/fdc-test-precon", omit=("matchups",))["standins"])

    def test_history_and_editor_header_projections_do_not_relay_marker_metadata(self):
        self.choose()
        after = self.parsed()
        before = decks.parse_deck(editor_tests.TABLE_DECK.encode("utf-8"), "table-test", "casual")
        old_revision = history_tests.revision(OWN, 1, before.text)
        revision = history_tests.revision(OWN, 2, after.text)
        with mock.patch.object(history.guard, "sees_inventory", return_value=False):
            change = history.revision_change(revision, after, old_revision, before, cards_ready=False)
            edited = api.edit_view(OWN)
        self.assertEqual(change["kind"], "none")
        self.assertNotIn("Stand-ins", json.dumps(change))
        self.assertNotIn("Aerie Mystics", json.dumps(change))
        self.assertNotIn("Stand-ins", json.dumps(edited))

    def test_person_space_checks_its_own_physical_pool(self):
        deck_id = "user2/casual/table-test"
        path = self.box.magic / "people" / "user2" / "decks" / "casual" / "table-test.md"
        _write(path, editor_tests.TABLE_DECK.replace("- **Played by:** wife\n", ""))
        held = inventory.current().deck(deck_id)
        fake = pool.Pool(Counter({"Aerie Mystics": 1}), {}, [], space="user2")
        with access.using({"profile": "user2", "email": "", "remote": True}), \
                mock.patch.object(endpoint.pool, "load_pool", return_value=fake) as load:
            answer = endpoint.save_standins(self.body("user2", id=deck_id, version="target",
                                                      sha256=held.sha256, rows=[ROW]))
        self.assertTrue(answer["saved"])
        load.assert_called_once_with("user2")


class StandInPlanContextTests(StandInFixtures):
    """A selected deck may return a marker; saving a choice still changes no physical holder."""

    def setUp(self):
        super().setUp()
        self.donor, self.receiver = "casual/donor", "casual/receiver"
        self.path("casual/broken").unlink()       # this fixture's global warning deliberately blocks builds
        text = ("# Donor\n\n- **Format:** Casual 60-card, 1v1\n- **Played by:** user\n"
                "- **Status:** built\n- **Built version:** owned\n\n## Decklist\n\n```\nDeck\n60 Forest\n```\n"
                "\n## Substitutes\n\n### Owned-only version\n\n```\nDeck\n1 Aerie Mystics\n59 Forest\n```\n")
        _write(self.path(self.donor), text)
        _write(self.path(self.receiver), "# Receiver\n\n- **Format:** Casual 60-card, 1v1\n"
               "- **Played by:** wife\n- **Status:** building\n\n## Decklist\n\n```\nDeck\n"
               "1 Black Lotus\n59 Forest\n```\n")
        path = self.box.magic / "collection.csv"
        _write(path, path.read_text(encoding="utf-8").replace("Black Lotus,lea,232,nonfoil,1,NM,en,\n", ""))
        self.selected = [{"id": self.donor, "version": "target"}, {"id": self.receiver, "version": "target"}]

    def context(self, selected=None):
        selected = self.selected if selected is None else selected
        plan = assembly.assembly_preview(self.body(decks=selected))
        return plan, {"decks": selected, "fingerprint": plan["completion"]["fingerprint"]}

    def receiver_text(self):
        return self.text(self.receiver)

    def holders(self):
        return {holder.id: holder.cards["Aerie Mystics"] for holder in pool.load_pool().in_use
                if holder.cards["Aerie Mystics"]}

    def test_selected_returned_marker_can_be_saved_then_explicitly_built(self):
        plan, context = self.context()
        receiver = next(item for item in plan["decks"] if item["id"] == self.receiver)
        self.assertIn({"name": "Aerie Mystics", "free": 1}, receiver["standins"]["candidates"])
        self.assertIn({"for": "Black Lotus", "qty": 1, "suggestion": "Aerie Mystics"},
                      receiver["standins"]["needs"])
        holders = self.holders()
        self.assertEqual(holders[self.donor], 1)
        self.assertApiError(409, lambda: self.choose(deck_id=self.receiver))
        answer = self.choose(deck_id=self.receiver, **context)
        self.assertTrue(answer["saved"])
        self.assertEqual(self.holders(), holders)
        self.assertIsNone(standins.installed_for(self.parsed(self.receiver)))
        fresh, context = self.context()
        self.assertTrue(fresh["completion"]["can_mark_built"], fresh["completion"])
        answer = assembly_completion.mark_built(self.body(**context, confirmed=True))
        self.assertTrue(answer["saved"])
        after = self.holders()
        self.assertNotIn(self.donor, after)
        self.assertEqual(after[self.receiver], 1)
        self.assertEqual(standins.installed_for(self.parsed(self.receiver)), {"version": "target", "cards": [ROW]})

    def test_other_selected_marker_allocations_are_subtracted_from_candidates(self):
        contender = "casual/contender"
        text = self.receiver_text().replace("# Receiver", "# Contender").replace("Black Lotus", "Elvish Mystic")
        deck = decks.parse_deck(text.encode("utf-8"), "contender", "casual")
        standins.set_choices(deck, "target", [{"for": "Elvish Mystic", "using": "Aerie Mystics", "qty": 1}])
        _write(self.path(contender), decks.render_deck_file(deck))
        self.selected.insert(1, {"id": contender, "version": "target"})
        plan, context = self.context()
        target = next(item for item in plan["decks"] if item["id"] == self.receiver)
        other = next(item for item in plan["decks"] if item["id"] == contender)
        self.assertIn({"name": "Aerie Mystics", "free": 1}, target["standins"]["candidates"])
        self.assertEqual(other["standins"]["rows"], [{"for": "Elvish Mystic", "using": "Aerie Mystics", "qty": 1}])
        before = self.receiver_text()
        self.assertApiError(409, lambda: self.choose(deck_id=self.receiver, **context),
                            contains="only 0 physically owned copies free in this packing plan")
        self.assertEqual(self.receiver_text(), before)

    def test_replacing_own_choice_does_not_subtract_its_existing_marker_twice(self):
        deck = self.parsed(self.receiver)
        standins.set_choices(deck, "target", [ROW])
        _write(self.path(self.receiver), decks.render_deck_file(deck))
        _, context = self.context()
        self.assertFalse(self.choose(deck_id=self.receiver, **context)["saved"])

    def test_context_fields_must_appear_together(self):
        _, context = self.context()
        for incomplete in ({"decks": context["decks"]}, {"fingerprint": context["fingerprint"]}):
            with self.subTest(context=incomplete), mock.patch.object(inventory, "apply") as apply:
                self.assertApiError(400, lambda: self.choose(deck_id=self.receiver, **incomplete))
                apply.assert_not_called()

    def test_target_must_match_a_selected_deck_and_version_exactly_once(self):
        _, context = self.context(self.selected[:1])
        self.assertApiError(400, lambda: self.choose(deck_id=self.receiver, **context))
        duplicate = [*self.selected, self.selected[1]]
        self.assertApiError(400, lambda: self.choose(deck_id=self.receiver, decks=duplicate, fingerprint="0" * 64))
        own = self.path(self.receiver)
        _write(own, own.read_text(encoding="utf-8") + "\n## Substitutes\n\n### Owned-only version\n\n"
               "```\nDeck\n1 Black Lotus\n59 Forest\n```\n")
        _, context = self.context()
        self.assertApiError(400, lambda: self.choose(deck_id=self.receiver, version="owned", **context))

    def test_stale_fingerprint_and_changed_inventory_do_not_save_choices(self):
        _, context = self.context()
        before = self.receiver_text()
        self.assertApiError(409, lambda: self.choose(deck_id=self.receiver, **dict(context, fingerprint="0" * 64)))
        path = self.box.magic / "collection.csv"
        _write(path, path.read_text(encoding="utf-8").replace("Aerie Mystics,con,1,nonfoil,2,", "Aerie Mystics,con,1,nonfoil,1,"))
        with mock.patch.object(inventory, "apply") as apply:
            self.assertApiError(409, lambda: self.choose(deck_id=self.receiver, **context))
            apply.assert_not_called()
        self.assertEqual(self.receiver_text(), before)

    def test_context_races_check_inventory_and_deck_revisions_inside_apply(self):
        _, context = self.context()
        before = self.receiver_text()
        real = inventory.apply

        def raced(*args, **kwargs):
            _write(self.path("casual/race"), self.text(self.donor).replace("# Donor", "# Race"))
            return real(*args, **kwargs)

        with mock.patch.object(inventory, "apply", side_effect=raced):
            self.assertApiError(409, lambda: self.choose(deck_id=self.receiver, **context))
        self.assertEqual(self.receiver_text(), before)

    def test_nonhome_and_unauthorized_context_never_construct_a_plan(self):
        deck_id = "user2/casual/table-test"
        path = self.box.magic / "people" / "user2" / "decks" / "casual" / "table-test.md"
        _write(path, editor_tests.TABLE_DECK.replace("- **Played by:** wife\n", ""))
        held = inventory.current().deck(deck_id)
        body = self.body("user2", id=deck_id, version="target", sha256=held.sha256, rows=[ROW],
                         decks=self.selected, fingerprint="0" * 64)
        with access.using({"profile": "user2", "email": "", "remote": True}), \
                mock.patch.object(assembly, "_preview", side_effect=AssertionError("home inventory first")):
            self.assertApiError(400, endpoint.save_standins, body)
        with mock.patch.object(endpoint.guard, "require_sees_inventory", side_effect=api.ApiError(403, "hidden")), \
                mock.patch.object(assembly, "_preview", side_effect=AssertionError("home inventory first")):
            self.assertApiError(403, lambda: self.choose(deck_id=self.receiver, decks=self.selected, fingerprint="0" * 64))

    def test_context_operation_guards_both_revision_components(self):
        snapshot = inventory.current()
        operation = inventory.Op("deck.save", {"deck_id": self.receiver, "text": self.receiver_text(),
                                               "base_sha256": self.sha(self.receiver)})
        guarded = endpoint._ContextSave(operation, (snapshot.revision, snapshot.decks_revision))
        for changed in (snapshot.replace(revision=snapshot.revision + "new"),
                        snapshot.replace(decks_revision=snapshot.decks_revision + "new")):
            with self.subTest(revision=changed.revision), self.assertRaises(inventory.Conflict):
                guarded.run(changed)


class StandInHttpTests(server_tests.ServerTestCase):
    def test_post_route_dispatches_with_existing_write_guards(self):
        body = b'{"profile":"matt","fixture":true}'
        with mock.patch.object(endpoint, "save_standins", return_value={"saved": True}) as save:
            answer = self.get_json("/api/assembly/standins", method="POST", body=body,
                                   headers=dict(server_tests.WRITE, Origin=f"http://127.0.0.1:{self.port}"))
            self.assertEqual(answer, {"saved": True})
            save.assert_called_once_with(body)
            save.reset_mock()
            self.assertError("/api/assembly/standins", 403, method="POST", body=b"{}",
                             headers={"Content-Type": "application/json"})
            self.assertError("/api/assembly/standins?extra=yes", 400, method="POST", body=b"{}",
                             headers=server_tests.WRITE)
            for method in ("GET", "HEAD", "PUT", "DELETE"):
                code, _, _ = self.request(method, "/api/assembly/standins")
                self.assertEqual(code, 405)
            save.assert_not_called()
