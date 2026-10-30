"""Tests for decklab.lib.api.collection_edit: single-card edits and CSV imports
of a space's collection.csv (the Collection page), and GET /api/printings.

Each test runs in test_api's Sandbox with a config.json that has roles and
one person space (user2), so the person's files under magic/people/user2/
stay in the sandbox. Each write's message, actor, reason and extra lines are
recorded (last_write(), reason(), extra()). config.REPO points there too, so the inventory lock
and revision are the sandbox's. Cards resolve against the fixture card index.

Run from the repo root: python scripts/test_fixtures.py decklab.tests.test_collection_edit
"""
import hashlib
import json
from unittest import mock

from decklab.lib import access, config, inventory
from decklab.lib.api import collection, collection_edit as ce
from decklab.lib.inventory.files import FileInventory
from decklab.tests.test_api import ApiTestCase, _write

ROLES = {"profiles": [
    {"id": "matt", "name": "Matt", "plays_as": "user", "role": "admin", "space": "home"},
    {"id": "user1", "name": "User1", "plays_as": "wife", "role": "member", "space": "home"},
    {"id": "user2", "name": "User2", "role": "member", "space": "user2"},
    {"id": "user3", "name": "User3", "role": "member", "space": "user3"},
]}

HEADER = "name,set,collector_number,finish,quantity,condition,language,notes\n"
USER2 = HEADER + "Llanowar Elves,fdn,227,nonfoil,2,NM,en,\n"

MANABOX = (
    "Name,Set code,Set name,Collector number,Foil,Rarity,Quantity,ManaBox ID,Scryfall ID,Purchase price,"
    "Misprint,Altered,Condition,Language,Purchase price currency\n"
    "Llanowar Elves,FDN,Foundations,227,foil,common,2,11,x,0.10,false,false,near_mint,en,USD\n"
    "Llanowar Elves,FDN,Foundations,227,foil,common,1,11,x,0.10,false,false,near_mint,ja,USD\n"
    "Forest,FDN,Foundations,280,normal,common,10,12,y,0.05,false,false,near_mint,en,USD\n"
    "Sol Ring,ECC,Edge of Eternities Commander,57,normal,uncommon,1,13,z,1.00,false,false,light_played,ja,USD\n"
    "Nonsense Card,XXX,Nowhere,1,normal,common,1,14,w,0,false,false,near_mint,en,USD\n")
MOXFIELD = (
    '"Count","Tradelist Count","Name","Edition","Condition","Language","Foil","Tags","Last Modified",'
    '"Collector Number","Alter","Proxy","Purchase Price"\n'
    '"1","0","Black Lotus","lea","Near Mint","English","","","2026-10-01 10:00:00.000000","232","False","False",""\n'
    '"2","0","Pick Your Poison","mkm","Heavily Played","German","foil","","2026-10-01 10:00:00.000000","170",'
    '"False","False",""\n')
DECKBOX = (
    "Count,Tradelist Count,Name,Edition,Edition Code,Card Number,Condition,Language,Foil,Signed,Artist Proof,"
    "Altered Art,Misprint,Promo,Textless,Printing Id,Printing Note,Tags,My Price\n"
    "1,0,Elvish Mystic,Commander Masters,CMM,648,Good (Lightly Played),English,,,,,,,,,,,\n"
    "1,0,\"Ghalta, Primal Hunger\",Rivals of Ixalan,,,Near Mint,English,,,,,,,,,,,\n")
OWN_COLUMNS = HEADER + "Aerie Mystics,con,1,foil,3,LP,en,from a trade\n"


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


class CollectionEditTestCase(ApiTestCase):

    def setUp(self):
        super().setUp()
        box = self.box
        _write(box.root / "config.json", json.dumps(ROLES))
        _write(box.magic / "people" / "user2" / "collection.csv", USER2)
        for target, name, value in ((config, "REPO", box.root), (config, "DATA", box.data),
                                    (ce, "IMPORTS_DIR", box.data / "collection-imports"),
                                    (ce, "_upload_date", lambda: "2026-10-10")):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        # The inventory: the sandbox's files. Each write's message, reason and Summary are kept.
        self.backend = FileInventory(box.root)
        self.writes = []
        real = self.backend.apply

        def apply(op, actor, message, reason=None, expected_revision=None):
            after, summary = real(op, actor, message, reason=reason, expected_revision=expected_revision)
            self.writes.append((message, actor, reason, summary))
            return after, summary
        self.backend.apply = apply
        self.addCleanup(inventory.use(self.backend))

    def assertApiError(self, status, call, *args, contains=None, **kwargs):
        return super().assertApiError(status, lambda: call(*args, **kwargs), contains=contains)

    def as_(self, profile):
        """Act as a visitor through the tunnel (None: the home network)."""
        return access.using(None if profile is None else {"profile": profile, "email": "", "remote": True})

    def call(self, function, profile="matt", **data):
        return function(json.dumps({"profile": profile, **data}).encode("utf-8"))

    def rows(self, space="home"):
        return ce.rows_view(space)

    def last_write(self):
        """(message, who by) of the last write the sandbox's inventory recorded."""
        message, actor, _, _ = self.writes[-1]
        return message, actor.name

    def reason(self):
        """The last write's reason (None without one)."""
        return self.writes[-1][2]

    def extra(self):
        """The last write's extra lines (its Summary's body)."""
        return list((self.writes[-1][3].extra or {}).get("body", ()))

    def magic_files(self):
        """{repo path: bytes} of every file under the sandbox's magic/."""
        return {p.relative_to(self.box.root).as_posix(): p.read_bytes()
                for p in self.box.magic.rglob("*") if p.is_file()}

    def save(self, space="home", profile="matt", **data):
        data.setdefault("sha256", self.rows(space)["sha256"])
        return self.call(ce.save_card, profile, space=space, **data)


