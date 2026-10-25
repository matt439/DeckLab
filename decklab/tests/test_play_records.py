"""Real play records: snapshot integrity, review guards, plans, the record hash and the
state store they're kept in (the sandbox's MemoryStore; PlayPgStoreTests runs a save and an
edit through PostgreSQL)."""
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from decklab.lib import access, config, state
from decklab.lib.api import play_records as play
from decklab.lib.state import pg, rules
from decklab.tests import db_support
from decklab.tests.test_api import ApiTestCase, Sandbox
from decklab.tests.test_collection_edit import ROLES


DECK = """# Practice deck

- **Format:** Casual 60-card, 1v1
- **Played by:** either
- **Status:** building

## Decklist

```
Deck
4 Llanowar Elves (FDN) 227
4 Elvish Mystic
52 Forest

Sideboard
2 Pick Your Poison (MKM) 170
2 Sol Ring (ECC) 57
```
"""


def encoded(data):
    return json.dumps(data).encode()


def selector(snapshot):
    return {key: snapshot[key] for key in ("id", "version", "sha256")}


class PlayFixture:
    """The decks, payloads and two-step save the tests share; box is a Sandbox."""

    def write_decks(self):
        self.box.stack.enter_context(mock.patch.object(config, "REPO", self.box.root))
        self.box.stack.enter_context(mock.patch.object(play, "_play_today", return_value="2026-10-08"))
        self.deckfile = self.box.magic / "decks/casual/gruul-test.md"
        self.deckfile.write_text(DECK, encoding="utf-8")
        (self.deckfile.parent / "other.md").write_text(DECK.replace("Practice deck", "Other deck"), encoding="utf-8")

    def game(self):
        a = play._snapshot("casual/gruul-test", "target")
        b = play._snapshot("casual/other", "target")
        return {"profile": "matt", "id": None, "sha256": None, "preview": True,
                "date": "2026-10-08", "result": "a", "notes": "A real game entered by the player.",
                "sides": [{**selector(a), "player": "Matt", "mulligans": 1},
                          {**selector(b), "player": "User1", "mulligans": 0}]}

    def plan(self):
        game = self.game()
        return {"profile": "matt", "id": None, "sha256": None, "preview": True,
                "deck": {k: game["sides"][0][k] for k in ("id", "version", "sha256")},
                "opponent": {k: game["sides"][1][k] for k in ("id", "version", "sha256")},
                "out": [{"name": "Llanowar Elves", "qty": 2}],
                "in": [{"name": "Pick Your Poison", "qty": 2}], "notes": "For this matchup."}

    def save(self, data, function=play.save_game):
        checked = function(encoded(data))
        return function(encoded({**data, "id": checked["id"], "preview": False,
                                 "review_sha256": checked["review_sha256"]}))


