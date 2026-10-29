"""The state stores' contract (decklab/lib/state): the same tests on the in-memory store, always,
and on the PostgreSQL store, in a throwaway database (they skip without one: db_support.py).

StoreContract holds the tests; each backend's class says how to make its store. Between them
they check that both keep the same rules (wishlist order, casefold names, the list's limit,
settings' upsert and no-op, the simulations mode, play records' hashes and conflicts) and
write the same audit trail, so tests elsewhere can rely on the MemoryStore meaning PostgreSQL.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_state_contract
The fixture runner disables configured PostgreSQL and real Forge; named native
runtime cases also need separate qualification (see AGENTS.md, Tests).
"""
import copy
import os
import threading
import unittest
from datetime import datetime, timezone
from unittest import mock

from decklab.lib import state
from decklab.lib.state import Actor, Conflict, Invalid, Unavailable, rules
from decklab.lib.state.memory import MemoryStore
from decklab.tests import db_support

MATT = Actor("matt", "Matt", "home")
USER1 = Actor("user1", "User1", "tunnel")
CLAUDE = Actor("claude", "Claude", None, "cli")

ID_A = "a" * 32
ID_B = "b" * 32
ID_C = "c" * 32


def entry(name, set_code="", number="", notes="", source=""):
    return {"name": name, "set": set_code, "number": number, "notes": notes, "source": source}


def game(record_id, revision=1, notes="", created="2026-10-11T01:02:03+00:00", updated=None):
    side = lambda deck_id, title: {"id": deck_id, "version": "target", "title": title,   # noqa: E731
                                   "sections": {"Deck": [{"name": "Plains", "qty": 4}]},
                                   "sha256": "0" * 64, "player": "Matt", "mulligans": 0}
    return {"version": 1, "id": record_id, "kind": "games", "revision": revision, "created_on": created,
            "updated_on": updated or created, "updated_by": "Matt", "date": "2026-10-10",
            "sides": [side("casual/gruul", "Gruul"), side("user2/casual/elves", "Elves")],
            "result": "a", "notes": notes}


def plan(record_id):
    selection = lambda deck_id: {"id": deck_id, "version": "target", "title": deck_id,   # noqa: E731
                                 "sections": {"Deck": [{"name": "Plains", "qty": 1}]}, "sha256": "1" * 64}
    return {"version": 1, "id": record_id, "kind": "sideboards", "revision": 1,
            "created_on": "2026-10-11T01:02:03.456789+00:00", "updated_on": "2026-10-11T01:02:03.456789+00:00",
            "updated_by": "User1", "deck": selection("casual/free-peoples"), "opponent": selection("casual/otters"),
            "out": [], "in": [], "after": {"Deck": []}, "notes": ""}


def operations(store):
    """One sequence of writes of every kind, for comparing the stores' audit trails."""
    store.wishlist_add("user1", entry("Plains", "sld", "1513"), USER1, "Add Plains to User1's wishlist")
    store.wishlist_add("user1", entry("Forest"), USER1, "Add Forest to User1's wishlist")
    store.wishlist_set("user1", "forest", CLAUDE, "Note Forest", notes="for the deck", source="magic/x.md")
    store.wishlist_remove("user1", "plains", USER1, "Remove Plains from User1's wishlist", reason="bought")
    store.settings_put("matt", {"theme": "dark", "matchup_games": "800"}, MATT, "Change Matt's settings")
    store.settings_put("matt", {"theme": "light", "matchup_games": None}, MATT, "Change Matt's settings again")
    store.simulation_mode_set("everyone", MATT, "Set simulations to everyone")
    store.simulation_mode_set("paused", MATT, "Set simulations to paused")
    store.visibility_set("home", "decks", True, MATT, "Make the home decks public")
    store.visibility_set("guest", "games", True, CLAUDE, "Make test games public")
    store.visibility_set("home", "decks", False, USER1, "Make the home decks private")
    first = store.play_put("games", game(ID_A), None, MATT, "Save game Gruul vs Elves")
    store.play_put("games", game(ID_A, 2, "Close one", updated="2026-10-11T02:00:00+00:00"),
                   rules.record_sha(first), MATT, "Save game Gruul vs Elves")
    store.play_put("sideboards", plan(ID_B), None, USER1, "Save sideboard plan")


def comparable(activity):
    """activity() without what can't match between stores: ids, times and the mode's since."""
    out = copy.deepcopy(activity["changes"])
    for change in out:
        change.pop("id")
        change.pop("at")
        for row in change["rows"]:
            for side in ("before", "after"):
                if row["table"] in ("simulation_mode", "visibility") and row[side]:
                    row[side]["since"] = None
    return out