class RowsTests(CollectionEditTestCase):

    def test_home_rows_as_in_the_file(self):
        view = self.rows()
        self.assertEqual(view["space"], "home")
        self.assertEqual(view["sha256"], sha((self.box.magic / "collection.csv").read_bytes()))
        self.assertEqual([r["name"] for r in view["rows"]], ["Elvish Mystic", "Llanowar Elves", "Black Lotus"])
        self.assertEqual(view["rows"][0], {"name": "Elvish Mystic", "set": "cmm", "collector_number": "648",
                                           "finish": "nonfoil", "quantity": "1", "condition": "NM",
                                           "language": "en", "notes": ""})
        self.assertTrue(view["editable"])           # the home network

    def test_rows_come_with_pictures_kept_apart_from_the_rows(self):
        # The Card list's thumbnails and viewer (WP9): each row's card, keyed by its identity key, with the
        # row's own printing's picture; a name Scryfall doesn't know has none. The rows stay the eight columns.
        view = self.rows()
        pictures = view["pictures"]
        elves = pictures["fdn|227|nonfoil"]
        self.assertEqual((elves["name"], elves["img_small"], elves["exact"]), ("Llanowar Elves", "/img/fdn/227/small", True))
        self.assertIn("oracle_text", elves)
        self.assertEqual(pictures["cmm|648|nonfoil"]["name"], "Elvish Mystic")
        self.assertTrue(all(set(r) == set(ce.FIELDS) for r in view["rows"]))

    def test_rows_come_with_prices_of_their_own_printing_and_finish(self):
        # The Card list's ~A$ each (E7-S27): Scryfall's USD for the row's own printing and finish (not the
        # cheapest printing's) at the rate; no entry for a row Scryfall has no price for (Black Lotus).
        view = self.rows()
        prices = view["prices"]
        self.assertEqual(prices["rows"], {"cmm|648|nonfoil": {"usd": 1.35, "aud": 2.7},
                                          "fdn|227|nonfoil": {"usd": 0.25, "aud": 0.5}})
        self.assertEqual((prices["rate"], prices["rate_date"], prices["price_date"], prices["price_error"]),
                         (2.0, "2026-09-28", "2026-09-28", None))
        self.assertTrue(all(set(r) == set(ce.FIELDS) for r in view["rows"]))
        foil = self.save(action="add", row={"name": "Llanowar Elves", "set": "fdn", "collector_number": "227",
                                            "finish": "foil", "quantity": "1"})
        self.assertEqual(foil["prices"]["rows"]["fdn|227|foil"], {"usd": 1.77, "aud": 3.54})
        self.assertEqual(len(foil["prices"]["rows"]), 3)        # the whole list's, not just the row saved

    def test_without_a_rate_rows_show_and_say_why_there_are_no_prices(self):
        with mock.patch.object(ce.cards, "usd_to_aud", side_effect=RuntimeError("no rate")):
            view = self.rows()
        self.assertEqual(view["prices"]["rows"], {})
        self.assertEqual(view["prices"]["price_error"], "no rate")
        self.assertEqual(len(view["rows"]), 3)

    def test_storage_counts_give_held_copies_to_named_printings_then_the_cheapest(self):
        # In storage only (E7-S28): decks count copies by name; their lists' printings say which rows hold them.
        # Source hints are additive metadata; keep these assertions on the original allocation.
        def counts(storage):
            return {**storage, "rows": {key: {field: row[field] for field in ("held", "guess")}
                                        for key, row in storage["rows"].items()}}

        from collections import Counter
        from decklab.lib import pool
        row = lambda name, s, n, finish="nonfoil", q="2": {"name": name, "set": s, "collector_number": n,
                                                          "finish": finish, "quantity": q}
        rows = [row("Llanowar Elves", "fdn", "227"), row("Llanowar Elves", "fdn", "227", "foil", "1"),
                row("Elvish Mystic", "cmm", "648", q="1"), row("Forest", "fdn", "280", "foil", "3"),
                row("Black Lotus", "lea", "232", q="1")]
        decks = [pool.InUse("casual/a", "A", "built", Counter({"Llanowar Elves": 2, "Elvish Mystic": 1}),
                            printings=Counter({("Llanowar Elves", "fdn", "227", "foil"): 1,
                                               ("Elvish Mystic", "m19", "1", "nonfoil"): 1}))]
        fake = pool.Pool(Counter(), {}, decks)
        prices = ce._prices(rows)
        with mock.patch.object(pool, "load_pool", return_value=fake):
            storage = counts(ce._storage("home", rows, prices))
        self.assertIsNone(storage["error"])
        self.assertEqual(storage["rows"], {
            "fdn|227|foil": {"held": 1, "guess": False},         # the printing the deck's list names
            "fdn|227|nonfoil": {"held": 1, "guess": False},      # the rest: the only row left with room
            "cmm|648|nonfoil": {"held": 1, "guess": False},      # another printing named, but only one row
            "fdn|280|foil": {"held": None, "guess": False}})     # basics' copies in decks aren't tracked
        # Two rows with room for a copy no list names: the cheaper one gets it, as a guess.
        decks[0].printings.clear()
        with mock.patch.object(pool, "load_pool", return_value=fake):
            storage = counts(ce._storage("home", rows, prices))
        self.assertEqual(storage["rows"]["fdn|227|nonfoil"], {"held": 2, "guess": True})
        self.assertNotIn("fdn|227|foil", storage["rows"])
        # An unpriced row isn't known to be cheap: the priced one gets the copies first.
        unpriced = {**prices, "rows": {k: v for k, v in prices["rows"].items() if k != "fdn|227|nonfoil"}}
        with mock.patch.object(pool, "load_pool", return_value=fake):
            storage = counts(ce._storage("home", rows, unpriced))
        self.assertEqual(storage["rows"]["fdn|227|foil"], {"held": 1, "guess": True})
        self.assertEqual(storage["rows"]["fdn|227|nonfoil"], {"held": 1, "guess": True})
        # Copies enough to fill every row: no choice, so no guess.
        decks[0].cards["Llanowar Elves"] = 3
        with mock.patch.object(pool, "load_pool", return_value=fake):
            storage = counts(ce._storage("home", rows, prices))
        self.assertEqual((storage["rows"]["fdn|227|nonfoil"], storage["rows"]["fdn|227|foil"]),
                         ({"held": 2, "guess": False}, {"held": 1, "guess": False}))
        with mock.patch.object(ce, "_ready", return_value=False):
            self.assertEqual(ce._storage("home", rows, prices), {"rows": {}, "error": "The card data isn't ready yet."})
        with mock.patch.object(pool, "load_pool", side_effect=ValueError("bad pool")):
            storage = counts(ce._storage("home", rows, prices))
        self.assertEqual(storage["rows"], {})
        self.assertIn("bad pool", storage["error"])
        # Through the rows view, against the sandbox's real built decks.
        self.assertEqual(counts(self.rows()["storage"]), {"rows": {"cmm|648|nonfoil": {"held": 1, "guess": False},
                                                           "fdn|227|nonfoil": {"held": 2, "guess": False}},
                                                  "error": None})

    def test_a_missing_file_is_empty(self):
        _write(self.box.root / "config.json", json.dumps(ROLES))
        view = self.rows("user3")
        self.assertEqual((view["rows"], view["sha256"]), ([], ce.EMPTY_SHA))

    def test_editable_follows_the_visitor(self):
        with self.as_("user2"):
            self.assertTrue(self.rows("user2")["editable"])
            self.assertApiError(403, self.rows, "home")         # home's isn't his to see
        with self.as_("user1"):
            self.assertTrue(self.rows("home")["editable"])       # home's is User1's as Matt's (E10-S43)
        with self.as_("matt"):
            self.assertTrue(self.rows("home")["editable"])
            # An admin opens no other space's (E10-S29): the 403 a missing space gets, naming no one.
            error = self.assertApiError(403, self.rows, "user3")
            self.assertEqual(error.message, "That collection isn't public.")

    def test_unknown_space(self):
        self.assertApiError(404, self.rows, "nobody")           # a script naming nobody is told
        self.assertApiError(400, self.rows, "../x" * 20)
        # Anyone named gets the hidden space's answer, word for word, so it tells nothing.
        with self.as_("matt"):
            missing = self.assertApiError(403, self.rows, "nobody")
            hidden = self.assertApiError(403, self.rows, "user2")
        self.assertEqual((missing.message, missing.extra), (hidden.message, hidden.extra))

    def test_collection_view_names_its_space(self):
        view = collection.collection_view(space="user2")
        self.assertEqual(view["space"], "user2")
        self.assertEqual([c["name"] for c in view["cards"]], ["Llanowar Elves"])
        self.assertEqual(view["spaces"][0], {"id": "home", "name": "Home"})
        self.assertIn({"id": "user2", "name": "User2"}, view["spaces"])
        with self.as_("user2"):
            self.assertApiError(403, collection.collection_view)      # home's isn't his to see
            view = collection.collection_view(space="user2")
            self.assertTrue(view["editable"])
            self.assertEqual(view["spaces"], [{"id": "user2", "name": "User2"}])