class PlayRecordsTests(PlayFixture, ApiTestCase):
    def setUp(self):
        super().setUp()
        self.write_decks()

    def stored(self, kind="games"):
        return self.box.state.play_list(kind)

    def test_preview_never_writes_and_confirmation_is_required(self):
        payload = self.game()
        preview = play.save_game(encoded(payload))
        self.assertEqual(self.stored(), [])
        self.assertEqual(preview["record"]["sides"][0]["sections"]["Deck"][0]["name"], "Llanowar Elves")
        self.assertApiError(409, play.save_game, encoded({**payload, "preview": False}))
        self.assertApiError(409, play.save_game, encoded({**payload, "id": preview["id"], "preview": False,
            "result": "b", "review_sha256": preview["review_sha256"]}))
        self.assertEqual(self.box.state.changes(), [])

    def test_saved_game_has_durable_snapshots_without_inventory_edits(self):
        inventory = (self.box.magic / "collection.csv").read_bytes()
        original = self.deckfile.read_bytes()
        answer = self.save(self.game())
        record = answer["record"]
        self.assertEqual(self.box.state.play_get("games", record["id"]), record)
        self.assertEqual(record["revision"], 1)
        self.assertEqual(record["sides"][0]["mulligans"], 1)
        self.assertEqual(record["updated_by"], "Matt")
        self.assertNotIn("commit", answer)
        self.assertEqual((self.box.magic / "collection.csv").read_bytes(), inventory)
        self.assertEqual(self.deckfile.read_bytes(), original)

    def test_sha256_is_the_hash_of_the_record_as_its_file_was_written(self):
        answer = self.save(self.game())
        raw = (json.dumps(answer["record"], ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
        self.assertEqual(answer["sha256"], play._hash(raw))
        self.assertEqual(play._read("games", answer["record"]["id"]), (answer["record"], answer["sha256"]))
        overview = play.play_overview()
        self.assertEqual(overview["games"], [{"record": answer["record"], "sha256": answer["sha256"],
                                              "can": {"sides": [True, True], "result": True}}])
        self.assertEqual(answer["record"]["space"], "home")     # the space that recorded it (E10-S32)
        # Each list's deck says who plays it and how far it's got, for the quick record's starting decks.
        self.assertEqual(set(overview["decks"]), {item["id"] for item in overview["lists"]})
        self.assertTrue(all(set(about) == {"player", "status", "can_record"}
                            for about in overview["decks"].values()))

    def test_the_audit_trail_names_the_writer_the_listener_and_the_decks(self):
        game = self.save(self.game())
        with access.using({"profile": "matt", "email": "", "remote": True}):
            self.save(self.plan(), play.save_sideboard)
        first, second = self.box.state.changes()
        self.assertEqual((first["actor"], first["source"], first["via"], first["message"]),
                         ("matt", "web", "home", "Save game Practice deck vs Other deck"))
        self.assertEqual(first["rows"][0]["key"], {"kind": "games", "id": game["record"]["id"]})
        self.assertEqual(first["rows"][0]["after"]["deck_ids"], ["casual/gruul-test", "casual/other"])
        self.assertEqual((second["actor"], second["via"], second["message"]),
                         ("matt", "tunnel", "Save sideboard plan Practice deck vs Other deck"))

    def test_duplicate_confirmation_does_not_create_a_second_game(self):
        payload = self.game()
        checked = play.save_game(encoded(payload))
        confirmed = {**payload, "id": checked["id"], "preview": False, "review_sha256": checked["review_sha256"]}
        play.save_game(encoded(confirmed))
        self.assertApiError(409, play.save_game, encoded(confirmed))
        self.assertEqual(len(self.stored()), 1)

    def test_correction_retains_historical_lists_and_guards_record_hash(self):
        saved = self.save(self.game())
        record = saved["record"]
        self.deckfile.write_text(DECK.replace("52 Forest", "51 Forest"), encoding="utf-8")
        corrected = {"profile": "matt", "id": record["id"], "sha256": saved["sha256"], "preview": True,
                     **{k: record[k] for k in ("date", "result", "notes")},
                     "sides": [{**selector(side), "player": side["player"], "mulligans": side["mulligans"]}
                               for side in record["sides"]]}
        corrected["result"] = "b"
        second = self.save(corrected)
        self.assertEqual(second["record"]["revision"], 2)
        self.assertEqual(second["record"]["created_on"], record["created_on"])
        self.assertEqual(second["record"]["sides"], record["sides"])
        self.assertApiError(409, play.save_game, encoded(corrected), contains=rules.CHANGED_MESSAGE)

    def test_store_conflict_after_the_check_is_the_same_409(self):
        saved = self.save(self.game())
        payload = {**self.game(), "id": saved["record"]["id"], "sha256": saved["sha256"], "notes": "Correction"}
        preview = play.save_game(encoded(payload))

        def changed_meanwhile(kind, record, expected, actor, message):
            raise state.Conflict(rules.CHANGED_MESSAGE)
        with mock.patch.object(self.box.state, "play_put", changed_meanwhile):
            with self.assertRaises(play.ApiError) as caught:
                play.save_game(encoded({**payload, "preview": False, "review_sha256": preview["review_sha256"]}))
        self.assertEqual((caught.exception.status, str(caught.exception)), (409, rules.CHANGED_MESSAGE))
        self.assertEqual(self.box.state.play_get("games", saved["record"]["id"]), saved["record"])

    def test_deck_change_after_review_refuses_save(self):
        payload = self.game()
        preview = play.save_game(encoded(payload))
        self.deckfile.write_text(DECK.replace("52 Forest", "51 Forest"), encoding="utf-8")
        self.assertApiError(409, play.save_game, encoded({**payload, "id": preview["id"], "preview": False,
            "review_sha256": preview["review_sha256"]}))
        self.assertEqual(self.stored(), [])

    def test_bad_profile_dates_versions_names_and_fields_are_refused(self):
        for changes in ({"profile": "nobody"}, {"date": "2026-10-09"}, {"date": "yesterday"},
                        {"result": ""}, {"id": "../escape"}, {"preview": "yes"}, {"extra": 1}, {"retry": True}):
            with self.subTest(changes=changes):
                self.assertApiError(403 if changes.get("profile") else 400,
                                    play.save_game, encoded({**self.game(), **changes}))
        for key, value in (("version", "missing"), ("mulligans", -1), ("mulligans", True), ("player", "")):
            payload = self.game()
            payload["sides"][0][key] = value
            self.assertApiError(400, play.save_game, encoded(payload))
        payload = self.game()
        self.deckfile.write_text(DECK.replace("Llanowar Elves", "llanowar elves"), encoding="utf-8")
        self.assertApiError(400, play.save_game, encoded(payload))
        self.assertEqual(self.stored(), [])

    def test_sideboard_preserves_quantities_printings_and_deck_file(self):
        original = self.deckfile.read_bytes()
        saved = self.save(self.plan(), play.save_sideboard)
        plan = saved["record"]
        count = lambda section, name: sum(x["qty"] for x in plan["after"][section] if x["name"] == name)
        self.assertEqual(count("Deck", "Llanowar Elves"), 2)
        self.assertEqual(count("Sideboard", "Llanowar Elves"), 2)
        self.assertEqual(count("Deck", "Pick Your Poison"), 2)
        self.assertEqual(sum(x["qty"] for x in plan["after"]["Deck"]), 60)
        self.assertEqual(sum(x["qty"] for x in plan["after"]["Sideboard"]), 4)
        incoming = [x for x in plan["after"]["Deck"] if x["name"] == "Pick Your Poison"][0]
        self.assertEqual((incoming["set"], incoming["number"]), ("mkm", "170"))
        self.assertEqual(self.deckfile.read_bytes(), original)
        self.assertEqual(self.stored("sideboards"), [plan])

    def test_plan_presentation_does_not_change_the_record_hash_or_revision_token(self):
        payload = self.plan()
        saved = self.save(payload, play.save_sideboard)
        original = rules.record_bytes(saved["record"])
        changes = len(self.box.state.changes())
        entry = play.play_overview("casual/gruul-test")["sideboards"][0]
        self.assertEqual(set(entry), {"record", "sha256", "cards", "editable"})
        self.assertEqual(entry["sha256"], saved["sha256"])
        self.assertEqual(rules.record_bytes(entry["record"]), original)
        self.assertEqual(rules.record_sha(entry["record"]), saved["sha256"])
        self.assertEqual(entry["cards"]["out"][0]["card"]["img"], "/img/fdn/227/normal")
        entry["cards"]["out"][0]["qty"] = 99
        self.assertEqual(rules.record_bytes(self.stored("sideboards")[0]), original)
        self.assertEqual(len(self.box.state.changes()), changes)
        revised = self.save({**payload, "id": saved["record"]["id"], "sha256": entry["sha256"],
                             "notes": "Revised after viewing."}, play.save_sideboard)
        self.assertEqual(revised["record"]["revision"], 2)

    def test_stale_plan_pictures_keep_historical_printings_and_clip_each_source_line(self):
        mixed = DECK.replace("4 Llanowar Elves (FDN) 227",
                             "1 Llanowar Elves (FDN) 227 *F*\n3 Llanowar Elves (M19) 314")
        mixed = mixed.replace("2 Pick Your Poison (MKM) 170",
                              "1 Pick Your Poison (MKM) 170\n3 Pick Your Poison (MKM) 170 *F*")
        self.deckfile.write_text(mixed, encoding="utf-8")
        saved = self.save(self.plan(), play.save_sideboard)
        self.deckfile.write_text(DECK.replace("4 Llanowar Elves (FDN) 227", "4 Elvish Mystic")
                                .replace("2 Pick Your Poison (MKM) 170", "2 Sol Ring (ECC) 57"), encoding="utf-8")
        answer = play.play_overview("casual/gruul-test")
        current = next(s for s in answer["lists"] if s["id"] == "casual/gruul-test" and s["version"] == "target")
        self.assertNotEqual(current["sha256"], saved["record"]["deck"]["sha256"])
        entry = answer["sideboards"][0]
        outgoing, incoming = entry["cards"]["out"], entry["cards"]["in"]
        self.assertEqual([(r["qty"], r["set"], r["number"], r["finish"]) for r in outgoing],
                         [(1, "fdn", "227", "foil"), (1, "m19", "314", "nonfoil")])
        self.assertEqual([r["card"]["img"] for r in outgoing], ["/img/fdn/227/normal", "/img/m19/314/normal"])
        self.assertEqual([(r["qty"], r["finish"]) for r in incoming], [(1, "nonfoil"), (1, "foil")])
        self.assertTrue(all(r["card"]["img"] == "/img/mkm/170/normal" for r in incoming))
        self.assertEqual(entry["record"], saved["record"])
        self.assertEqual(entry["sha256"], saved["sha256"])

    def test_missing_card_data_keeps_the_plan_and_its_moves(self):
        saved = self.save(self.plan(), play.save_sideboard)
        for patch in (mock.patch.object(play.cards, "card", return_value=None),
                      mock.patch.object(play, "_line_json", side_effect=RuntimeError("index unavailable"))):
            with self.subTest(patch=patch), patch:
                answer = play.play_overview("casual/gruul-test")
            entry = answer["sideboards"][0]
            self.assertEqual(entry["record"], saved["record"])
            self.assertEqual(entry["sha256"], saved["sha256"])
            self.assertEqual([(r["name"], r["qty"], r["card"]) for r in entry["cards"]["out"]],
                             [("Llanowar Elves", 2, None)])
            self.assertTrue(answer["warnings"])
            self.assertFalse(any("record could not be shown" in warning for warning in answer["warnings"]))

    def test_a_damaged_plan_is_validated_before_its_pictures_are_built(self):
        saved = self.save(self.plan(), play.save_sideboard)
        record_id = saved["record"]["id"]
        stored = self.box.state._play[("sideboards", record_id)]["content"]
        stored["after"]["Deck"][0]["qty"] += 1
        with mock.patch.object(play, "_plan_cards") as enrich:
            answer = play.play_overview("casual/gruul-test")
        enrich.assert_not_called()
        self.assertEqual(answer["sideboards"], [])
        self.assertTrue(any(record_id in warning for warning in answer["warnings"]))

    def test_sideboard_refuses_unequal_nonexistent_and_oversubscribed_moves(self):
        for changes in ({"in": []}, {"out": [{"name": "Forest", "qty": 0}]},
                        {"in": [{"name": "Llanowar Elves", "qty": 2}]},
                        {"in": [{"name": "Pick Your Poison", "qty": 3}]},
                        {"in": [{"name": "Pick Your Poison", "qty": 2}] * 2}):
            with self.subTest(changes=changes):
                self.assertApiError(400, play.save_sideboard, encoded({**self.plan(), **changes}))
        self.assertEqual(self.stored("sideboards"), [])

    def test_game_can_record_actual_sideboarded_list(self):
        saved = self.save(self.plan(), play.save_sideboard)
        payload = self.game()
        payload["sides"][0].update(plan_id=saved["record"]["id"], plan_sha256=saved["sha256"])
        game = self.save(payload)
        self.assertEqual(game["record"]["sides"][0]["sections"], saved["record"]["after"])
        self.assertNotEqual(game["record"]["sides"][0]["sha256"], saved["record"]["deck"]["sha256"])
        self.assertEqual(game["record"]["sides"][0]["base_sha256"], saved["record"]["deck"]["sha256"])
        # Correcting a result retains the sideboarded snapshot even after a deck edit.
        self.deckfile.write_text(DECK.replace("52 Forest", "51 Forest"), encoding="utf-8")
        correction = {**payload, "id": game["record"]["id"], "sha256": game["sha256"], "result": "draw"}
        for i, side in enumerate(game["record"]["sides"]):
            correction["sides"][i].update(selector(side))
        corrected = self.save(correction)
        self.assertEqual(corrected["record"]["sides"][0]["sections"], saved["record"]["after"])

    def test_game_refuses_plan_for_wrong_opponent_or_stale_base(self):
        saved = self.save(self.plan(), play.save_sideboard)
        payload = self.game()
        payload["sides"][0].update(plan_id=saved["record"]["id"], plan_sha256=saved["sha256"])
        payload["sides"][1].update(selector(play._snapshot("casual/gruul-test", "target")))
        self.assertApiError(400, play.save_game, encoded(payload))
        payload = self.game()
        payload["sides"][0].update(plan_id=saved["record"]["id"], plan_sha256="a" * 64)
        self.assertApiError(409, play.save_game, encoded(payload))

    def test_two_devices_cannot_overwrite_the_same_record_revision(self):
        saved = self.save(self.game())
        payload = {**self.game(), "id": saved["record"]["id"], "sha256": saved["sha256"], "notes": "Correction"}
        preview = play.save_game(encoded(payload))
        confirmed = encoded({**payload, "preview": False, "review_sha256": preview["review_sha256"]})
        gate = threading.Barrier(2)
        def save_once(_):
            gate.wait(timeout=5)
            try:
                return play.save_game(confirmed)["record"]["revision"]
            except play.ApiError as exc:
                return exc.status
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(save_once, range(2)))
        self.assertEqual(sorted(results), [2, 409])

    def test_games_of_the_same_day_are_newest_recorded_first(self):
        first = self.save({**self.game(), "notes": "first"})["record"]
        second = self.save({**self.game(), "notes": "second"})["record"]
        self.assertLess(first["created_on"], second["created_on"])
        store = self.box.state
        real = store.play_list
        for order in (lambda rows: rows, lambda rows: list(reversed(rows))):
            with self.subTest(order=order):
                with mock.patch.object(store, "play_list", lambda kind: order(real(kind))):
                    games = play.play_overview()["games"]
                self.assertEqual([g["record"]["notes"] for g in games], ["second", "first"])

    def test_corrupt_snapshot_or_sideboard_result_is_never_accepted(self):
        saved = self.save(self.game())
        record_id = saved["record"]["id"]
        self.box.state._play[("games", record_id)]["content"]["sides"][0]["sections"]["Deck"][0]["qty"] += 1
        self.assertApiError(500, play._read, "games", record_id)
        # Never built on, and the overview reports it instead of showing it.
        damaged = rules.record_sha(self.box.state.play_get("games", record_id))
        self.assertApiError(500, play.save_game, encoded({**self.game(), "id": record_id, "sha256": damaged}))
        answer = play.play_overview()
        self.assertTrue(answer["warnings"])
        self.assertEqual(answer["games"], [])
        saved = self.save(self.plan(), play.save_sideboard)
        record_id = saved["record"]["id"]
        self.box.state._play[("sideboards", record_id)]["content"]["after"]["Deck"][0]["qty"] += 1
        self.assertApiError(500, play._read, "sideboards", record_id)

    def test_database_down_is_503_before_the_write_lock(self):
        saved = self.save(self.game())
        payload = {**self.game(), "id": saved["record"]["id"], "sha256": saved["sha256"]}
        self.box.state.down = True
        lock = mock.MagicMock()
        with mock.patch.object(play.saving, "_save_lock", lock):
            with self.assertRaises(play.ApiError) as caught:
                play.save_game(encoded(payload))
        self.assertEqual((caught.exception.status, caught.exception.extra), (503, {"reason": "database"}))
        lock.__enter__.assert_not_called()
        # The overview answers 503 before it snapshots any deck.
        with mock.patch.object(play.decks, "list_decks") as list_decks:
            with self.assertRaises(play.ApiError) as caught:
                play.play_overview()
        self.assertEqual(caught.exception.status, 503)
        list_decks.assert_not_called()


class MixedFixture(PlayFixture):
    """Home's decks, User2's and User3's, and games and plans naming two spaces."""

    SEED_TIME = "2026-10-08T01:00:00+00:00"

    def setUp(self):
        super().setUp()
        self.write_decks()
        (self.box.root / "config.json").write_text(json.dumps(ROLES), encoding="utf-8")
        person = DECK.replace("- **Played by:** either\n", "")
        for space, slug, title in (("user2", "r-elves", "User2 Elves"), ("user3", "m-elves", "User3 Elves")):
            path = self.box.magic / "people" / space / "decks" / "casual" / f"{slug}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(person.replace("Practice deck", title), encoding="utf-8")
        self.home = self.save_game("casual/gruul-test", "casual/other")
        # Games and plans naming decks of two spaces can't be recorded through the page by anyone
        # who may not see both decks (E10-S32), so they go straight into the store.
        self.mixed = self.stored_game("user2/casual/r-elves", "casual/gruul-test", "home")
        self.members_game = self.stored_game("user2/casual/r-elves", "user3/casual/m-elves", "user2")
        self.home_plan = self.save_plan("casual/gruul-test", "casual/other")
        self.members_plan = self.stored_plan("user3/casual/m-elves", "user2/casual/r-elves")
        self.user2_plan = self.stored_plan("user2/casual/r-elves", "casual/gruul-test")

    @staticmethod
    def recorder(deck_id):
        """Who records a game or plan of this deck: someone of its own space (E10-S29: Matt, an admin,
        records only games with a home deck)."""
        space = deck_id.split("/")[0]
        return space if space in ("user2", "user3") else "matt"

    def save_game(self, a, b):
        payload = {**self.game(), "profile": self.recorder(a)}
        for side, deck_id in zip(payload["sides"], (a, b)):
            side.update(selector(play._snapshot(deck_id, "target")))
        return self.save(payload)["record"]["id"]

    def save_plan(self, deck_id, opponent):
        payload = {**self.plan(), "profile": self.recorder(deck_id)}
        payload["deck"] = selector(play._snapshot(deck_id, "target"))
        payload["opponent"] = selector(play._snapshot(opponent, "target"))
        return self.save(payload, play.save_sideboard)["record"]["id"]

    def put(self, kind, content):
        record_id = uuid.uuid4().hex
        record = {"version": 1, "id": record_id, "kind": kind, "revision": 1, "created_on": self.SEED_TIME,
                  "updated_on": self.SEED_TIME, "updated_by": "Matt", **content}
        self.box.state.play_put(kind, record, None, state.Actor("test", "a test"), "Seed a record")
        return record_id

    def stored_game(self, a, b, space=None, notes="A private note."):
        sides = [{**play._snapshot(deck_id, "target"), "player": player, "mulligans": mulligans}
                 for deck_id, player, mulligans in ((a, "User2", 1), (b, "Matt", 0))]
        return self.put("games", {"date": "2026-10-08", "result": "a", "notes": notes, "sides": sides,
                                  **({"space": space} if space else {})})

    def stored_plan(self, deck_id, opponent):
        deck, other = play._snapshot(deck_id, "target"), play._snapshot(opponent, "target")
        return self.put("sideboards", {"deck": deck, "opponent": other, "notes": "For this matchup.",
                                       **play._plan_moves(deck, [{"name": "Llanowar Elves", "qty": 2}],
                                                          [{"name": "Pick Your Poison", "qty": 2}])})

    def seen(self, deck_id=None):
        answer = play.play_overview(deck_id)
        return ({e["record"]["id"] for e in answer["games"]}, {e["record"]["id"] for e in answer["sideboards"]},
                answer)


class PlayViewerTests(MixedFixture, ApiTestCase):
    """GET /api/play answers for its viewer (permissions.sees_play_record): the household's games
    and plans stay home's, each member sees only the games with one of their own decks, and a
    plan only its deck's space (E10-S32)."""

    def test_a_member_sees_only_the_games_and_plans_of_their_own_decks(self):
        tunnel = {"profile": "user2", "email": "", "remote": True}
        for where in (lambda: access.viewing("user2"), lambda: access.using(tunnel)):
            with where():
                games, plans, answer = self.seen()
            self.assertEqual(games, {self.mixed, self.members_game})
            # A plan is its deck's space's only: User3's against User2's deck isn't his (E10-S32).
            self.assertEqual(plans, {self.user2_plan})
            # Only his own space's decks (E10-S30): no home deck's list, nor User3's, nor a warning
            # naming one.
            self.assertEqual(set(answer["decks"]), {"user2/casual/r-elves"})
            self.assertEqual({item["id"] for item in answer["lists"]}, {"user2/casual/r-elves"})
            self.assertNotIn("Gruul", json.dumps(answer["warnings"]))
        with access.viewing("user3"):
            self.assertEqual(self.seen()[:2], ({self.members_game}, {self.members_plan}))
            # A deck filter doesn't reach past the rule.
            self.assertEqual(self.seen("casual/gruul-test")[:2], (set(), set()))
        with access.viewing("user2"):
            # Nor does it tell which hidden deck a game was against.
            self.assertEqual(self.seen("casual/gruul-test")[:2], (set(), set()))
            self.assertEqual(self.seen("user2/casual/r-elves")[:2], ({self.mixed, self.members_game}, {self.user2_plan}))

    def test_user1_sees_every_game_with_a_home_deck(self):
        for where in (lambda: access.viewing("user1"),
                      lambda: access.using({"profile": "user1", "email": "", "remote": True})):
            with where():
                self.assertEqual(self.seen()[:2], ({self.home, self.mixed}, {self.home_plan}))

    def test_visible_plans_and_current_decks_report_actual_recording_permissions(self):
        for where in (lambda: access.viewing("user1"),
                      lambda: access.using({"profile": "user1", "email": "", "remote": True})):
            with where():
                answer = play.play_overview()
            self.assertFalse(answer["sideboards"][0]["editable"])
            self.assertFalse(answer["decks"]["casual/gruul-test"]["can_record"])
            self.assertFalse(answer["decks"]["casual/other"]["can_record"])
        # Permission for either deck makes the pair writable; seeing home's plans alone does not.
        other = self.deckfile.parent / "other.md"
        other.write_text(DECK.replace("Practice deck", "Other deck").replace("Played by:** either", "Played by:** wife"),
                         encoding="utf-8")
        with access.viewing("user1"):
            answer = play.play_overview()
        self.assertFalse(answer["decks"]["casual/gruul-test"]["can_record"])
        self.assertTrue(answer["decks"]["casual/other"]["can_record"])
        self.assertTrue(answer["sideboards"][0]["editable"])
        with access.viewing("user2"):
            answer = play.play_overview()
        self.assertTrue(answer["decks"]["user2/casual/r-elves"]["can_record"])
        # User3's and home's decks aren't his to see (E10-S30), so they aren't offered at all.
        self.assertNotIn("user3/casual/m-elves", answer["decks"])
        self.assertNotIn("casual/other", answer["decks"])
        self.assertEqual([e["record"]["id"] for e in answer["sideboards"]], [self.user2_plan])
        self.assertTrue(answer["sideboards"][0]["editable"])

    def test_plan_pictures_are_built_only_after_viewer_and_deck_filters(self):
        with mock.patch.object(play, "_plan_cards", wraps=play._plan_cards) as enrich:
            with access.viewing("user1"):
                answer = play.play_overview()
            self.assertEqual([call.args[0]["id"] for call in enrich.call_args_list], [self.home_plan])
            self.assertEqual([e["record"]["id"] for e in answer["sideboards"]], [self.home_plan])
            enrich.reset_mock()
            with access.viewing("user2"):
                answer = play.play_overview("casual/gruul-test")
            enrich.assert_not_called()
            self.assertEqual(answer["sideboards"], [])
            self.assertEqual(answer["warnings"], [])

    def test_a_script_sees_every_game_and_an_admin_only_his_spaces(self):
        everything = ({self.home, self.mixed, self.members_game},
                      {self.home_plan, self.members_plan, self.user2_plan})
        with access.viewing(None):
            games, plans, answer = self.seen()
            self.assertEqual((games, plans), everything)
            # A script is sent every record as stored.
            self.assertEqual(next(e for e in answer["games"] if e["record"]["id"] == self.mixed)["record"],
                             self.box.state.play_get("games", self.mixed))
        # E10-S29: the admin role opens no other space's games, at home as through the tunnel.
        homes = ({self.home, self.mixed}, {self.home_plan})
        for where in (lambda: access.viewing("matt"),
                      lambda: access.using({"profile": "matt", "email": "", "remote": True})):
            with where():
                self.assertEqual(self.seen()[:2], homes)

    def test_a_login_not_set_up_is_refused(self):
        with access.using({"profile": None, "email": "someone@example.com", "remote": True}):
            self.assertApiError(403, play.play_overview)

    def test_a_damaged_record_is_warned_about_only_to_those_who_may_see_it(self):
        self.box.state._play[("games", self.members_game)]["content"]["sides"][0]["sections"]["Deck"][0]["qty"] += 1
        for viewer, warned in (("user1", False), ("user2", True), ("matt", False)):      # E10-S29
            with self.subTest(viewer=viewer), access.viewing(viewer):
                games, _, answer = self.seen()
                self.assertNotIn(self.members_game, games)
                self.assertEqual(bool(answer["warnings"]), warned, answer["warnings"])
        # One whose decks can't be read at all: only for a script, which sees every record.
        self.box.state._play[("games", self.members_game)]["content"]["sides"] = None
        for viewer, warned in (("user1", False), ("user2", False), ("matt", False), (None, True)):
            with self.subTest(viewer=viewer), access.viewing(viewer):
                self.assertEqual(bool(self.seen()[2]["warnings"]), warned)


class PlayMemberRulesTests(MixedFixture, ApiTestCase):
    """Decision G (E10-S32): in a record naming decks of two spaces, each viewer reads the other
    space's side by its space only, each side's space changes only its own side, the date, result
    and notes stay with the space that recorded it, a plan is its deck's space's, and no body
    names a deck its writer may not see."""

    def entry(self, kind, record_id):
        answer = play.play_overview()
        return next(e for e in answer[kind] if e["record"]["id"] == record_id)

    def body(self, entry, profile, **changes):
        """An edit of a game exactly as the page sends it back from what it was shown."""
        record = entry["record"]
        sides = []
        for side in record["sides"]:
            if side.get("hidden"):
                sides.append({"hidden": True})
            else:
                sides.append({**selector(side), "player": side["player"], "mulligans": side["mulligans"]})
        return {"profile": profile, "id": record["id"], "sha256": entry["sha256"], "preview": True,
                **{key: record[key] for key in ("date", "result", "notes")}, "sides": sides, **changes}

    def test_the_other_space_s_side_is_anonymised_with_no_list(self):
        with access.viewing("user2"):
            entry = self.entry("games", self.mixed)
        words = json.dumps(entry)
        for leak in ("Practice deck", "gruul-test", "A private note.", '"space"'):
            self.assertNotIn(leak, words)
        self.assertEqual(entry["record"]["sides"][1], {"hidden": True, "title": "one of the home decks",
                                                       "player": "Matt", "mulligans": 0})
        self.assertEqual((entry["record"]["notes"], entry["record"]["updated_by"]), ("", "someone"))
        self.assertEqual(entry["can"], {"sides": [True, False], "result": False})
        # The same game to home: User2's side by his space's name, home's notes kept.
        with access.viewing("matt"):
            entry = self.entry("games", self.mixed)
        self.assertEqual(entry["record"]["sides"][0]["title"], "one of User2's decks")
        self.assertNotIn("r-elves", json.dumps(entry))
        self.assertEqual(entry["record"]["notes"], "A private note.")
        self.assertEqual(entry["can"], {"sides": [False, True], "result": True})

    def test_a_member_changes_only_his_own_side(self):
        with access.viewing("user2"):
            entry = self.entry("games", self.mixed)
            body = self.body(entry, "user2")
            body["sides"][0]["mulligans"] = 3
            preview = play.save_game(encoded(body))
            self.assertNotIn("Practice deck", json.dumps(preview))
            saved = play.save_game(encoded({**body, "preview": False, "review_sha256": preview["review_sha256"]}))
            self.assertNotIn("Practice deck", json.dumps(saved))
            self.assertNotIn("A private note.", json.dumps(saved))
            stored = self.box.state.play_get("games", self.mixed)
            self.assertEqual(stored["sides"][0]["mulligans"], 3)
            self.assertEqual((stored["sides"][1]["title"], stored["notes"], stored["space"]),
                             ("Practice deck", "A private note.", "home"))
            entry = self.entry("games", self.mixed)
            # The result, the date and the notes are home's: a body changing them is refused.
            for change in ({"result": "b"}, {"date": "2026-10-07"}, {"notes": "Mine now."}):
                with self.subTest(change=change):
                    self.assertApiError(403, play.save_game, encoded(self.body(entry, "user2", **change)),
                                        contains=play.RESULT_MESSAGE)
            # The hidden side can't be changed, nor named outright.
            body = self.body(entry, "user2")
            body["sides"][1]["mulligans"] = 2
            self.assertApiError(403, play.save_game, encoded(body), contains=play.SIDE_MESSAGE)
            stored = self.box.state.play_get("games", self.mixed)["sides"][1]
            body["sides"][1] = {**selector(stored), "player": "Matt", "mulligans": 0}
            self.assertApiError(404, play.save_game, encoded(body), contains="No deck 'casual/gruul-test'")
            # Nor replaced by one of his own decks.
            body["sides"][1] = {**selector(play._snapshot("user2/casual/r-elves", "target")),
                                "player": "Matt", "mulligans": 0}
            self.assertApiError(403, play.save_game, encoded(body), contains=play.SIDE_MESSAGE)

    def test_the_recording_space_keeps_the_result_but_not_the_other_side(self):
        with access.viewing("matt"):
            entry = self.entry("games", self.mixed)
            saved = self.save(self.body(entry, "matt", result="draw", notes="Revised."))
            self.assertEqual((saved["record"]["result"], saved["record"]["notes"]), ("draw", "Revised."))
            self.assertEqual(saved["record"]["sides"][0]["title"], "one of User2's decks")
            entry = self.entry("games", self.mixed)
            body = self.body(entry, "matt")
            body["sides"][0]["player"] = "Someone else"
            self.assertApiError(403, play.save_game, encoded(body), contains=play.SIDE_MESSAGE)
        stored = self.box.state.play_get("games", self.mixed)
        self.assertEqual((stored["sides"][0]["player"], stored["sides"][0]["id"]), ("User2", "user2/casual/r-elves"))

    def test_a_game_saved_before_the_rule_is_home_s_to_change(self):
        older = self.stored_game("user2/casual/r-elves", "casual/gruul-test")     # no "space"
        with access.viewing("user2"):
            entry = self.entry("games", older)
            self.assertEqual(entry["can"], {"sides": [True, False], "result": False})
            self.assertApiError(403, play.save_game, encoded(self.body(entry, "user2", result="b")))
        with access.viewing("matt"):
            self.assertTrue(self.entry("games", older)["can"]["result"])

    def test_a_record_the_writer_may_not_see_is_missing_even_with_a_stale_sha(self):
        with access.viewing(None):
            sha = next(e["sha256"] for e in play.play_overview()["games"] if e["record"]["id"] == self.home)
        with access.viewing("user1"):
            home = self.entry("games", self.home)
        for profile, record_id in (("user2", self.home), ("user3", self.mixed), ("matt", self.members_game)):
            for given in (sha, "0" * 64, None):
                with self.subTest(profile=profile, sha=given), access.viewing(profile):
                    body = {**self.body(home, profile), "id": record_id, "sha256": given}
                    self.assertApiError(404, play.save_game, encoded(body), contains="No play record")
        # A record id nobody has saved, given a sha256, is the same 404.
        with access.viewing("user2"):
            self.assertApiError(404, play.save_game, encoded({**self.body(home, "user2"), "id": "f" * 32}),
                                contains="No play record")

    def test_a_new_game_needs_both_decks_visible(self):
        with access.viewing(None):
            home_list = play._snapshot("casual/gruul-test", "target")
            user3_list = play._snapshot("user3/casual/m-elves", "target")
        mine = play._snapshot("user2/casual/r-elves", "target")
        for other in (home_list, user3_list):
            payload = {**self.game(), "profile": "user2"}
            with self.subTest(other=other["id"]), access.viewing("user2"):
                payload["sides"][0].update(selector(mine))
                payload["sides"][1].update(selector(other))
                self.assertApiError(404, play.save_game, encoded(payload), contains=f"No deck {other['id']!r}")

    def test_a_plan_is_its_deck_s_space_s_alone(self):
        with access.viewing("user2"):
            entry = self.entry("sideboards", self.user2_plan)
            self.assertEqual(entry["record"]["opponent"], {"hidden": True, "title": "one of the home decks"})
            self.assertNotIn("gruul-test", json.dumps(entry))
            # Revised with its hidden opponent sent back as shown.
            body = {"profile": "user2", "id": self.user2_plan, "sha256": entry["sha256"], "preview": True,
                    "deck": selector(entry["record"]["deck"]), "opponent": {"hidden": True},
                    "out": [{"name": "Llanowar Elves", "qty": 1}], "in": [{"name": "Pick Your Poison", "qty": 1}],
                    "notes": "Fewer."}
            saved = self.save(body, play.save_sideboard)
            self.assertNotIn("gruul-test", json.dumps(saved))
            self.assertEqual(self.box.state.play_get("sideboards", self.user2_plan)["opponent"]["id"],
                             "casual/gruul-test")
            # A new plan against a deck he may not see, or of a deck that isn't his.
            with access.viewing(None):
                home_list = play._snapshot("casual/gruul-test", "target")
            fresh = {**body, "id": None, "sha256": None, "opponent": selector(home_list)}
            self.assertApiError(404, play.save_sideboard, encoded(fresh), contains="No deck 'casual/gruul-test'")
            fresh = {**fresh, "deck": selector(home_list), "opponent": selector(entry["record"]["deck"])}
            self.assertApiError(404, play.save_sideboard, encoded(fresh), contains="No deck 'casual/gruul-test'")
        # Home doesn't see User2's plan against its deck, nor may revise it.
        with access.viewing("matt"):
            self.assertNotIn(self.user2_plan, self.seen()[1])
            body = {**body, "profile": "matt", "sha256": None}
            self.assertApiError(404, play.save_sideboard, encoded(body), contains="No play record")

    def test_a_game_s_plan_of_the_hidden_side_stays_out_of_sight(self):
        # Matt's game against User2's deck with home's plan applied: User2 sees neither the plan nor the list.
        with access.viewing(None):
            plan = next(e for e in play.play_overview()["sideboards"] if e["record"]["id"] == self.home_plan)
        game = self.box.state.play_get("games", self.mixed)
        content = {key: game[key] for key in ("date", "result", "notes", "sides", "space")}
        side = content["sides"][1]
        side.update(base_sha256=side["sha256"], sections=plan["record"]["after"], plan_id=self.home_plan,
                    plan_sha256=plan["sha256"])
        side["sha256"] = play._hash(play._bytes({k: side[k] for k in ("id", "version", "sections")}))
        record_id = self.put("games", content)
        with access.viewing("user2"):
            entry = self.entry("games", record_id)
        self.assertEqual(set(entry["record"]["sides"][1]), {"hidden", "title", "player", "mulligans"})
        self.assertNotIn(self.home_plan, json.dumps(entry))


class PlayPgStoreTests(PlayFixture, db_support.DbTestCase):
    """A game and a sideboard plan saved through the API into PostgreSQL, then each edited with
    the sha the save returned: the hash must survive the round trip through jsonb, or every
    edit would be refused as changed."""

    def setUp(self):
        db_support.reset(self.dbname)
        db_support.seed_membership(self.dbname)
        self.box = Sandbox().start()
        self.addCleanup(self.box.stop)
        self.store = pg.PgStore(dbname=self.dbname, breaker=pg.Breaker())
        self.box.stack.callback(state.use(self.store))
        self.write_decks()

    def test_save_and_edit_a_game_and_a_sideboard_plan(self):
        plan = self.save({**self.plan(), "notes": "Bring in removal — für Gandalf."}, play.save_sideboard)
        self.assertEqual(self.store.play_get("sideboards", plan["record"]["id"]), plan["record"])
        revised = self.save({**self.plan(), "id": plan["record"]["id"], "sha256": plan["sha256"],
                             "notes": "Revised."}, play.save_sideboard)
        self.assertEqual(revised["record"]["revision"], 2)

        payload = self.game()
        payload["sides"][0].update(plan_id=revised["record"]["id"], plan_sha256=revised["sha256"])
        game = self.save(payload)
        stored = self.store.play_get("games", game["record"]["id"])
        self.assertEqual(stored, game["record"])
        self.assertEqual(rules.record_sha(stored), game["sha256"])
        corrected = {**payload, "id": game["record"]["id"], "sha256": game["sha256"], "result": "draw"}
        for i, side in enumerate(game["record"]["sides"]):
            corrected["sides"][i].update(selector(side))
        second = self.save(corrected)
        self.assertEqual((second["record"]["revision"], second["record"]["result"]), (2, "draw"))
        with self.assertRaises(play.ApiError) as caught:
            play.save_game(encoded(corrected))
        self.assertEqual(caught.exception.status, 409)
        overview = play.play_overview()
        self.assertEqual([e["sha256"] for e in overview["games"]], [second["sha256"]])
        self.assertEqual([e["sha256"] for e in overview["sideboards"]], [revised["sha256"]])
        with self.connect("ro") as c:
            rows = c.execute("select s.actor, s.source, s.via, s.message from audit.change_set s "
                             "order by s.id").fetchall()
        self.assertEqual(rows, [("matt", "web", "home", "Save sideboard plan Practice deck vs Other deck")] * 2
                         + [("matt", "web", "home", "Save game Practice deck vs Other deck")] * 2)