class StoreContract:
    """The tests every store passes. Subclasses set self.store in setUp."""

    def trail(self):
        return self.store.activity(limit=100)["changes"]

    # ------------------------------------------------------------------ wishlists

    def test_a_new_wishlist_is_empty(self):
        self.assertEqual(self.store.wishlist("user1"), [])

    def test_adds_keep_their_order_and_shape(self):
        self.assertEqual(self.store.wishlist_add("user1", entry("Plains", "sld", "1513"), USER1, "Add Plains"),
                         (True, [entry("Plains", "sld", "1513")]))
        changed, entries = self.store.wishlist_add("user1", {"name": "Forest", "set": "", "number": ""},
                                                   USER1, "Add Forest")
        self.assertTrue(changed)
        self.assertEqual(entries, [entry("Plains", "sld", "1513"), entry("Forest")])
        self.assertEqual(self.store.wishlist("user1"), entries)
        self.assertEqual(self.store.wishlist("matt"), [])

    def test_a_casefold_equal_name_is_unchanged_and_writes_nothing(self):
        self.store.wishlist_add("user1", entry("Straße"), USER1, "Add Straße")
        before = len(self.trail())
        self.assertEqual(self.store.wishlist_add("user1", entry("STRASSE"), USER1, "Add STRASSE"),
                         (False, [entry("Straße")]))
        self.assertEqual(len(self.trail()), before)

    def test_remove_matches_by_casefold_and_order_survives(self):
        for name in ("A", "B", "C"):
            self.store.wishlist_add("user1", entry(name), USER1, f"Add {name}")
        self.assertEqual(self.store.wishlist_remove("user1", "b", USER1, "Remove B")[0], True)
        self.store.wishlist_add("user1", entry("D"), USER1, "Add D")
        self.assertEqual([e["name"] for e in self.store.wishlist("user1")], ["A", "C", "D"])
        before = len(self.trail())
        self.assertEqual(self.store.wishlist_remove("user1", "nope", USER1, "Remove nope"),
                         (False, self.store.wishlist("user1")))
        self.assertEqual(len(self.trail()), before)

    def test_add_at_puts_a_removed_card_back_where_it_was(self):
        # The page's Undo of a removal: the removed card's position is free, so nothing else moves.
        for name in ("A", "B", "C", "D"):
            self.store.wishlist_add("user1", entry(name), USER1, f"Add {name}")
        self.store.wishlist_remove("user1", "B", USER1, "Remove B")
        before = len(self.trail())
        changed, entries = self.store.wishlist_add("user1", entry("B", notes="back"), USER1, "Put B back", at=1)
        self.assertTrue(changed)
        self.assertEqual([e["name"] for e in entries], ["A", "B", "C", "D"])
        self.assertEqual(self.store.wishlist("user1"), entries)
        trail = self.trail()
        self.assertEqual(len(trail), before + 1)
        self.assertEqual([(r["op"], r["key"]["position"]) for r in trail[0]["rows"]], [("INSERT", 1)])
        # The first card, put back first.
        self.store.wishlist_remove("user1", "A", USER1, "Remove A")
        self.assertEqual([e["name"] for e in self.store.wishlist_add("user1", entry("A"), USER1, "A back", at=0)[1]],
                         ["A", "B", "C", "D"])
        # An index past the end appends.
        self.assertEqual(self.store.wishlist_add("user1", entry("E"), USER1, "Add E", at=99)[1][-1]["name"], "E")

    def test_add_at_moves_the_cards_up_to_the_next_free_position(self):
        for name in ("A", "B", "C", "D", "E"):
            self.store.wishlist_add("user1", entry(name), USER1, f"Add {name}")
        self.store.wishlist_remove("user1", "D", USER1, "Remove D")          # positions 0 1 2 4
        changed, entries = self.store.wishlist_add("user1", entry("X"), USER1, "Add X", at=1)
        self.assertEqual([e["name"] for e in entries], ["A", "X", "B", "C", "E"])
        self.assertEqual(self.store.wishlist("user1"), entries)
        rows = self.trail()[0]["rows"]
        self.assertEqual([(r["op"], r["before"] and r["before"]["position"], r["after"]["position"]) for r in rows],
                         [("UPDATE", 2, 3), ("UPDATE", 1, 2), ("INSERT", None, 1)])
        for bad in (-1, 1.5, True, "1"):
            with self.subTest(at=bad), self.assertRaises(Invalid):
                self.store.wishlist_add("user1", entry("Y"), USER1, "Add Y", at=bad)

    def test_a_full_wishlist_refuses_another_card(self):
        with mock.patch.object(rules, "MAX_ENTRIES", 2):
            self.store.wishlist_add("user1", entry("A"), USER1, "Add A")
            self.store.wishlist_add("user1", entry("B"), USER1, "Add B")
            with self.assertRaisesRegex(Invalid, "at most 1000 cards"):
                self.store.wishlist_add("user1", entry("C"), USER1, "Add C")
            # A name already there is still just "unchanged".
            self.assertFalse(self.store.wishlist_add("user1", entry("a"), USER1, "Add a")[0])
        self.assertEqual(len(self.store.wishlist("user1")), 2)

    def test_bad_entries_and_ids_are_invalid(self):
        for bad in (entry(" Plains"), entry(""), entry("Plains", "sld"), entry("Plains", "SLD", "1"),
                    entry("x" * 151), entry("Plains", notes="n" * 2001), {"name": "Plains"}):
            with self.subTest(bad=bad), self.assertRaises(Invalid):
                self.store.wishlist_add("user1", bad, USER1, "Add")
        for bad in ("", "a b", "../x", None, "x" * 65):
            with self.subTest(profile=bad), self.assertRaises(Invalid):
                self.store.wishlist(bad)
        self.assertEqual(self.store.wishlist("user1"), [])

    def test_control_characters_are_refused_but_notes_keep_line_breaks(self):
        for bad in (entry("Pla\x00ins"), entry("Plains\n"), entry("Plains", notes="a\x00b"),
                    entry("Plains", source="x\ty"), entry("Plains", notes="bell\x07")):
            with self.subTest(bad=bad), self.assertRaises(Invalid):
                self.store.wishlist_add("user1", bad, USER1, "Add")
        self.assertTrue(self.store.wishlist_add("user1", entry("Plains", notes="line one\nline two\tok"),
                                                USER1, "Add")[0])
        self.assertEqual(self.store.wishlist("user1")[0]["notes"], "line one\nline two\tok")
        with self.assertRaises(Invalid):
            self.store.wishlist_set("user1", "Plains", CLAUDE, "NUL", notes="\x00")

    def test_wishlist_set_changes_fields_and_refuses_an_absent_card(self):
        self.store.wishlist_add("user1", entry("Plains"), USER1, "Add Plains")
        self.assertEqual(self.store.wishlist_set("user1", "PLAINS", CLAUDE, "Note it", notes="art", set="sld",
                                                 number="1513"),
                         (True, [entry("Plains", "sld", "1513", notes="art")]))
        before = len(self.trail())
        self.assertFalse(self.store.wishlist_set("user1", "plains", CLAUDE, "Same", notes="art")[0])
        self.assertEqual(len(self.trail()), before)
        self.assertEqual(self.store.wishlist_set("user1", "plains", CLAUDE, "No printing", set="", number="")[1],
                         [entry("Plains", notes="art")])
        with self.assertRaises(Invalid):
            self.store.wishlist_set("user1", "Forest", CLAUDE, "Absent", notes="x")
        with self.assertRaises(Invalid):
            self.store.wishlist_set("user1", "Plains", CLAUDE, "Half a printing", set="sld")

    # ------------------------------------------------------------------ settings

    def test_settings_upsert_delete_and_no_op(self):
        self.assertEqual(self.store.settings("matt"), {})
        self.assertEqual(self.store.settings_put("matt", {"theme": "dark", "matchup_games": "800"}, MATT, "Set"),
                         {"matchup_games": "800", "theme": "dark"})
        before = len(self.trail())
        self.assertEqual(self.store.settings_put("matt", {"theme": "dark"}, MATT, "Same"),
                         {"matchup_games": "800", "theme": "dark"})
        # Removing a key that isn't saved changes nothing either.
        self.assertEqual(self.store.settings_put("matt", {"field_budget": None}, MATT, "Clear"),
                         {"matchup_games": "800", "theme": "dark"})
        self.assertEqual(len(self.trail()), before)
        self.assertEqual(self.store.settings_put("matt", {"theme": None, "matchup_games": "400"}, MATT, "Change"),
                         {"matchup_games": "400"})
        self.assertEqual(self.store.settings("matt"), {"matchup_games": "400"})
        self.assertEqual(self.store.settings("user1"), {})
        rows = self.trail()[0]["rows"]
        self.assertEqual([(r["op"], r["key"]) for r in rows],
                         [("UPDATE", {"profile_id": "matt", "key": "matchup_games"}),
                          ("DELETE", {"profile_id": "matt", "key": "theme"})])

    def test_settings_come_back_in_plain_key_order(self):
        # en_US collation ignores underscores ("ab" before "a_c"); both stores sort by code point.
        self.store.settings_put("matt", {"ab": "1", "a_c": "2", "a_b": "3", "b": "4"}, MATT, "Set")
        self.assertEqual(list(self.store.settings("matt")), ["a_b", "a_c", "ab", "b"])

    def test_bad_settings_are_invalid(self):
        for bad in ({"Theme": "dark"}, {"theme": 3}, {"theme": "x" * 201}, {"": "x"}, {"theme": "da\x00rk"},
                    {"theme": "dark\n"}):
            with self.subTest(bad=bad), self.assertRaises(Invalid):
                self.store.settings_put("matt", bad, MATT, "Bad")

    # ------------------------------------------------------------------ the simulations mode

    def test_the_mode_starts_unset_and_records_who_set_it(self):
        self.assertIsNone(self.store.simulation_mode())
        view = self.store.simulation_mode_set("everyone", MATT, "Set simulations to everyone")
        self.assertEqual({k: view[k] for k in ("mode", "by", "by_id")}, {"mode": "everyone", "by": "Matt", "by_id": "matt"})
        self.assertIsNotNone(datetime.fromisoformat(view["since"]).tzinfo)
        self.assertEqual(self.store.simulation_mode(), view)
        self.store.simulation_mode_set("paused", USER1, "Set simulations to paused")
        self.assertEqual(self.store.simulation_mode()["by"], "User1")
        with self.assertRaises(Invalid):
            self.store.simulation_mode_set("nobody", MATT, "Bad")
        self.assertEqual([r["op"] for c in self.trail() for r in c["rows"]], ["UPDATE", "INSERT"])

    def test_an_imported_mode_keeps_its_time_and_name(self):
        view = self.store.simulation_mode_set("admins", Actor("system", "System", None, "migration"),
                                              "Import phase 2 files", since="2026-10-01T09:30:00+10:00",
                                              by_name="Matt")
        self.assertEqual(view["by"], "Matt")
        self.assertIsNone(view["by_id"])
        self.assertEqual(datetime.fromisoformat(view["since"]),
                         datetime.fromisoformat("2026-10-01T09:30:00+10:00"))

    def test_a_time_without_an_offset_is_local_time_in_both_stores(self):
        view = self.store.simulation_mode_set("admins", Actor("system", "System", None, "migration"),
                                              "Import", since="2026-10-01T09:30:00", by_name="Matt")
        self.assertEqual(datetime.fromisoformat(view["since"]),
                         datetime.fromisoformat("2026-10-01T09:30:00").astimezone())
        row = self.trail()[0]["rows"][0]["after"]
        self.assertEqual(datetime.fromisoformat(row["since"]), datetime.fromisoformat(view["since"]))
        self.store.simulation_mode_set("admins", MATT, "Fraction", since="2026-10-01T09:30:00.120000+10:00")
        row = self.trail()[0]["rows"][0]["after"]
        self.assertIn(":00.12", row["since"])
        self.assertNotIn(".120", row["since"])
        for bad in ({"since": "yesterday"}, {"by_name": 3}, {"by_name": "Ma\x00tt"}, {"by_name": " "}):
            with self.subTest(bad=bad), self.assertRaises(Invalid):
                self.store.simulation_mode_set("admins", MATT, "Bad", **bad)

    def test_the_cached_readers_answer_with_the_last_values(self):
        self.store.settings_put("matt", {"theme": "dark"}, MATT, "Set")
        self.store.simulation_mode_set("paused", MATT, "Pause")
        self.assertEqual(self.store.settings_cached("matt"), {"theme": "dark"})
        self.assertEqual(self.store.settings_cached("user1"), {})
        self.assertEqual(self.store.simulation_mode_cached(), self.store.simulation_mode())

    # ------------------------------------------------------------------ visibility

    def test_visibility_starts_private_and_a_flip_records_its_actor(self):
        self.assertEqual(self.store.visibility(), {})
        self.assertEqual(self.store.visibility_cached(), {})
        view = self.store.visibility_set("home", "decks", True, MATT, "Make the home decks public")
        self.assertEqual(set(view), {("home", "decks")})
        row = view["home", "decks"]
        self.assertEqual((row["by"], row["by_id"]), ("Matt", "matt"))
        self.assertIsNotNone(datetime.fromisoformat(row["since"]).tzinfo)
        self.assertEqual(self.store.visibility(), view)
        self.assertEqual(self.store.visibility_cached(), view)
        audit = self.trail()[0]
        self.assertEqual((audit["actor"], audit["source"], audit["via"]), ("matt", "web", "home"))
        self.assertEqual(audit["rows"][0]["key"], {"owner": "home", "thing": "decks"})
        self.assertEqual(audit["rows"][0]["op"], "INSERT")

    def test_visibility_noops_write_nothing_and_off_deletes_only_its_switch(self):
        self.assertEqual(self.store.visibility_set("home", "decks", False, MATT, "Keep private"), {})
        self.assertEqual(self.trail(), [])
        first = self.store.visibility_set("home", "decks", True, MATT, "Make public")
        self.assertEqual(self.store.visibility_set("home", "decks", True, USER1, "Keep public"), first)
        self.assertEqual(len(self.trail()), 1)
        self.store.visibility_set("home", "games", True, USER1, "Make games public")
        self.store.visibility_set("shared", "accessories", True, USER1, "Make shared kit public")
        view = self.store.visibility_set("home", "decks", False, CLAUDE, "Make the home decks private")
        self.assertEqual(set(view), {("home", "games"), ("shared", "accessories")})
        self.assertEqual(self.store.visibility_cached(), view)
        audit = self.trail()[0]
        self.assertEqual((audit["actor"], audit["source"], audit["via"]), ("claude", "cli", None))
        self.assertEqual(audit["rows"][0]["op"], "DELETE")
        self.assertEqual(audit["rows"][0]["before"]["set_by_name"], "Matt")

    def test_visibility_inputs_are_strict_and_answers_are_independent_copies(self):
        for owner, thing, on in (("Home", "decks", True), ("", "decks", True), ("x" * 65, "decks", True),
                                 ("home", "tokens", True), ("home", "decks", 1), ("home", "decks", "on"),
                                 ("user2", "accessories", True), ("home", [], True)):
            with self.subTest(owner=owner, thing=thing, on=on), self.assertRaises(Invalid):
                self.store.visibility_set(owner, thing, on, MATT, "Bad switch")
        with self.assertRaises(ValueError):
            self.store.visibility_set("home", "decks", True, MATT, " ")
        self.assertEqual(self.trail(), [])
        view = self.store.visibility_set("home", "collection", True, MATT, "Make public")
        view["home", "collection"]["by"] = "Changed in caller"
        cached = self.store.visibility_cached()
        self.assertEqual(cached["home", "collection"]["by"], "Matt")
        cached.clear()
        self.assertIn(("home", "collection"), self.store.visibility())

    def test_visibility_outage_cache_fails_closed_after_one_minute(self):
        from decklab.lib.state.pg import CACHE_SECONDS
        now = [1000.0]
        self.store._clock = lambda: now[0]
        self.assertEqual(self.store.visibility_cached(), {})
        public = self.store.visibility_set("home", "decks", True, MATT, "Make public")
        now[0] += CACHE_SECONDS - 1
        self.assertEqual(self.store.visibility_cached(), public)
        now[0] += 1
        self.assertEqual(self.store.visibility_cached(), {})
        self.assertEqual(self.store.visibility(), public)
        self.assertEqual(self.store.visibility_cached(), public)

    def test_visibility_batches_commit_or_roll_back_the_rows_and_cache(self):
        first = self.store.visibility_set("home", "decks", True, MATT, "Make public")
        before = len(self.trail())
        with self.assertRaisesRegex(ValueError, "rollback"):
            with self.store.batch(USER1, "Test rollback"):
                self.store.visibility_set("home", "decks", False, USER1, "Make private")
                self.store.visibility_set("home", "games", True, USER1, "Make games public")
                raise ValueError("rollback")
        self.assertEqual(self.store.visibility(), first)
        self.assertEqual(self.store.visibility_cached(), first)
        self.assertEqual(len(self.trail()), before)
        with self.store.batch(USER1, "Change two switches"):
            self.store.visibility_set("home", "decks", False, USER1, "Make private")
            saved = self.store.visibility_set("home", "games", True, USER1, "Make games public")
        self.assertEqual(self.store.visibility_cached(), saved)
        self.assertEqual(self.store.visibility(), saved)
        self.assertEqual(len(self.trail()), before + 1)
        self.assertEqual(len(self.trail()[0]["rows"]), 2)

    # ------------------------------------------------------------------ play records

    def test_records_jsonb_would_change_are_invalid(self):
        for bad in (dict(game(ID_A), notes="a\x00b"), dict(game(ID_A), extra=1.5), dict(game(ID_A), extra=1e16),
                    dict(game(ID_A), extra=[{"x": -0.0}]), dict(game(ID_A), updated_by="Ma\ntt")):
            with self.subTest(bad=bad), self.assertRaises(Invalid):
                self.store.play_put("games", bad, None, MATT, "Save")
        self.assertIsNone(self.store.play_get("games", ID_A))
        self.assertEqual(self.store.play_put("games", dict(game(ID_A), extra=[10 ** 16, True, None]), None, MATT,
                                             "Save")["extra"], [10 ** 16, True, None])

    def test_a_play_record_round_trips_with_the_same_hash(self):
        from decklab.lib.api import play_records
        for record in (game(ID_A, notes="Ünïcode — notes ✓"), game(ID_C, created="2026-10-11T00:00:00+00:00"),
                       plan(ID_B)):
            with self.subTest(id=record["id"]):
                kind = record["kind"]
                self.assertIsNone(self.store.play_get(kind, record["id"]))
                saved = self.store.play_put(kind, record, None, MATT, "Save")
                self.assertEqual(saved, record)
                loaded = self.store.play_get(kind, record["id"])
                self.assertEqual(play_records._bytes(loaded), play_records._bytes(record))
                self.assertEqual(rules.record_sha(loaded), play_records._hash(play_records._bytes(record)))

    def test_play_conflicts_and_listing(self):
        first = self.store.play_put("games", game(ID_B), None, MATT, "Save")
        with self.assertRaisesRegex(Conflict, "changed or was removed"):
            self.store.play_put("games", game(ID_B, 2), None, MATT, "Save again as new")
        with self.assertRaises(Conflict):
            self.store.play_put("games", game(ID_B, 2), "0" * 64, MATT, "Save with a stale hash")
        with self.assertRaises(Conflict):
            self.store.play_put("games", game(ID_C), rules.record_sha(first), MATT, "Save a missing one")
        second = self.store.play_put("games", game(ID_B, 2, "edited"), rules.record_sha(first), MATT, "Edit")
        self.assertEqual(second["revision"], 2)
        self.store.play_put("games", game(ID_A), None, MATT, "Save another")
        self.assertEqual([r["id"] for r in self.store.play_list("games")], [ID_A, ID_B])
        self.assertEqual(self.store.play_list("sideboards"), [])
        for bad_kind in ("game", None):
            with self.assertRaises(Invalid):
                self.store.play_list(bad_kind)
        with self.assertRaises(Invalid):
            self.store.play_get("games", "nope")
        with self.assertRaises(Invalid):
            self.store.play_put("sideboards", game(ID_C), None, MATT, "Wrong kind")
        with self.assertRaises(Invalid):
            self.store.play_put("games", dict(game(ID_C), created_on="yesterday"), None, MATT, "Bad time")

    # ------------------------------------------------------------------ the audit trail

    def test_activity_records_who_from_where_and_why(self):
        self.store.wishlist_add("user1", entry("Plains", "sld", "1513"), USER1, "  Add Plains  ")
        self.store.wishlist_remove("user1", "Plains", CLAUDE, "Remove Plains", reason="bought it")
        self.store.wishlist_add("user1", entry("Forest"), MATT, "Add Forest", )
        newest, removed, added = self.trail()
        self.assertEqual({k: added[k] for k in ("actor", "source", "via", "message", "reason")},
                         {"actor": "user1", "source": "web", "via": "tunnel", "message": "Add Plains", "reason": None})
        self.assertEqual({k: removed[k] for k in ("actor", "source", "via", "reason")},
                         {"actor": "claude", "source": "cli", "via": None, "reason": "bought it"})
        self.assertEqual(newest["via"], "home")
        self.assertEqual(added["rows"], [{"table": "wishlist_entry", "op": "INSERT",
                                          "key": {"profile_id": "user1", "position": 0}, "before": None,
                                          "after": {"profile_id": "user1", "position": 0, "name": "Plains",
                                                    "set_code": "sld", "collector_number": "1513", "notes": "",
                                                    "source": ""}}])
        self.assertEqual(removed["rows"][0]["before"], added["rows"][0]["after"])
        self.assertIsNone(removed["rows"][0]["after"])
        self.assertTrue(newest["id"] > removed["id"] > added["id"])
        self.assertIsNotNone(datetime.fromisoformat(newest["at"]).tzinfo)

    def test_activity_pages_newest_first(self):
        for name in "ABCDE":
            self.store.wishlist_add("user1", entry(name), USER1, f"Add {name}")
        first = self.store.activity(limit=2)
        self.assertEqual([c["message"] for c in first["changes"]], ["Add E", "Add D"])
        second = self.store.activity(before=first["next"], limit=2)
        self.assertEqual([c["message"] for c in second["changes"]], ["Add C", "Add B"])
        third = self.store.activity(before=second["next"], limit=2)
        self.assertEqual([c["message"] for c in third["changes"]], ["Add A"])
        self.assertIsNone(third["next"])
        exact = self.store.activity(before=second["next"], limit=1)
        self.assertEqual(([c["message"] for c in exact["changes"]], exact["next"]), (["Add A"], None))
        for bad in ({"limit": 0}, {"limit": 101}, {"before": 0}, {"before": "5"}):
            with self.subTest(bad=bad), self.assertRaises(Invalid):
                self.store.activity(**bad)

    def test_activity_filters_through_visible(self):
        for name in "ABCDE":
            self.store.wishlist_add("user1" if name in "AC" else "matt", entry(name),
                                    USER1 if name in "AC" else MATT, f"Add {name}")

        def user1s(change):
            rows = [r for r in change["rows"] if r["key"]["profile_id"] == "user1"]
            return dict(change, rows=rows) if rows else None
        page = self.store.activity(limit=1, visible=user1s)
        self.assertEqual([c["message"] for c in page["changes"]], ["Add C"])
        rest = self.store.activity(before=page["next"], limit=5, visible=user1s)
        self.assertEqual(([c["message"] for c in rest["changes"]], rest["next"]), (["Add A"], None))

    def test_activity_examines_at_most_the_scan_cap(self):
        for name in "ABCDE":
            self.store.wishlist_add("matt", entry(name), MATT, f"Add {name}")
        with mock.patch.object(rules, "SCAN_CAP", 3):
            page = self.store.activity(limit=5, visible=lambda change: None)
        self.assertEqual(page["changes"], [])
        self.assertEqual(page["next"], self.trail()[2]["id"])

    def test_the_same_writes_give_the_same_activity_as_memory(self):
        reference = MemoryStore(mode=None)
        operations(reference)
        operations(self.store)
        self.assertEqual(comparable(self.store.activity(limit=100)), comparable(reference.activity(limit=100)))
        self.assertEqual(self.store.wishlist("user1"), reference.wishlist("user1"))
        self.assertEqual(self.store.settings("matt"), reference.settings("matt"))
        self.assertEqual(self.store.play_list("games"), reference.play_list("games"))

    def test_the_trail_ends_exactly_at_the_scan_cap(self):
        for name in "ABC":
            self.store.wishlist_add("matt", entry(name), MATT, f"Add {name}")
        with mock.patch.object(rules, "SCAN_CAP", 3):
            page = self.store.activity(limit=5, visible=lambda change: None)
        self.assertEqual(page, {"changes": [], "next": None})

    # ------------------------------------------------------------------ batches

    def test_a_batch_is_one_change_set(self):
        system = Actor("system", "System", None, "migration")
        with self.store.batch(system, "Import phase 2 files") as batch:
            self.assertIs(batch, self.store)
            self.store.wishlist_add("user1", entry("Plains"), system, "Add Plains")
            self.store.wishlist_add("user1", entry("plains"), system, "Add plains again")      # unchanged
            self.store.settings_put("matt", {"theme": "dark"}, system, "Theme")
            self.store.simulation_mode_set("admins", system, "Mode", by_name="Matt")
            self.store.play_put("games", game(ID_A), None, system, "Game")
            with self.assertRaises(Conflict):                   # refused alone; the batch goes on
                self.store.play_put("games", game(ID_A), None, system, "Game again")
            self.assertEqual(self.store.settings("matt"), {"theme": "dark"})   # its own writes
            with self.assertRaises(ValueError):
                with self.store.batch(system, "Nested"):
                    pass
        (change,) = self.trail()
        self.assertEqual({k: change[k] for k in ("actor", "source", "via", "message")},
                         {"actor": "system", "source": "migration", "via": None, "message": "Import phase 2 files"})
        self.assertEqual([r["table"] for r in change["rows"]],
                         ["wishlist_entry", "profile_setting", "simulation_mode", "play_record"])
        self.assertEqual(self.store.settings("matt"), {"theme": "dark"})
        self.assertEqual(self.store.simulation_mode()["by"], "Matt")

    def test_a_batch_that_raises_keeps_nothing(self):
        with self.assertRaises(RuntimeError):
            with self.store.batch(MATT, "All or nothing"):
                self.store.wishlist_add("user1", entry("Plains"), MATT, "Add")
                self.store.settings_put("matt", {"theme": "dark"}, MATT, "Theme")
                self.store.simulation_mode_set("paused", MATT, "Pause")
                raise RuntimeError("stop")
        self.assertEqual(self.store.wishlist("user1"), [])
        self.assertEqual(self.store.settings("matt"), {})
        self.assertIsNone(self.store.simulation_mode())
        self.assertEqual(self.trail(), [])
        with self.store.batch(MATT, "Nothing changes"):
            self.store.wishlist_remove("user1", "Plains", MATT, "Remove")
        self.assertEqual(self.trail(), [])

    def test_writes_need_an_actor_and_a_message(self):
        with self.assertRaises(ValueError):
            self.store.wishlist_add("user1", entry("Plains"), "user1", "Add")
        with self.assertRaises(ValueError):
            self.store.settings_put("matt", {"theme": "dark"}, MATT, "  ")
        self.assertEqual(self.trail(), [])