class DownloadTests(CollectionEditTestCase):
    """E7-S30: the Collection page's Download, a space's collection as a CSV for its own people."""

    def download(self, space="home", profile=None):
        with self.as_(profile), mock.patch.object(ce, "_upload_date", lambda: "2026-10-25"):
            return ce.download_view(space)

    def test_home_s_collection_is_collection_csv_named_after_the_space_and_date(self):
        answer = self.download(profile="user1")
        self.assertEqual((answer["space"], answer["filename"]), ("home", "home-collection-2026-10-25.csv"))
        self.assertEqual(answer["csv"].encode("utf-8"), ce.csv_bytes(self.rows()["rows"]))   # sorted, LF, no BOM
        lines = answer["csv"].splitlines()
        self.assertEqual(lines[0], "name,set,collector_number,finish,quantity,condition,language,notes")
        self.assertEqual([line.split(",")[0] for line in lines[1:]], ["Elvish Mystic", "Llanowar Elves", "Black Lotus"])

    def test_a_member_downloads_their_own_space_and_no_one_else_does(self):
        answer = self.download("user2", "user2")
        self.assertEqual(answer["filename"], "user2-collection-2026-10-25.csv")
        self.assertIn("Llanowar Elves", answer["csv"])
        for profile, space in (("matt", "user2"), ("user2", "home"), ("user2", "nobody")):
            with self.subTest(profile=profile, space=space):
                error = self.assertApiError(403, self.download, space, profile)
                self.assertEqual((error.message, error.extra), ("That collection isn't public.", {}))

    def test_it_reads_back_through_the_import_as_the_collection_columns(self):
        text = self.download()["csv"]
        answer = self.call(ce.import_preview, "matt", space="home", filename="home-collection-2026-10-25.csv",
                           text=text)
        self.assertEqual(answer["format"], "collection")
        self.assertEqual(answer["problems"], [])
        self.assertEqual([{k: r[k] for k in ce.FIELDS} for r in answer["rows"]], self.rows()["rows"])


