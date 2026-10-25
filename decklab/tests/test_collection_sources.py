"""Conservative saved-list holder evidence for Collection printing rows, without live stores."""
import copy
import json
import unittest
from collections import Counter
from unittest import mock

from decklab.lib import access, config, decks, inventory, pool, state
from decklab.lib.api import collection_edit as ce, collection_sources as sources
from decklab.lib.decks import assembled, standins
from decklab.tests.test_api import ApiTestCase, _write


NAME = "Llanowar Elves"
MYSTIC = "Elvish Mystic"
KEY = "fdn|227|nonfoil"
FOIL = "fdn|227|foil"
ACTOR = state.Actor("test", "a test", source="test")
ROLES = {"profiles": [
    {"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin", "space": "home"},
    {"id": "user1", "name": "User1", "plays_as": "wife", "role": "member", "space": "home"},
    {"id": "user2", "name": "User2", "role": "member", "space": "user2"},
]}


def row(name=NAME, *, finish="nonfoil", quantity=4, set_code="fdn", number="227"):
    return {"name": name, "set": set_code, "collector_number": number, "finish": finish,
            "quantity": str(quantity), "condition": "NM", "language": "en", "notes": ""}


def hint(name=NAME, *, finish="nonfoil", set_code="fdn", number="227"):
    return name, set_code, number, finish


def holder(deck_id="casual/a", title="A", *, cards=None, printings=None, warnings=None, standin_names=None,
           printing_version="target"):
    return pool.InUse(deck_id, title, "intact product" if deck_id.startswith("product/") else "built",
                      Counter({NAME: 1} if cards is None else cards),
                      standin_warnings=[] if warnings is None else warnings,
                      printings=Counter({hint(): 1} if printings is None else printings),
                      standin_names=set() if standin_names is None else set(standin_names),
                      printing_version=printing_version)


def grouped(rows):
    result = {}
    for item in rows:
        result.setdefault(item["name"], []).append(item)
    return result