class MemoryStoreTests(StoreContract, unittest.TestCase):

    def setUp(self):
        self.store = MemoryStore(mode=None)

    def test_the_default_mode_is_everyone_with_nobody_named(self):
        self.assertEqual(MemoryStore().simulation_mode(), {"mode": "everyone", "by": None, "by_id": None, "since": None})

    def test_seeded_wishlists_write_no_change_set(self):
        self.store.seed_wishlist("user1", [entry("Plains"), entry("Forest", "fdn", "1")])
        self.assertEqual(self.store.wishlist("user1"), [entry("Plains"), entry("Forest", "fdn", "1")])
        self.assertEqual(self.trail(), [])
        with self.assertRaises(Invalid):
            self.store.seed_wishlist("user1", [entry("Plains"), entry("plains")])

    def test_down_makes_every_call_unavailable(self):
        self.store.down = True
        self.assertFalse(self.store.reachable())
        with self.assertRaises(Unavailable):
            self.store.wishlist("user1")
        with self.assertRaises(Unavailable):
            self.store.simulation_mode_set("everyone", MATT, "Set")
        with self.assertRaises(Unavailable):
            with self.store.batch(MATT, "Batch"):
                pass
        self.assertEqual(self.store.settings_cached("matt"), {})
        self.assertIsNone(self.store.simulation_mode_cached())