class SaveTests(CollectionEditTestCase):

    def test_add_a_card_to_a_persons_collection(self):
        with self.as_("user2"):
            answer = self.save("user2", "user2", action="add",
                               row={"name": "llanowar elves", "set": "M19", "collector_number": "314",
                                    "finish": "nonfoil", "quantity": 1, "condition": "", "language": ""})
        self.assertTrue(answer["ok"])
        self.assertFalse(answer["merged"])
        self.assertNotIn("commit", answer)
        self.assertEqual(self.last_write(),
                         ("add card Llanowar Elves (M19 314) in User2's collection", "User2"))
        text = (self.box.magic / "people" / "user2" / "collection.csv").read_bytes()
        self.assertEqual(text, (USER2 + "Llanowar Elves,m19,314,nonfoil,1,,,\n").encode())
        self.assertEqual(answer["sha256"], sha(text))
        self.assertEqual(len(answer["rows"]), 2)
        self.assertEqual(list(answer["pictures"]), ["m19|314|nonfoil"])       # the saved row's thumbnail

    def test_a_save_lists_its_space_s_decks_whose_tables_are_now_out_of_date(self):
        table = ("\n## Owned vs needed\n\n| Card | Need | Owned | Missing | ~AUD each | ~AUD missing | Notes |\n"
                 "|---|---|---|---|---|---|---|\n| Llanowar Elves | 4 | {owned} | **{missing}** | | | |\n"
                 "| **Total to buy** | | | **{missing}** | | | |\n")
        deck = ("# {title}\n\n- **Format:** Casual 60-card, 1v1\n{played}- **Status:** idea\n\n## Decklist\n\n"
                "```\nDeck\n4 Llanowar Elves (FDN) 227\n```\n")
        _write(self.box.magic / "people" / "user2" / "decks" / "casual" / "r-table.md",
               deck.format(title="R Table", played="") + table.format(owned=2, missing=2))
        # A home deck whose table is out of date already: not the person's save's business.
        _write(self.box.magic / "decks" / "casual" / "home-table.md",
               deck.format(title="Home Table", played="- **Played by:** wife\n") + table.format(owned=4, missing=0))
        self.assertEqual(ce._stale_tables("user2"), [])
        with self.as_("user2"):
            answer = self.save("user2", "user2", action="add",
                               row={"name": "Llanowar Elves", "set": "fdn", "collector_number": "227",
                                    "finish": "nonfoil", "quantity": 1, "condition": "NM", "language": "en"})
        [stale] = answer["stale_tables"]
        self.assertEqual((stale["id"], stale["title"], stale["count"], stale["may_update"]),
                         ("user2/casual/r-table", "R Table", 1, True))
        self.assertEqual(stale["changes"][0]["now"]["owned"], 3)
        # Home's save lists home's deck only; User1 may update it (she plays it).
        with self.as_("user1"):
            self.assertEqual([(s["id"], s["may_update"]) for s in ce._stale_tables("home")],
                             [("casual/home-table", True)])
        # A visitor who can't see the space's inventory gets none (R6d).
        with self.as_("user1"):
            self.assertEqual(ce._stale_tables("user2"), [])

    def test_stale_tables_that_cant_be_worked_out_never_fail_the_save(self):
        with mock.patch("decklab.lib.api.commits._stale_list", side_effect=RuntimeError("no")):
            answer = self.save(action="add", row={"name": "Black Lotus", "set": "lea", "collector_number": "232",
                                                  "finish": "nonfoil", "quantity": "1", "condition": "NM",
                                                  "language": "en"})
        self.assertTrue(answer["ok"])
        self.assertEqual(answer["stale_tables"], [])

    def test_adding_a_listed_printing_adds_to_it(self):
        answer = self.save(action="add", row={"name": "Black Lotus", "set": "lea", "collector_number": "232",
                                              "finish": "nonfoil", "quantity": "2", "condition": "NM",
                                              "language": "en"})
        self.assertTrue(answer["merged"])
        lotus = next(r for r in answer["rows"] if r["name"] == "Black Lotus")
        self.assertEqual(lotus["quantity"], "3")
        self.assertEqual(self.last_write(), ("add card Black Lotus (LEA 232) in the home collection", "Matt"))

    def test_edit_and_remove_with_a_reason(self):
        original = {"set": "lea", "collector_number": "232", "finish": "nonfoil"}
        answer = self.save(action="edit", original=original,
                           row={"name": "Black Lotus", "set": "lea", "collector_number": "232", "finish": "nonfoil",
                                "quantity": 1, "condition": "LP", "language": "en", "notes": "a little worn"})
        lotus = next(r for r in answer["rows"] if r["name"] == "Black Lotus")
        self.assertEqual((lotus["condition"], lotus["notes"]), ("LP", "a little worn"))
        self.assertEqual(self.last_write(), ("edit card Black Lotus (LEA 232) in the home collection", "Matt"))
        self.assertIsNone(self.reason())
        # The page sends the row with a remove too; only original counts.
        answer = self.save(action="remove", original=original, reason="Traded to User2",
                           row={"name": "Black Lotus", "set": "lea", "collector_number": "232", "finish": "nonfoil",
                                "quantity": 1})
        self.assertNotIn("Black Lotus", [r["name"] for r in answer["rows"]])
        self.assertEqual(self.last_write(), ("remove card Black Lotus (LEA 232) in the home collection", "Matt"))
        self.assertEqual(self.reason(), "Traded to User2")

    def test_an_edit_onto_another_listed_printing_is_refused(self):
        self.assertApiError(400, self.save, action="edit",
                            original={"set": "lea", "collector_number": "232", "finish": "nonfoil"},
                            row={"name": "Llanowar Elves", "set": "fdn", "collector_number": "227",
                                 "finish": "nonfoil", "quantity": 1}, contains="already listed")

    def test_checks_against_scryfall(self):
        row = {"name": "Black Lotus", "set": "lea", "collector_number": "232", "finish": "nonfoil", "quantity": 1}
        for bad, words in (({"name": "Blak Lotus"}, "no card named"),
                           ({"collector_number": "999"}, "printing unknown"),
                           ({"finish": "foil"}, "wasn't printed foil"),
                           ({"finish": "shiny"}, "finish must be"),
                           ({"quantity": 0}, "quantity must be"),
                           ({"quantity": 10000}, "quantity must be"),
                           ({"set": "not a set"}, "set must be")):
            self.assertApiError(400, self.save, action="add", row={**row, **bad}, contains=words)

    def test_formula_like_text_is_refused(self):
        row = {"name": "Black Lotus", "set": "lea", "collector_number": "232", "finish": "nonfoil", "quantity": 1}
        for key in ("notes", "condition", "language"):
            for start in ("=", "+", "-", "@"):
                self.assertApiError(400, self.save, action="add", row={**row, key: f"{start}SUM(A1)"},
                                    contains="formula")
        self.assertTrue(self.save(action="add", row={**row, "notes": "traded, 2 for 1"})["ok"])

    def test_ordinary_basics_are_not_added(self):
        self.assertApiError(400, self.save, action="add",
                            row={"name": "Forest", "set": "fdn", "collector_number": "280", "finish": "nonfoil",
                                 "quantity": 5}, contains="basic lands")

    def test_a_stale_sha_is_409_with_the_rows_now(self):
        error = self.assertApiError(409, self.save, action="add", sha256="0" * 64,
                                    row={"name": "Black Lotus", "set": "lea", "collector_number": "232",
                                         "finish": "nonfoil", "quantity": 1})
        self.assertEqual(error.extra["sha256"], self.rows()["sha256"])
        self.assertEqual(len(error.extra["rows"]), 3)
        self.assertEqual(error.extra["prices"]["rows"]["fdn|227|nonfoil"], {"usd": 0.25, "aud": 0.5})

    def test_a_save_waits_for_another_save_in_the_server(self):
        # saving._save_lock first, as every inventory writer in the server takes it: never a false BUSY.
        import threading
        from decklab.lib.api import saving
        done = {}
        row = {"name": "Black Lotus", "set": "lea", "collector_number": "232", "finish": "nonfoil", "quantity": 1}
        sha256 = self.rows()["sha256"]
        thread = threading.Thread(target=lambda: done.setdefault("answer", self.save(action="add", row=row,
                                                                                      sha256=sha256)))
        with saving._save_lock:
            thread.start()
            thread.join(0.5)
            self.assertTrue(thread.is_alive())
        thread.join(30)
        self.assertTrue(done["answer"]["ok"])

    def test_refusals_never_show_an_absolute_path(self):
        row = {"name": "Black Lotus", "set": "lea", "collector_number": "232", "finish": "nonfoil", "quantity": 1}
        where = f"{config.REPO}/magic/collection.csv"
        for error, status in ((inventory.Conflict(f"{where} is locked"), 409),
                              (inventory.Invalid(f"{where} is wrong"), 400), (ValueError(f"{where} exists"), 409)):
            with mock.patch.object(inventory, "apply", side_effect=error):
                caught = self.assertApiError(status, self.save, action="add", row=row)
            self.assertIn("magic/collection.csv", caught.message)
            self.assertNotIn(str(config.REPO), caught.message)