class ListedHolderTests(unittest.TestCase):
    def annotate(self, rows, holders, counts, *, sees=lambda deck_id: True, records=True):
        storage = {"rows": counts, "error": None}
        return sources.annotate(storage, holders, grouped(rows), sees=sees, records=records)

    def test_only_the_recorded_key_is_named_and_the_remaining_copies_stay_unattributed(self):
        rows = [row(), row(finish="foil", quantity=2)]
        holders = [holder(cards={NAME: 2}, printings={hint(): 2}),
                   holder("casual/b", "B", cards={NAME: 2}, printings={hint(finish="foil"): 1})]
        result = self.annotate(rows, holders, {KEY: {"held": 3, "guess": True}, FOIL: {"held": 1, "guess": False}})
        self.assertEqual(result["rows"][KEY], {"held": 3, "guess": True,
            "listed_holders": [{"id": "casual/a", "title": "A", "quantity": 2, "version": "target"}], "unattributed": 1})
        self.assertEqual(result["rows"][FOIL], {"held": 1, "guess": False,
            "listed_holders": [{"id": "casual/b", "title": "B", "quantity": 1, "version": "target"}], "unattributed": 0})

    def test_physical_logical_mismatch_withholds_the_entire_holder_name_not_other_cards(self):
        rows = [row(quantity=2), row(finish="foil", quantity=2),
                row(MYSTIC, set_code="cmm", number="648", quantity=1)]
        holders = [holder(cards={NAME: 1, MYSTIC: 1}, printings={hint(): 2, hint(finish="foil"): 1,
                    hint(MYSTIC, set_code="cmm", number="648"): 1}),
                   holder("casual/b", "B", cards={NAME: 2}, printings={})]
        result = self.annotate(rows, holders, {KEY: {"held": 2, "guess": False}, FOIL: {"held": 1, "guess": False},
                                              "cmm|648|nonfoil": {"held": 1, "guess": False}})
        for key, quantity in ((KEY, 2), (FOIL, 1)):
            self.assertEqual(result["rows"][key]["listed_holders"], [])
            self.assertEqual(result["rows"][key]["unattributed"], quantity)
        self.assertEqual(result["rows"]["cmm|648|nonfoil"]["listed_holders"],
                         [{"id": "casual/a", "title": "A", "quantity": 1, "version": "target"}])

    def test_a_full_standin_or_a_recipe_warning_never_gives_a_listed_printing_name(self):
        cases = ([holder(cards={}, printings={hint(): 1}), holder("casual/b", "B", printings={})],
                 [holder(warnings=["Saved recipe does not match the physical cards."])])
        for holders in cases:
            with self.subTest(holders=holders):
                result = self.annotate([row()], holders, {KEY: {"held": 1, "guess": False}})
                self.assertEqual(result["rows"][KEY]["listed_holders"], [])
                self.assertEqual(result["rows"][KEY]["unattributed"], 1)

    def test_a_sparse_printing_hint_stays_unattributed_when_one_of_three_copies_is_a_standin(self):
        # Only one of the logical three named a printing: hint total 1 <= physical 2 is not enough evidence.
        rows = [row(quantity=2), row(MYSTIC, set_code="cmm", number="648", quantity=1)]
        use = holder(cards={NAME: 2, MYSTIC: 1, "Pick Your Poison": 1},
                     printings={hint(): 1, hint(MYSTIC, set_code="cmm", number="648"): 1},
                     standin_names={NAME, "Pick Your Poison"})
        result = self.annotate(rows, [use], {KEY: {"held": 2, "guess": False},
                                           "cmm|648|nonfoil": {"held": 1, "guess": False}})
        self.assertEqual(result["rows"][KEY],
                         {"held": 2, "guess": False, "listed_holders": [], "unattributed": 2})
        self.assertEqual(result["rows"]["cmm|648|nonfoil"]["listed_holders"],
                         [{"id": "casual/a", "title": "A", "quantity": 1, "version": "target"}])

    def test_whole_name_overcommit_does_not_give_a_hinted_holder_the_only_owned_copy(self):
        # Raw row hints fit, but physical demand from an unhinted holder also competes for this copy.
        uses = [holder(), holder("casual/b", "Unhinted", printings={})]
        result = self.annotate([row(quantity=1)], uses, {KEY: {"held": 1, "guess": False}})
        self.assertEqual(result["rows"][KEY],
                         {"held": 1, "guess": False, "listed_holders": [], "unattributed": 1})

    def test_competing_exact_hints_do_not_choose_an_arbitrary_owned_copy(self):
        holders = [holder(), holder("casual/b", "B")]
        for ordered in (holders, list(reversed(holders))):
            with self.subTest(order=[item.id for item in ordered]):
                result = self.annotate([row(quantity=1)], ordered, {KEY: {"held": 1, "guess": False}})
                self.assertEqual(result["rows"][KEY],
                                 {"held": 1, "guess": False, "listed_holders": [], "unattributed": 1})

    def test_ineligible_hints_still_block_a_competing_visible_claim(self):
        holders = [holder(), holder("casual/b", "B", cards={NAME: 1}, printings={hint(): 2})]
        result = self.annotate([row(quantity=2)], holders, {KEY: {"held": 2, "guess": False}})
        self.assertEqual(result["rows"][KEY]["listed_holders"], [])
        self.assertEqual(result["rows"][KEY]["unattributed"], 2)
        # The legacy allocation itself is another upper bound; never truncate a named claim to fit it.
        result = self.annotate([row(quantity=4)], [holder(cards={NAME: 2}, printings={hint(): 2})],
                               {KEY: {"held": 1, "guess": False}})
        self.assertEqual(result["rows"][KEY]["listed_holders"], [])
        self.assertEqual(result["rows"][KEY]["unattributed"], 1)

    def test_guess_false_does_not_turn_a_cheapest_or_forced_fallback_into_a_named_holder(self):
        holders = [holder(), holder("casual/b", "B", printings={})]
        result = self.annotate([row(quantity=1), row(finish="foil", quantity=1)], holders,
                               {KEY: {"held": 1, "guess": False}, FOIL: {"held": 1, "guess": False}})
        self.assertEqual(result["rows"][KEY]["listed_holders"],
                         [{"id": "casual/a", "title": "A", "quantity": 1, "version": "target"}])
        self.assertEqual(result["rows"][FOIL]["listed_holders"], [])
        self.assertEqual(result["rows"][FOIL]["unattributed"], 1)

    def test_hidden_and_private_products_are_one_numeric_remainder_without_identity_fields(self):
        holders = [holder(), holder("casual/private", "Private deck"),
                   holder("product/private", "Private product")]
        result = self.annotate([row()], holders, {KEY: {"held": 3, "guess": False}},
                               sees=lambda deck_id: deck_id != "casual/private", records=False)
        self.assertEqual(result["rows"][KEY]["listed_holders"],
                         [{"id": "casual/a", "title": "A", "quantity": 1, "version": "target"}])
        self.assertEqual(result["rows"][KEY]["unattributed"], 2)
        for secret in ("Private", "casual/private", "product/private", "intact", "hidden_count"):
            self.assertNotIn(secret, json.dumps(result))
        self.assertEqual(set(result["rows"][KEY]), {"held", "guess", "listed_holders", "unattributed"})

    def test_duplicate_visible_titles_keep_their_distinct_ids(self):
        result = self.annotate([row(quantity=2)], [holder(title="Same title"), holder("casual/b", "Same title")],
                               {KEY: {"held": 2, "guess": False}})
        listed = result["rows"][KEY]["listed_holders"]
        self.assertEqual({item["id"]: item for item in listed}, {
            "casual/a": {"id": "casual/a", "title": "Same title", "quantity": 1, "version": "target"},
            "casual/b": {"id": "casual/b", "title": "Same title", "quantity": 1, "version": "target"}})
        self.assertEqual(result["rows"][KEY]["unattributed"], 0)

    def test_holder_links_keep_the_evidence_list_version_and_withhold_invalid_versions(self):
        for version in ("target", "owned", None, "", "owned-only", "target&profile=private"):
            with self.subTest(version=version):
                result = self.annotate([row(quantity=1)], [holder(printing_version=version)],
                                       {KEY: {"held": 1, "guess": False}})
                expected = ([{"id": "casual/a", "title": "A", "quantity": 1, "version": version}]
                            if version in ("target", "owned") else [])
                self.assertEqual(result["rows"][KEY], {"held": 1, "guess": False,
                                 "listed_holders": expected, "unattributed": 0 if expected else 1})

    def test_basics_and_unavailable_storage_keep_their_unknown_state(self):
        basic = row("Forest", number="280", finish="foil", quantity=3)
        result = self.annotate([basic], [holder(cards={"Forest": 100}, printings={hint("Forest", number="280", finish="foil"): 100})],
                               {"fdn|280|foil": {"held": None, "guess": False}})
        self.assertEqual(result["rows"]["fdn|280|foil"],
                         {"held": None, "guess": False, "listed_holders": [], "unattributed": None})
        failed = {"rows": {}, "error": "The copies in decks couldn't be worked out."}
        self.assertEqual(sources.annotate(failed, [], {}, sees=lambda deck_id: True, records=True), failed)

    def test_projection_clones_inputs_and_performs_no_other_inventory_or_deck_reads(self):
        rows = [row()]
        holders = [holder()]
        storage = {"rows": {KEY: {"held": 1, "guess": False}}, "error": None}
        before = copy.deepcopy((storage, holders, rows))
        with mock.patch.object(pool, "load_pool", side_effect=AssertionError("no pool reload")), \
                mock.patch.object(decks, "load_deck", side_effect=AssertionError("no deck read")), \
                mock.patch.object(inventory, "current", side_effect=AssertionError("no inventory read")), \
                mock.patch.object(inventory, "deck_revisions_with_text", side_effect=AssertionError("no history")):
            result = sources.annotate(storage, holders, grouped(rows), sees=lambda deck_id: True, records=True)
        self.assertEqual((storage, holders, rows), before)
        self.assertIsNot(result, storage)
        self.assertIsNot(result["rows"][KEY], storage["rows"][KEY])
        self.assertEqual(result["rows"][KEY]["unattributed"], 0)

    def test_visibility_read_failures_remove_earlier_names_but_keep_every_legacy_count(self):
        rows = [row(quantity=3), row(finish="foil", quantity=2), row("Forest", number="280")]
        uses = [holder(cards={NAME: 2}, printings={hint(): 1}),
                holder("casual/private", "Private source title", printings={hint(finish="foil"): 1})]
        storage = {"rows": {KEY: {"held": 2, "guess": True}, FOIL: {"held": 1, "guess": False},
                            "fdn|280|nonfoil": {"held": None, "guess": False}}, "error": None}
        expected = {"rows": {KEY: {"held": 2, "guess": True, "listed_holders": [], "unattributed": 2},
                             FOIL: {"held": 1, "guess": False, "listed_holders": [], "unattributed": 1},
                             "fdn|280|nonfoil": {"held": None, "guess": False,
                                                "listed_holders": [], "unattributed": None}}, "error": None}
        before = copy.deepcopy((storage, rows, uses))
        for error_type in (OSError, RuntimeError, state.Unavailable):
            for failure_at in ("predicate", "named_holder"):
                with self.subTest(error=error_type.__name__, failure_at=failure_at):
                    error = error_type("Secret diagnostic: private source path")
                    read = mock.Mock(side_effect=[True, error])
                    policy = read if failure_at == "predicate" else lambda deck_id: True
                    probe = (mock.patch.object(sources, "named_holder", wraps=sources.named_holder)
                             if failure_at == "predicate"
                             else mock.patch.object(sources, "named_holder", side_effect=read))
                    with probe as named:
                        result = sources.annotate(storage, uses, grouped(rows), sees=policy, records=True)
                    self.assertEqual([call.args[0] for call in named.call_args_list],
                                     ["casual/a", "casual/private"])
                    self.assertEqual(read.call_count, 2)  # The first row was named before the later read failed.
                    self.assertEqual(result, expected)
                    self.assertIsNot(result, storage)
                    self.assertTrue(all(result["rows"][key] is not storage["rows"][key] for key in storage["rows"]))
                    self.assertEqual((storage, rows, uses), before)
                    for secret in ("Secret diagnostic", "private source path", "Private source title", "casual/a", "casual/private"):
                        self.assertNotIn(secret, json.dumps(result))

    def test_programmer_errors_in_visibility_and_canonical_rows_still_propagate(self):
        for error_type in (TypeError, KeyError, AssertionError, ValueError):
            for failure_at in ("predicate", "named_holder"):
                with self.subTest(error=error_type.__name__, failure_at=failure_at):
                    error = error_type("fixture programming error")
                    predicate = mock.Mock(side_effect=error)
                    probe = (mock.patch.object(sources, "named_holder", wraps=sources.named_holder)
                             if failure_at == "predicate"
                             else mock.patch.object(sources, "named_holder", side_effect=error))
                    with probe, self.assertRaises(error_type) as caught:
                        self.annotate([row()], [holder()], {KEY: {"held": 1, "guess": False}},
                                      sees=predicate if failure_at == "predicate" else lambda deck_id: True)
                    self.assertIs(caught.exception, error)
        for malformed, error_type in (({**row(), "quantity": "not a number"}, ValueError),
                                      ({key: value for key, value in row().items() if key != "quantity"}, KeyError)):
            with self.subTest(malformed=malformed), self.assertRaises(error_type):
                self.annotate([malformed], [holder()], {KEY: {"held": 1, "guess": False}})


class CollectionSourcePrivacyTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.enterContext(mock.patch.object(config, "REPO", self.box.root))
        self.enterContext(mock.patch.object(config, "DATA", self.box.data))
        _write(self.box.root / "config.json", json.dumps(ROLES))
        _write(self.box.magic / "people/user2/collection.csv",
               "name,set,collector_number,finish,quantity,condition,language,notes\n"
               "Llanowar Elves,fdn,227,nonfoil,2,NM,en,\n")

    def as_(self, who):
        return access.using({"profile": who, "email": "", "remote": True})

    def publish(self, owner, thing):
        self.box.state.visibility_set(owner, thing, True, ACTOR, "Publish fixture")

    def test_public_collection_and_public_decks_do_not_publish_product_source_names(self):
        self.publish("home", "collection")
        holders = [holder("casual/public", "A public deck"),
                   holder("product/fdn-beginner-box", "Private product source")]
        fake = pool.Pool(Counter(), {}, holders)
        with self.as_("user2"), mock.patch.object(pool, "load_pool", return_value=fake):
            private = ce.rows_view("home")
        self.assertFalse(private["editable"])
        self.assertEqual(private["storage"]["rows"][KEY]["listed_holders"], [])
        self.assertEqual(private["storage"]["rows"][KEY]["unattributed"], 2)
        self.publish("home", "decks")
        with self.as_("user2"), mock.patch.object(pool, "load_pool", return_value=fake):
            public = ce.rows_view("home")
        self.assertEqual(public["storage"]["rows"][KEY]["listed_holders"],
                         [{"id": "casual/public", "title": "A public deck", "quantity": 1, "version": "target"}])
        self.assertEqual(public["storage"]["rows"][KEY]["unattributed"], 1)
        for secret in ("Private product source", "product/fdn-beginner-box"):
            self.assertNotIn(secret, json.dumps(public["storage"]))
        with self.as_("matt"), mock.patch.object(pool, "load_pool", return_value=fake):
            own = ce.rows_view("home")
        self.assertEqual({item["id"] for item in own["storage"]["rows"][KEY]["listed_holders"]},
                         {"casual/public", "product/fdn-beginner-box"})
        self.assertEqual(own["storage"]["rows"][KEY]["unattributed"], 0)

    def test_public_member_collection_has_no_admin_override_for_its_private_decks(self):
        self.publish("user2", "collection")
        fake = pool.Pool(Counter(), {}, [holder("user2/casual/private", "Private member deck", cards={NAME: 2},
                                               printings={hint(): 2})], space="user2")
        with self.as_("matt"), mock.patch.object(pool, "load_pool", return_value=fake):
            answer = ce.rows_view("user2")
        self.assertFalse(answer["editable"])
        self.assertEqual(answer["storage"]["rows"][KEY]["listed_holders"], [])
        self.assertEqual(answer["storage"]["rows"][KEY]["unattributed"], 2)
        self.assertNotIn("Private member deck", json.dumps(answer))
        self.assertNotIn("user2/casual/private", json.dumps(answer))
        self.publish("user2", "decks")
        with self.as_("matt"), mock.patch.object(pool, "load_pool", return_value=fake):
            public = ce.rows_view("user2")
        self.assertEqual(public["storage"]["rows"][KEY]["listed_holders"],
                         [{"id": "user2/casual/private", "title": "Private member deck", "quantity": 2, "version": "target"}])

    def test_private_collection_is_denied_before_a_pool_or_source_read(self):
        with self.as_("matt"), mock.patch.object(pool, "load_pool", side_effect=AssertionError("no hidden pool")) as load:
            error = self.assertApiError(403, ce.rows_view, "user2")
        self.assertEqual(error.extra, {})
        load.assert_not_called()

    def test_rows_save_and_stale_refresh_keep_source_metadata_outside_the_canonical_rows(self):
        fake = pool.Pool(Counter(), {}, [holder()])
        with self.as_("matt"), mock.patch.object(pool, "load_pool", return_value=fake), \
                mock.patch.object(ce, "_stale_tables", return_value=[]):
            before = ce.rows_view("home")
            original = next(item for item in before["rows"] if ce._picture_key(item) == KEY)
            body = {"profile": "matt", "space": "home", "action": "edit", "sha256": before["sha256"],
                    "original": {key: original[key] for key in ("set", "collector_number", "finish")},
                    "row": {**original, "condition": "LP"}}
            saved = ce.save_card(json.dumps(body).encode("utf-8"))
            stale = self.assertApiError(409, ce.save_card, json.dumps(body).encode("utf-8"))
            current = ce.rows_view("home")
        expected = {"held": 1, "guess": False,
                    "listed_holders": [{"id": "casual/a", "title": "A", "quantity": 1, "version": "target"}], "unattributed": 0}
        for answer in (before, saved, stale.extra, current):
            self.assertEqual(answer["storage"]["rows"][KEY], expected)
            self.assertTrue(all(set(item) == set(ce.FIELDS) for item in answer["rows"]))
            self.assertNotIn("listed_holders", json.dumps(answer["rows"]))
        self.assertTrue(saved["ok"])
        self.assertNotEqual(saved["sha256"], before["sha256"])
        self.assertEqual((stale.extra["sha256"], current["sha256"]), (saved["sha256"], saved["sha256"]))
        self.assertEqual(next(item["condition"] for item in current["rows"] if ce._picture_key(item) == KEY), "LP")

    def test_storage_hook_preserves_legacy_counts_with_one_pool_read_and_generic_failures(self):
        rows = [row(quantity=2)]
        fake = pool.Pool(Counter(), {}, [holder(cards={NAME: 2}, printings={hint(): 1})])
        before = copy.deepcopy((rows, fake))
        with self.as_("matt"), mock.patch.object(pool, "load_pool", return_value=fake) as load, \
                mock.patch.object(decks, "load_deck", side_effect=AssertionError("no deck reload")):
            result = ce._storage("home", rows, {"rows": {}})
        load.assert_called_once_with()
        self.assertEqual(result["rows"][KEY], {"held": 2, "guess": False,
            "listed_holders": [{"id": "casual/a", "title": "A", "quantity": 1, "version": "target"}], "unattributed": 1})
        self.assertEqual((rows, fake), before)
        self.publish("home", "collection")
        with self.as_("user2"), mock.patch.object(pool, "load_pool", side_effect=ValueError("private deck and order name")):
            failed = ce._storage("home", rows, {"rows": {}})
        self.assertEqual(failed["rows"], {})
        self.assertNotIn("private", failed["error"])
        with mock.patch.object(ce, "_ready", return_value=False):
            unavailable = ce._storage("home", rows, {"rows": {}})
        self.assertEqual(unavailable["rows"], {})
        self.assertTrue(unavailable["error"])

    def test_optional_policy_construction_read_failures_keep_the_allocated_storage_counts(self):
        rows = [row(quantity=2)]
        fake = pool.Pool(Counter(), {}, [holder(cards={NAME: 2}, printings={hint(): 1})])
        before = copy.deepcopy((rows, fake))
        for guard_name in ("deck_reader", "sees_home_records"):
            for error_type in (OSError, RuntimeError, state.Unavailable):
                with self.subTest(guard=guard_name, error=error_type.__name__):
                    with self.as_("matt"), mock.patch.object(pool, "load_pool", return_value=fake) as load, \
                            mock.patch.object(ce.guard, guard_name, side_effect=error_type("Secret private policy diagnostic")):
                        result = ce._storage("home", rows, {"rows": {}})
                    load.assert_called_once_with()
                    self.assertEqual(result, {"rows": {KEY: {"held": 2, "guess": False,
                                     "listed_holders": [], "unattributed": 2}}, "error": None})
                    self.assertNotIn("Secret", json.dumps(result))
                    self.assertEqual((rows, fake), before)

    def test_programmer_errors_in_optional_policy_construction_or_projection_are_not_swallowed(self):
        rows = [row(quantity=2)]
        fake = pool.Pool(Counter(), {}, [holder(cards={NAME: 2}, printings={hint(): 1})])
        for error_type in (TypeError, KeyError, AssertionError, ValueError):
            for owner, method in ((ce.guard, "deck_reader"), (ce.guard, "sees_home_records"), (sources, "annotate")):
                with self.subTest(method=method, error=error_type.__name__):
                    error = error_type("fixture programming error")
                    with self.as_("matt"), mock.patch.object(pool, "load_pool", return_value=fake) as load, \
                            mock.patch.object(owner, method, side_effect=error), self.assertRaises(error_type) as caught:
                        ce._storage("home", rows, {"rows": {}})
                    load.assert_called_once_with()
                    self.assertIs(caught.exception, error)

    def test_real_pool_tracks_canonical_installed_standin_names_without_another_snapshot_read(self):
        _write(self.box.magic / "products/status.csv",
               "file,status,intact,notes\nfdn-beginner-box.csv,cancelled,,\nfdc-test-precon.csv,cancelled,,\n")
        _write(self.box.magic / "collection.csv", ",".join(ce.FIELDS) + "\n"
               "Llanowar Elves,fdn,227,nonfoil,2,NM,en,\n"
               "Elvish Mystic,cmm,648,nonfoil,1,NM,en,\n"
               "Pick Your Poison,mkm,170,nonfoil,1,NM,en,\n")
        path = self.box.magic / "decks/casual/sparse.md"
        text = ("# Sparse printing\n\n- **Status:** built\n- **Played by:** user\n\n## Decklist\n\n```\nDeck\n"
                "1 Llanowar Elves (FDN) 227\n2 Llanowar Elves\n1 Elvish Mystic (CMM) 648\n```\n")
        parsed = decks.parse_deck(text.encode("utf-8"), "sparse", "casual")
        standins.install_stand_ins(parsed, "target", [{"for": NAME, "using": "pick your poison", "qty": 1}])
        _write(path, decks.render_deck_file(parsed))
        inventory.invalidate()
        rows = [row(quantity=2), row(MYSTIC, set_code="cmm", number="648", quantity=1)]
        with self.as_("matt"), mock.patch.object(self.box.inventory, "load", wraps=self.box.inventory.load) as read, \
                mock.patch.object(inventory, "deck_revisions_with_text", side_effect=AssertionError("no history")), \
                inventory.pinned():
            actual = pool.load_pool()
            use = next(item for item in actual.in_use if item.id == "casual/sparse")
            self.assertEqual(use.cards, Counter({NAME: 2, MYSTIC: 1, "Pick Your Poison": 1}))
            self.assertEqual(use.printings[hint()], 1)
            self.assertEqual(use.standin_names, {NAME, "Pick Your Poison"})
            self.assertEqual(use.standin_warnings, [])
            with mock.patch.object(pool, "load_pool", return_value=actual):
                result = ce._storage("home", rows, {"rows": {}})
        self.assertEqual(read.call_count, 1)
        self.assertEqual(result["rows"][KEY],
                         {"held": 2, "guess": False, "listed_holders": [], "unattributed": 2})
        self.assertEqual(result["rows"]["cmm|648|nonfoil"]["listed_holders"],
                         [{"id": "casual/sparse", "title": "Sparse printing", "quantity": 1, "version": "target"}])

    def test_real_pool_source_links_use_the_assembled_list_version_and_products_use_target(self):
        _write(self.box.magic / "products/status.csv",
               "file,status,intact,notes\nfdn-beginner-box.csv,cancelled,,\nfdc-test-precon.csv,cancelled,,\n"
               "source-box.csv,owned,yes,\n")
        _write(self.box.magic / "products/source-box.csv",
               "section,name,set,collector_number,finish,quantity\ndeck,Elvish Mystic,cmm,648,nonfoil,1\n")
        _write(self.box.magic / "collection.csv", ",".join(ce.FIELDS) + "\n"
               "Llanowar Elves,fdn,227,nonfoil,1,NM,en,\n"
               "Llanowar Elves,m19,314,nonfoil,1,NM,en,\n"
               "Elvish Mystic,cmm,648,nonfoil,1,NM,en,\n")
        text = ("# Assembled Play-now\n\n- **Status:** built\n- **Played by:** user\n- **Built version:** target\n\n"
                "## Decklist\n\n```\nDeck\n1 Llanowar Elves (M19) 314\n```\n\n"
                "## Substitutes\n\n### Owned-only version\n\n```\nDeck\n1 Llanowar Elves (FDN) 227\n```\n")
        parsed = decks.parse_deck(text.encode("utf-8"), "assembled-owned", "casual")
        assembled.install(parsed, "owned", parsed.owned)
        self.assertEqual(parsed.built_version, "target")
        self.assertEqual(assembled.version(parsed), "owned")
        _write(self.box.magic / "decks/casual/assembled-owned.md", decks.render_deck_file(parsed))
        _write(self.box.magic / "decks/casual/planned.md",
               "# Planned printing\n\n- **Status:** built\n- **Played by:** user\n\n"
               "## Decklist\n\n```\nDeck\n1 Llanowar Elves (M19) 314\n```\n")
        inventory.invalidate()
        rows = [row(quantity=1), row(set_code="m19", number="314", quantity=1),
                row(MYSTIC, set_code="cmm", number="648", quantity=1)]
        self.publish("home", "collection")
        with self.as_("matt"), mock.patch.object(self.box.inventory, "load", wraps=self.box.inventory.load) as read, \
                mock.patch.object(decks, "load_deck", wraps=decks.load_deck) as deck_read, \
                mock.patch.object(inventory, "deck_revisions_with_text", side_effect=AssertionError("no history")), \
                inventory.pinned():
            actual = pool.load_pool()
            uses = {item.id: item for item in actual.in_use}
            self.assertEqual(set(uses), {"casual/assembled-owned", "casual/planned", "product/source-box"})
            owned = uses["casual/assembled-owned"]
            self.assertEqual((owned.printing_version, owned.cards, owned.printings),
                             ("owned", Counter({NAME: 1}), Counter({hint(): 1})))
            self.assertEqual((uses["casual/planned"].printing_version, uses["casual/planned"].printings),
                             ("target", Counter({hint(set_code="m19", number="314"): 1})))
            self.assertEqual((uses["product/source-box"].printing_version, uses["product/source-box"].why),
                             ("target", "intact product"))
            reads_before_projection = deck_read.call_count
            with mock.patch.object(pool, "load_pool", return_value=actual):
                result = ce._storage("home", rows, {"rows": {}})
                with self.as_("user2"):
                    hidden = ce.rows_view("home")["storage"]
            self.assertEqual(deck_read.call_count, reads_before_projection)
        self.assertEqual(read.call_count, 1)
        for key, deck_id, version in ((KEY, "casual/assembled-owned", "owned"),
                                      ("m19|314|nonfoil", "casual/planned", "target"),
                                      ("cmm|648|nonfoil", "product/source-box", "target")):
            with self.subTest(key=key):
                self.assertEqual(result["rows"][key], {"held": 1, "guess": False, "unattributed": 0,
                    "listed_holders": [{"id": deck_id, "title": uses[deck_id].title,
                                        "quantity": 1, "version": version}]})
                self.assertEqual(hidden["rows"][key],
                                 {"held": 1, "guess": False, "listed_holders": [], "unattributed": 1})
        for secret in ("Assembled Play-now", "casual/assembled-owned", "product/source-box", '"version"'):
            self.assertNotIn(secret, json.dumps(hidden))