class PgStoreTests(StoreContract, db_support.DbTestCase):

    def setUp(self):
        from decklab.lib.state import pg
        db_support.reset(self.dbname)
        db_support.seed_membership(self.dbname)
        self.breaker = pg.Breaker()
        self.store = pg.PgStore(dbname=self.dbname, breaker=self.breaker)

    def test_an_unreachable_database_trips_the_breaker(self):
        from decklab.lib.state import pg
        down = pg.PgStore(dbname="decklab_tests_must_not_reach_this", breaker=self.breaker)
        with self.assertRaises(Unavailable):
            down.wishlist("user1")
        self.assertFalse(down.reachable())
        with mock.patch("decklab.db.conn.connect", side_effect=AssertionError("tried to connect")):
            with self.assertRaises(Unavailable):
                down.settings("matt")
        self.breaker.reset()
        self.assertTrue(down.reachable())

    def test_a_database_without_the_tables_needs_migrating(self):
        from decklab.lib.state import pg
        with mock.patch.object(pg, "_ENTRY_COLUMNS", "name, set_code, collector_number, notes, no_such_column"):
            with self.assertRaisesRegex(Unavailable, "decklab.db migrate"):
                self.store.wishlist("user1")

    def test_settings_and_mode_are_cached_until_the_breaker_trips(self):
        self.store.settings_put("matt", {"theme": "dark"}, MATT, "Set")
        self.store.simulation_mode_set("everyone", MATT, "Set")
        with mock.patch("decklab.db.conn.connect", side_effect=AssertionError("tried to connect")):
            self.assertEqual(self.store.settings("matt"), {"theme": "dark"})
            self.assertEqual(self.store.simulation_mode()["mode"], "everyone")
        self.breaker.trip("down for the test")
        with self.assertRaises(Unavailable):
            self.store.settings("matt")
        self.breaker.reset()
        self.assertEqual(self.store.settings("matt"), {"theme": "dark"})

    def test_a_write_by_another_process_shows_once_the_cache_is_a_minute_old(self):
        from decklab.lib.state import pg
        now = [1000.0]
        self.store._clock = lambda: now[0]
        self.store.settings_put("matt", {"theme": "dark"}, MATT, "Dark")
        self.store.simulation_mode_set("everyone", MATT, "Everyone")
        other = pg.PgStore(dbname=self.dbname, breaker=self.breaker)    # a command line, a test server
        other.settings_put("matt", {"theme": "light"}, MATT, "Light")
        other.simulation_mode_set("paused", MATT, "Paused")
        now[0] += pg.CACHE_SECONDS - 1
        self.assertEqual(self.store.settings("matt"), {"theme": "dark"})      # still cached
        self.assertEqual(self.store.simulation_mode()["mode"], "everyone")
        now[0] += 1
        self.assertEqual(self.store.settings("matt"), {"theme": "light"})
        self.assertEqual(self.store.simulation_mode()["mode"], "paused")
        self.assertEqual(self.store.settings_cached("matt"), {"theme": "light"})
        self.assertEqual(self.store.simulation_mode_cached()["mode"], "paused")
        # A stale value that can't be read again: Unavailable from the reader, and the cached
        # readers still answer with the last good value, never raising.
        now[0] += pg.CACHE_SECONDS
        from decklab.db import conn as db
        with mock.patch("decklab.db.conn.connect", side_effect=db.DbUnavailable("down for the test")):
            with self.assertRaises(Unavailable):
                self.store.settings("matt")
        self.assertEqual(self.store.settings_cached("matt"), {"theme": "light"})
        self.assertEqual(self.store.simulation_mode_cached()["mode"], "paused")

    def racing(self, write):
        """The store's _call wrapped so that the first database call (a read) does write()
        after reading, before its answer comes back: a write that committed mid-read."""
        real, raced = self.store._call, []

        def call(work):
            value = real(work)
            if not raced:
                raced.append(True)
                write()
            return value
        return mock.patch.object(self.store, "_call", call)

    def test_a_read_that_overlapped_a_write_never_caches_the_older_value(self):
        self.store.simulation_mode_set("everyone", MATT, "Everyone")
        self.store.settings_put("matt", {"theme": "dark"}, MATT, "Dark")
        self.store.clear_cache()
        with self.racing(lambda: self.store.simulation_mode_set("paused", MATT, "Pause")):
            self.assertEqual(self.store.simulation_mode()["mode"], "everyone")     # what the poll read
        with self.racing(lambda: self.store.settings_put("matt", {"theme": "light"}, MATT, "Light")):
            self.assertEqual(self.store.settings("matt"), {"theme": "dark"})
        self.assertEqual(self.store.simulation_mode()["mode"], "paused")
        self.assertEqual(self.store.settings("matt"), {"theme": "light"})
        with mock.patch("decklab.db.conn.connect", side_effect=AssertionError("tried to connect")):
            self.assertEqual(self.store.simulation_mode()["mode"], "paused")
            self.assertEqual(self.store.settings("matt"), {"theme": "light"})

    def test_concurrent_writes_leave_the_last_committed_value_cached(self):
        modes = ["admins", "everyone", "paused"] * 4
        threads = [threading.Thread(target=self.store.simulation_mode_set, args=(m, MATT, f"Set {m}")) for m in modes]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        cached = self.store.simulation_mode()["mode"]
        self.store.clear_cache()
        self.assertEqual(cached, self.store.simulation_mode()["mode"])

    def test_the_last_good_values_survive_a_trip(self):
        self.store.settings_put("matt", {"theme": "dark"}, MATT, "Set")
        self.store.simulation_mode_set("paused", MATT, "Pause")
        self.breaker.trip("down for the test")
        with mock.patch("decklab.db.conn.connect", side_effect=AssertionError("tried to connect")):
            with self.assertRaises(Unavailable):
                self.store.settings("matt")
            with self.assertRaises(Unavailable):
                self.store.simulation_mode()
            self.assertEqual(self.store.settings_cached("matt"), {"theme": "dark"})
            self.assertEqual(self.store.simulation_mode_cached()["mode"], "paused")
        self.store.clear_cache()
        self.assertEqual(self.store.settings_cached("matt"), {})
        self.assertIsNone(self.store.simulation_mode_cached())

    def test_only_a_lost_database_trips_the_breaker(self):
        import psycopg
        errors = psycopg.errors
        cases = ((errors.DeadlockDetected(), Conflict), (errors.SerializationFailure(), Conflict),
                 (errors.QueryCanceled(), Unavailable), (errors.LockNotAvailable(), Unavailable),
                 (psycopg.DataError("NUL"), Invalid), (errors.CheckViolation("check"), Invalid),
                 (errors.UniqueViolation(), Conflict), (errors.DiskFull(), Unavailable))
        for error, kind in cases:
            with self.subTest(error=type(error).__name__):
                mapped = self.store._mapped(psycopg, error)
                self.assertIsInstance(mapped, kind)
                self.assertTrue(self.store.reachable())
        self.assertNotIn("constraint", str(self.store._mapped(psycopg, errors.CheckViolation("violates check constraint"))))
        for error in (psycopg.OperationalError("server closed the connection"), errors.AdminShutdown(),
                      errors.ConnectionFailure(), errors.TooManyConnections()):
            with self.subTest(error=type(error).__name__):
                self.breaker.reset()
                self.assertIsInstance(self.store._mapped(psycopg, error), Unavailable)
                self.assertFalse(self.store.reachable())
        self.breaker.reset()

    def test_a_held_lock_times_out_without_tripping(self):
        from decklab.db import conn as db
        from decklab.lib.state import pg
        with db.connect("app", dbname=self.dbname) as holder:
            holder.execute("select pg_advisory_xact_lock(hashtext('settings:matt'))")
            with mock.patch.object(pg, "REQUEST_OPTIONS", "-c lock_timeout=200 -c statement_timeout=5000"):
                with self.assertRaisesRegex(Unavailable, "too long"):
                    self.store.settings_put("matt", {"theme": "dark"}, MATT, "Set")
            holder.rollback()
        self.assertTrue(self.store.reachable())
        self.assertEqual(self.store.settings("matt"), {})
        self.assertEqual(self.trail(), [])

    def test_the_breaker_logs_when_it_opens_and_closes(self):
        from decklab.lib.state import pg
        lines = []
        breaker = pg.Breaker(log=lines.append)
        breaker.trip("first")
        breaker.trip("second, while open")
        breaker.reset()
        breaker.reset()
        self.assertEqual(len(lines), 2)
        self.assertIn("first", lines[0])
        self.assertIn("reachable again", lines[1])

    def test_the_active_store_is_whichever_was_installed(self):
        with state.use(self.store) as active:
            self.assertIs(state.store(), active)
            self.assertTrue(state.reachable())