class BulkTests(CollectionEditTestCase):
    """POST /api/collection/bulk: the Card list's "Set condition & language" (E7-S29)."""

    BLANKS = (HEADER + "Elvish Mystic,cmm,648,nonfoil,1,LP,,\n" + "Llanowar Elves,fdn,227,nonfoil,5,,,binder 2\n"
              + "Black Lotus,lea,232,nonfoil,1,NM,ja,Merged copies have differing or unreported condition\n")
    KEYS = [{"set": "cmm", "collector_number": "648", "finish": "nonfoil"},
            {"set": "fdn", "collector_number": "227", "finish": "nonfoil"},
            {"set": "lea", "collector_number": "232", "finish": "nonfoil"}]

    def setUp(self):
        super().setUp()
        _write(self.box.magic / "collection.csv", self.BLANKS)

    def bulk(self, space="home", profile="matt", **data):
        data.setdefault("sha256", self.rows(space)["sha256"])
        data.setdefault("keys", self.KEYS)
        return self.call(ce.bulk_set, profile, space=space, **data)

    def facts(self, rows):
        return {r["name"]: (r["quantity"], r["condition"], r["language"], r["notes"]) for r in rows}

    def test_fills_only_blanks_by_default_in_one_change(self):
        answer = self.bulk(condition="NM", language="en")
        self.assertEqual(answer["changed"], 2)
        self.assertEqual(self.facts(answer["rows"]), {
            "Elvish Mystic": ("1", "LP", "en", ""),                 # its condition kept
            "Llanowar Elves": ("5", "NM", "en", "binder 2"),
            "Black Lotus": ("1", "NM", "ja", "Merged copies have differing or unreported condition")})
        self.assertEqual(len(self.writes), 1)                       # one change set
        self.assertEqual(self.last_write(), ("edit 2 rows in the home collection", "Matt"))
        self.assertEqual(self.extra(), ["Changed Elvish Mystic (CMM 648).", "Changed Llanowar Elves (FDN 227)."])
        text = (self.box.magic / "collection.csv").read_bytes()
        self.assertEqual(answer["sha256"], sha(text))
        self.assertEqual(answer["prices"]["rows"]["fdn|227|nonfoil"], {"usd": 0.25, "aud": 0.5})
        self.assertIn("storage", answer)
        self.assertEqual(answer["stale_tables"], [])

    def test_overwrites_when_only_blank_is_false(self):
        answer = self.bulk(language="en", only_blank=False)
        self.assertEqual(answer["changed"], 3)
        self.assertEqual({n: f[2] for n, f in self.facts(answer["rows"]).items()},
                         {"Elvish Mystic": "en", "Llanowar Elves": "en", "Black Lotus": "en"})
        self.assertEqual({n: f[1] for n, f in self.facts(answer["rows"]).items()},
                         {"Elvish Mystic": "LP", "Llanowar Elves": "", "Black Lotus": "NM"})
        self.assertEqual(self.last_write(), ("edit 3 rows in the home collection", "Matt"))

    def test_only_the_named_rows_change(self):
        answer = self.bulk(keys=self.KEYS[1:2], language="en")
        self.assertEqual(answer["changed"], 1)
        self.assertEqual(self.facts(answer["rows"])["Elvish Mystic"][2], "")
        self.assertEqual(self.last_write(), ("edit 1 row in the home collection", "Matt"))

    def test_nothing_to_change_writes_nothing(self):
        before = self.magic_files()
        answer = self.bulk(keys=self.KEYS[2:], language="en", condition="LP")      # both set already
        self.assertEqual((answer["ok"], answer["changed"], len(answer["rows"])), (True, 0, 3))
        self.assertEqual(self.writes, [])
        self.assertEqual(self.magic_files(), before)

    def test_a_stale_sha_is_409_with_the_rows_now(self):
        error = self.assertApiError(409, self.bulk, sha256="0" * 64, language="en")
        self.assertEqual(error.extra["sha256"], self.rows()["sha256"])
        self.assertEqual(len(error.extra["rows"]), 3)
        self.assertEqual(self.writes, [])

    def test_an_unknown_key_is_409_with_the_rows(self):
        error = self.assertApiError(409, self.bulk, language="en", contains="isn't in the collection",
                                    keys=[*self.KEYS, {"set": "m19", "collector_number": "314", "finish": "nonfoil"}])
        self.assertEqual(len(error.extra["rows"]), 3)
        self.assertEqual(self.writes, [])

    def test_only_the_space_s_own_people_may(self):
        with self.as_("user2"):
            self.assertApiError(403, self.bulk, profile="user2", language="en", sha256="0" * 64)
            answer = self.bulk("user2", "user2", language="ja", only_blank=False,
                               keys=[{"set": "fdn", "collector_number": "227", "finish": "nonfoil"}])
        self.assertEqual(answer["rows"][0]["language"], "ja")
        self.assertEqual(self.last_write(), ("edit 1 row in User2's collection", "User2"))
        with self.as_("user1"):
            self.assertEqual(self.bulk(profile="user1", language="en")["changed"], 2)

    def test_bad_requests_are_400(self):
        for data, words in (({"condition": "Mint"}, "condition must be"),
                            ({"language": "english"}, "language must be"),
                            ({}, "Give a condition"),
                            ({"language": "en", "only_blank": "yes"}, "only_blank"),
                            ({"language": "en", "keys": []}, "keys must be"),
                            ({"language": "en", "keys": [self.KEYS[0], self.KEYS[0]]}, "more than once"),
                            ({"language": "en", "keys": [{"set": "cmm", "collector_number": "648"}]}, None),
                            ({"language": "en", "keys": [{**self.KEYS[0], "finish": "shiny"}]}, "Each key"),
                            ({"language": "en", "keys": ["x"]}, "Each key must be"),
                            ({"language": "en", "keys": [{**self.KEYS[0], "set": 1}]}, "Each key's values"),
                            ({"language": ["en"]}, "language must be"),
                            ({"condition": {"NM": 1}}, "condition must be"),
                            ({"language": "en", "notes": "x"}, None)):
            with self.subTest(data=data):
                self.assertApiError(400, self.bulk, contains=words, **data)
        self.assertEqual(self.writes, [])

    def test_too_many_keys_or_too_big_a_body(self):
        with mock.patch.object(ce, "MAX_BULK_KEYS", 2):
            self.assertApiError(400, self.bulk, language="en", contains="keys must be a list of 1 to 2")
        with mock.patch.object(ce, "MAX_BULK_BODY", 100):
            self.assertApiError(413, self.bulk, language="en")
        self.assertEqual(self.writes, [])