class StateModuleTests(unittest.TestCase):

    def test_use_nests_and_restores(self):
        outer, inner = MemoryStore(), MemoryStore()
        restore_outer = state.use(outer)
        try:
            with state.use(inner):
                self.assertIs(state.store(), inner)
            self.assertIs(state.store(), outer)
        finally:
            restore_outer()
            restore_outer()                     # twice is harmless

    def test_explicit_mode_refuses_without_a_store(self):
        with mock.patch.dict(os.environ, {state.EXPLICIT_ENV: "1"}), mock.patch.object(state, "_active", []):
            with self.assertRaises(RuntimeError):
                state.store()

    def test_reachable_follows_the_active_store(self):
        down = MemoryStore()
        down.down = True
        with state.use(down):
            self.assertFalse(state.reachable())

    def test_actors_are_checked(self):
        self.assertEqual(Actor("matt", "Matt").source, "web")
        for bad in (("", "Matt"), ("matt", ""), ("matt", "Matt", "office"), ("matt", "Matt", None, "phone")):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                Actor(*bad)

    def test_jsonb_time_trims_the_fraction_like_postgresql(self):
        when = datetime(2026, 10, 11, 1, 2, 3, 120000, tzinfo=timezone.utc)
        text = rules.jsonb_time(when)
        self.assertEqual(datetime.fromisoformat(text), when)
        self.assertIn(":03.12", text)
        self.assertNotIn(".120", text)
        self.assertNotIn(".", rules.jsonb_time(when.replace(microsecond=0)))

    def test_record_bytes_match_the_play_files(self):
        from decklab.lib.api import play_records
        record = game(ID_A, notes="Ünïcode")
        self.assertEqual(rules.record_bytes(record), play_records._bytes(record))


if __name__ == "__main__":
    unittest.main()