class ImportTests(CollectionEditTestCase):

    # A space's imports are made by its own people (E10-S29: Matt home's, User2 his own).
    def preview(self, text, space="home", filename="export.csv", profile=None):
        profile = profile or ("matt" if space == "home" else space)
        return self.call(ce.import_preview, profile, space=space, filename=filename, text=text)

    def apply(self, preview, space="home", profile=None, **data):
        profile = profile or ("matt" if space == "home" else space)
        data.setdefault("sha256", self.rows(space)["sha256"])
        return self.call(ce.import_apply, profile, space=space, token=preview["token"], **data)

    def test_manabox(self):
        answer = self.preview(MANABOX)
        self.assertEqual(answer["format"], "manabox")
        self.assertEqual(answer["dropped_basics"], 10)
        good = [r for r in answer["rows"] if not r["problem"]]
        self.assertEqual([(r["name"], r["set"], r["collector_number"], r["finish"], r["quantity"], r["condition"],
                           r["language"], r["line"]) for r in good],
                         [("Llanowar Elves", "fdn", "227", "foil", "3", "NM", "", 2),
                          ("Sol Ring", "ecc", "57", "nonfoil", "1", "MP", "ja", 5)])
        self.assertIn("differing or unreported language", good[0]["notes"])
        self.assertEqual(answer["problems"], [{"line": 6, "message": "Scryfall has no card named 'Nonsense Card'"}])
        self.assertEqual(answer["adds"], {"rows": 2, "cards": 4})

    def test_moxfield(self):
        answer = self.preview(MOXFIELD)
        self.assertEqual(answer["format"], "moxfield")
        self.assertEqual(answer["problems"], [])
        self.assertEqual([(r["name"], r["set"], r["finish"], r["quantity"], r["condition"], r["language"])
                          for r in answer["rows"]],
                         [("Black Lotus", "lea", "nonfoil", "1", "NM", "en"),
                          ("Pick Your Poison", "mkm", "foil", "2", "HP", "de")])

    def test_deckbox(self):
        answer = self.preview(DECKBOX)
        self.assertEqual(answer["format"], "deckbox")
        self.assertEqual([(r["name"], r["set"], r["collector_number"], r["condition"], r["language"])
                          for r in answer["rows"]],
                         [("Elvish Mystic", "cmm", "648", "LP", "en"), ("Ghalta, Primal Hunger", "", "", "NM", "en")])
        self.assertEqual(len(answer["problems"]), 1)
        self.assertIn("printing unknown", answer["problems"][0]["message"])
        self.assertEqual(answer["problems"][0]["line"], 3)

    def test_collection_columns(self):
        answer = self.preview(OWN_COLUMNS)
        self.assertEqual(answer["format"], "collection")
        self.assertEqual(answer["rows"][0]["notes"], "from a trade")
        self.assertEqual(answer["rows"][0]["condition"], "LP")

    def test_repeat_preview_is_same_space_exact_bytes_and_metadata_only(self):
        folder = self.box.magic / "people" / "user2" / "imports"
        _write(folder / "first.csv", OWN_COLUMNS)
        _write(folder / "different-name.csv", OWN_COLUMNS)
        _write(self.box.magic / "imports" / "home-only.csv", OWN_COLUMNS)
        preview = self.preview(OWN_COLUMNS, "user2", "Renamed.csv")
        self.assertEqual(preview["repeat_imports"], [
            {"name": "different-name.csv", "imported_at": None, "imported_by": None},
            {"name": "first.csv", "imported_at": None, "imported_by": None}])
        self.assertEqual(self.preview(OWN_COLUMNS.replace("\n", "\r\n"), "user2")["repeat_imports"], [])
        self.assertEqual(self.preview(OWN_COLUMNS + "\n", "user2", "first.csv")["repeat_imports"], [])
        self.assertEqual(self.preview(OWN_COLUMNS, "home")["repeat_imports"], [
            {"name": "home-only.csv", "imported_at": None, "imported_by": None}])
        with self.as_("user3"):
            self.assertApiError(403, self.preview, OWN_COLUMNS, "user2", profile="user3")

    def test_intentional_repeat_is_additive_and_records_the_repeat_in_the_audit_message(self):
        first = self.apply(self.preview(OWN_COLUMNS, "user2", "Original.csv"), "user2")
        raw = (self.box.root / first["raw"]).read_bytes()
        preview = self.preview(OWN_COLUMNS, "user2", "Renamed.csv")
        answer = self.apply(preview, "user2", sha256=first["sha256"])
        self.assertEqual(next(r["quantity"] for r in answer["rows"] if r["name"] == "Aerie Mystics"), "6")
        self.assertIn("intentional repeat import", self.last_write()[0])
        self.assertIn("2026-10-10-original.csv", self.last_write()[0])
        self.assertEqual((self.box.root / first["raw"]).read_bytes(), raw)
        self.assertEqual((self.box.root / answer["raw"]).read_bytes(), raw)

    def test_changed_raw_import_matches_require_a_fresh_preview_even_when_collection_sha_didnt_change(self):
        preview = self.preview(OWN_COLUMNS, "user2")
        folder = self.box.magic / "people" / "user2" / "imports"
        _write(folder / "arrived-after-preview.csv", OWN_COLUMNS)
        before = self.magic_files()
        error = self.assertApiError(409, self.apply, preview, "user2", sha256=preview["sha256"])
        self.assertTrue(error.extra["repreview_required"])
        self.assertEqual(self.magic_files(), before)
        self.assertEqual(self.writes, [])
        self.assertTrue((self.box.data / "collection-imports" / "user2.json").exists())
        fresh = self.preview(OWN_COLUMNS, "user2")
        self.assertEqual(len(fresh["repeat_imports"]), 1)
        self.assertTrue(self.apply(fresh, "user2")["ok"])

    def test_another_spaces_matching_import_does_not_invalidate_the_preview(self):
        preview = self.preview(OWN_COLUMNS, "user2")
        _write(self.box.magic / "imports" / "after-preview.csv", OWN_COLUMNS)
        self.assertTrue(self.apply(preview, "user2", sha256=preview["sha256"])["ok"])

    def test_an_unknown_file_is_400(self):
        self.assertApiError(400, self.preview, "a,b,c\n1,2,3\n", contains="isn't a ManaBox")

    def test_too_big(self):
        with mock.patch.object(ce, "MAX_IMPORT", 100):
            self.assertApiError(413, self.preview, MANABOX)

    def test_apply_merges_and_saves_the_raw_file(self):
        before = self.magic_files()
        preview = self.preview(OWN_COLUMNS + "Llanowar Elves,fdn,227,nonfoil,2,NM,en,\n", "user2",
                               "My Cards (Oct).csv")
        answer = self.apply(preview, "user2")
        self.assertEqual(answer["added"], {"rows": 1, "cards": 5})
        self.assertEqual(answer["skipped"], 0)
        elves = next(r for r in answer["rows"] if r["set"] == "fdn")
        self.assertEqual(elves["quantity"], "4")
        raw = self.box.magic / "people" / "user2" / "imports" / "2026-10-10-my-cards-oct.csv"
        self.assertEqual(raw.read_text(encoding="utf-8"), OWN_COLUMNS + "Llanowar Elves,fdn,227,nonfoil,2,NM,en,\n")
        self.assertEqual(answer["raw"], "magic/people/user2/imports/2026-10-10-my-cards-oct.csv")
        self.assertEqual(answer["stale_tables"], [])        # no deck of User2's has a table
        self.assertEqual(self.last_write(),
                         ("import 5 cards into User2's collection from My Cards (Oct).csv", "User2"))
        after = self.magic_files()
        self.assertEqual(sorted(rel for rel in before.keys() | after.keys() if before.get(rel) != after.get(rel)),
                         ["magic/people/user2/collection.csv",
                          "magic/people/user2/imports/2026-10-10-my-cards-oct.csv"])
        # Applied once: the preview is gone.
        self.assertApiError(410, self.apply, preview, "user2")

    def test_an_import_lists_the_space_s_decks_whose_tables_it_left_out_of_date(self):
        _write(self.box.magic / "people" / "user2" / "decks" / "casual" / "r-table.md",
               "# R Table\n\n- **Format:** Casual 60-card, 1v1\n- **Status:** idea\n\n## Decklist\n\n"
               "```\nDeck\n4 Llanowar Elves (FDN) 227\n```\n"
               "\n## Owned vs needed\n\n| Card | Need | Owned | Missing | ~AUD each | ~AUD missing | Notes |\n"
               "|---|---|---|---|---|---|---|\n| Llanowar Elves | 4 | 2 | **2** | | | |\n"
               "| **Total to buy** | | | **2** | | | |\n")
        preview = self.preview(OWN_COLUMNS + "Llanowar Elves,fdn,227,nonfoil,2,NM,en,\n", "user2", "more.csv")
        answer = self.apply(preview, "user2")
        [stale] = answer["stale_tables"]
        self.assertEqual((stale["id"], stale["count"], stale["may_update"]), ("user2/casual/r-table", 1, True))
        self.assertEqual(stale["changes"][0]["now"]["owned"], 4)

    def test_problems_block_unless_skipped(self):
        preview = self.preview(MANABOX)
        error = self.assertApiError(400, self.apply, preview)
        self.assertEqual(error.extra["problems"][0]["line"], 6)
        answer = self.apply(preview, skip_problems=True)
        self.assertEqual((answer["added"]["cards"], answer["skipped"]), (4, 1))
        self.assertEqual(self.last_write(), ("import 4 cards into the home collection from export.csv", "Matt"))
        extra = "\n".join(self.extra())
        self.assertIn("Left out 1 rows with problems: line 6", extra)
        self.assertIn("Left out 10 ordinary basic lands", extra)

    def test_apply_with_a_stale_sha_is_409(self):
        preview = self.preview(MOXFIELD)
        self.assertApiError(409, self.apply, preview, sha256="0" * 64)

    def test_a_preview_is_for_its_space_and_person(self):
        preview = self.preview(MOXFIELD, profile="matt")
        # Nobody named writes two spaces any more (E10-S29), so the record's own check is asked directly.
        path = ce._preview_path({"id": "matt"})
        self.assertApiError(400, ce._load_preview, preview["token"], "user2", {"id": "matt"})
        self.assertTrue(path.exists())
        with self.as_("user1"):            # Matt's preview isn't User1's to apply, at home too
            self.assertApiError(410, self.apply, preview, "home", "user1")

    def test_previews_expire(self):
        preview = self.preview(MOXFIELD)
        with mock.patch.object(ce, "IMPORT_TTL", -1):
            self.assertApiError(410, self.apply, preview)

    def test_too_big_says_the_limit(self):
        with mock.patch.object(ce, "MAX_IMPORT", 100):
            error = self.assertApiError(413, self.preview, MANABOX)
        self.assertIn("limited to", error.message)
        self.assertIn("split it into smaller files", error.message)
        self.assertEqual(ce.MAX_IMPORT, 4 * 1024 * 1024)

    def test_rows_are_capped(self):
        text = HEADER + "".join(f"Black Lotus,lea,232,nonfoil,{n},,,\n" for n in range(1, 4))
        with mock.patch.object(ce, "MAX_IMPORT_ROWS", 3):
            self.assertEqual(self.preview(text)["rows"][0]["quantity"], "6")      # at the cap: fine
            error = self.assertApiError(400, self.preview, text + "Black Lotus,lea,232,nonfoil,1,,,\n\n")
        self.assertIn("more than 3 rows", error.message)
        self.assertIn("split it", error.message)
        self.assertEqual(ce.MAX_IMPORT_ROWS, 20000)

    def test_one_pending_preview_per_profile(self):
        first = self.preview(MOXFIELD)
        second = self.preview(OWN_COLUMNS)
        self.assertEqual(sorted(p.name for p in (self.box.data / "collection-imports").iterdir()), ["matt.json"])
        self.assertApiError(410, self.apply, first, contains="newer preview replaced it")
        self.assertEqual(self.apply(second)["added"]["cards"], 3)
        # Someone else's preview is kept beside it.
        self.preview(MOXFIELD, "user2", profile="user2")
        self.preview(MOXFIELD)
        self.assertEqual(sorted(p.name for p in (self.box.data / "collection-imports").iterdir()),
                         ["matt.json", "user2.json"])

    def test_a_preview_keeps_only_what_the_apply_needs(self):
        preview = self.preview(MANABOX)
        record = json.loads((self.box.data / "collection-imports" / "matt.json").read_text(encoding="utf-8"))
        self.assertEqual(set(record), {"version", "token", "space", "profile", "filename", "text", "format", "good",
                                    "problems", "dropped_basics", "repeat_imports", "source_rows", "groups"})
        self.assertEqual(record["version"], 4)
        self.assertEqual(record["source_rows"], preview["source_rows"])
        self.assertEqual(record["groups"], preview["groups"])
        self.assertEqual(record["token"], preview["token"])
        self.assertTrue(all(set(r) == set(ce.FIELDS) for r in record["good"]))
        self.assertEqual(record["problems"], [{"line": 6, "message": "Scryfall has no card named 'Nonsense Card'"}])

    def test_a_second_preview_meanwhile_is_429(self):
        self.assertTrue(ce._preview_lock.acquire(blocking=False))       # another preview being checked
        try:
            self.assertApiError(429, self.preview, MOXFIELD, contains="Another import is being checked")
        finally:
            ce._preview_lock.release()
        self.assertTrue(self.preview(MOXFIELD)["token"])

    def test_the_imports_folder_is_capped(self):
        folder = self.box.magic / "people" / "user2" / "imports"
        _write(folder / "2026-10-01-old.csv", "x" * 900)
        preview = self.preview(OWN_COLUMNS, "user2")
        before = (self.box.magic / "people" / "user2" / "collection.csv").read_bytes()
        with mock.patch.object(ce, "MAX_IMPORTS_FOLDER", 1000):
            error = self.assertApiError(413, self.apply, preview, "user2")
        self.assertIn("imports folder", error.message)
        self.assertIn("limit of 0 MB", error.message)               # the patched limit, in MB
        self.assertEqual((self.box.magic / "people" / "user2" / "collection.csv").read_bytes(), before)
        self.assertEqual([p.name for p in folder.iterdir()], ["2026-10-01-old.csv"])
        self.assertEqual(self.apply(preview, "user2")["added"]["cards"], 3)    # under the real 50 MB

    def test_cells_are_checked(self):
        text = (HEADER + "Black Lotus,lea,232,nonfoil,1,=1+1,klingon,\"=HYPERLINK(\"\"x\"\")\"\n"
                + "Aerie Mystics,con,1,foil,1,-1,@x,\"tab\there\"\n"
                + "Llanowar Elves,fdn,227,nonfoil,1,+NM,qya,fine\n")
        rows = self.preview(text)["rows"]
        self.assertIn("formula", rows[0]["problem"])
        self.assertIn("control character", rows[1]["problem"])
        self.assertIsNone(rows[2]["problem"])
        # Conditions and languages hold only their known values, or nothing.
        self.assertEqual([(r["condition"], r["language"]) for r in rows], [("", ""), ("", ""), ("", "qya")])

    def test_a_control_character_in_any_used_field(self):
        text = MANABOX.splitlines(keepends=True)
        text = text[0] + "Sol Ring,ECC,\"Edge of\tEternities\",57,normal,uncommon,1,13,z,1.00,false,false,,,USD\n"
        self.assertIn("control character", self.preview(text)["rows"][0]["problem"])


class PrintingsTests(CollectionEditTestCase):

    def test_newest_first_paper_only(self):
        answer = ce.printings_view("Llanowar Elves")
        self.assertEqual(answer["name"], "Llanowar Elves")
        sets = [p["set"] for p in answer["printings"]]
        self.assertNotIn("pana", sets)                  # online only
        self.assertIn("fdn", sets)
        released = [p["released"] or "" for p in answer["printings"]]
        self.assertEqual(released, sorted(released, reverse=True))
        fdn = next(p for p in answer["printings"] if p["set"] == "fdn")
        self.assertEqual((fdn["collector_number"], fdn["finishes"], fdn["set_name"]),
                         ("227", ["nonfoil", "foil"], "FDN"))      # the fixture has no set names
        self.assertEqual(fdn["img_small"], "/img/fdn/227/small")      # the Add card sheet's printing strip

    def test_unknown(self):
        self.assertApiError(404, ce.printings_view, "Blak Lotus")
        self.assertApiError(400, ce.printings_view, "")


if __name__ == "__main__":
    import unittest
    unittest.main()
