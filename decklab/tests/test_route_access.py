"""Every feature row has reviewed access metadata and an isolated cross-space request probe.

These probes run real handlers against disposable files/memory stores. Transport identity,
Cloudflare signature and origin checks retain their independent HTTP integration suites.
"""
import ast
import contextlib
import csv
import inspect
import io
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
from types import SimpleNamespace
from unittest import mock

from decklab.lib import access, accessories, config, feature_routes, inventory, jobs, permissions, server_http, state
from decklab.lib.api import activity_undo, guard
from decklab.lib.api.common import ApiError
from decklab.tests.test_activity import _entry, _game
from decklab.tests.test_api import _write
from decklab.tests.test_api_permissions import PermissionTestCase, R_DECK

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = "ROUTE_PRIVATE_MARKER"
DECK = "user3/casual/private-probe"
RECORD = "a" * 32
CLASSES = {"open", "admin", "home-admin", "home-records", "inventory", "inventory-edit", "deck", "deck-edit",
           "draft", "play", "profile", "accessories", "activity", "viewer-filtered", "deck-run", "run-stop"}


@contextlib.contextmanager
def requester(who):
    identity = {"profile": who, "email": "", "remote": True} if who == "user2" else None
    with access.using(identity), access.viewing(who if identity is None else None), access.answering(False):
        yield


class ProbeHandler:
    def __init__(self, method, params=None, body=None, path=None):
        self.command, self.params, self.body = method, params or {}, body
        self.path = path or "/api/status"
        self.identity = access.current()
        self.server = SimpleNamespace(remote=self.identity is not None)
        self.answer = None

    def _allow(self, *methods):
        if self.command not in methods:
            raise ApiError(405, "Method not allowed")

    def _query(self, query, names):
        return {key: value for key, value in self.params.items() if key in names}

    def _deck_id(self, params):
        return params.get("id")

    def _no_query(self, query):
        if query:
            raise AssertionError("Probe unexpectedly supplied a POST query")

    def _write_body(self, limit=None):
        return json.dumps(self.body).encode()

    def _send_json(self, status, answer):
        self.answer = status, answer

    _pair_id = server_http.Handler._pair_id
    _own_profile_only = server_http.Handler._own_profile_only


def proof_codes():
    """Observe existing access decisions without replacing their implementations."""
    names = ("require", "sees", "allowed", "own_settings", "accessory_owners", "accessory_readers", "activity_scope")
    return {value.__code__ for module in (guard, permissions) for name, value in vars(module).items()
            if inspect.isfunction(value) and any(name.startswith(prefix) for prefix in names)}


class RouteAccessTests(PermissionTestCase):
    def persisted(self):
        return ({path.relative_to(self.box.root).as_posix(): path.read_bytes()
                 for path in self.box.magic.rglob("*") if path.is_file()},
                (self.box.root / "config.json").read_bytes(), self.box.state.changes())

    def setUp(self):
        super().setUp()
        raw = json.loads((self.box.root / "config.json").read_text(encoding="utf-8"))
        raw["profiles"].append({"id": "user3", "name": "User3", "space": "user3", "role": "member"})
        raw["forge_dir"] = str(self.box.root / "no-forge")
        _write(self.box.root / "config.json", json.dumps(raw))
        _write(self.box.magic / "people/user3/decks/casual/private-probe.md", R_DECK.replace("User2 Elves", PRIVATE))
        _write(self.box.magic / "people/user3/collection.csv", "name,set,collector_number,finish,quantity,condition,language,notes\n"
               f"Llanowar Elves,fdn,227,nonfoil,7,NM,en,{PRIVATE}\n")
        from decklab.lib.inventory import loan_rules, rules as inventory_rules
        loan = {"id": "c" * 32, "name": "Llanowar Elves", "set": "fdn", "collector_number": "227", "finish": "nonfoil",
                "quantity": "1", "borrower": PRIVATE, "lent_on": "2026-11-11", "returned_on": "", "notes": PRIVATE}
        _write(self.box.magic / "people/user3/loans.csv", inventory_rules.csv_bytes([loan], loan_rules.FIELDS).decode())
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=accessories.FIELDS)
        writer.writeheader()
        writer.writerow({**dict.fromkeys(accessories.FIELDS, ""), "id": "private-probe-mat", "kind": "playmat",
                         "owner": "user3", "name": PRIVATE, "quantity": "1"})
        _write(self.box.magic / "accessories.csv", out.getvalue())
        actor = state.Actor("user3", "User3", "tunnel")
        record = _game(RECORD, (DECK, PRIVATE), ("user3/casual/other", PRIVATE))
        record["space"], record["notes"] = "user3", PRIVATE
        self.box.state.play_put("games", record, None, actor, PRIVATE)
        plan = {key: value for key, value in record.items() if key not in ("sides", "date", "result", "space")}
        plan.update(kind="sideboards", deck={"id": DECK, "version": "target", "sha256": "b" * 64, "title": PRIVATE},
                    opponent={"id": "user3/casual/other", "title": PRIVATE}, **{"out": [], "in": []})
        self.box.state.play_put("sideboards", plan, None, actor, PRIVATE)
        self.box.state.wishlist_add("user3", _entry("Llanowar Elves", notes=PRIVATE), actor, PRIVATE)
        def ranked(format, *, visible, **options):
            row = {"id": DECK, "space": "user3", "title": PRIVATE}
            return {"rows": [row] if visible(row) else []}
        self.box.forge.rankings = SimpleNamespace(FORMATS=("Constructed", "Commander"), view=ranked)
        self.box.forge.field_membership = SimpleNamespace(UNAVAILABLE="Membership unavailable",
            view=mock.Mock(side_effect=AssertionError("Hidden field reached its backend")))
        self.box.forge.lists = SimpleNamespace(one_snapshot=inventory.pinned)
        self.box.forge.group = SimpleNamespace(MAX_OPPONENTS=12)
        from decklab.tests.test_gauntlet_api import FakeGauntlet
        self.box.forge.gauntlet = FakeGauntlet(self.box.forge, self.box.data / "no-gauntlet-results")
        self.box.forge.gauntlet.built = False
        self.box.forge.variants = SimpleNamespace(run_test=mock.Mock(side_effect=AssertionError("A run started")),
            load_summary=lambda *args: None, view=lambda *args, **kwargs: None,
            gauntlet_tests=SimpleNamespace(results_dir=lambda: self.box.data / "no-results"))
        # A missing guard must never reach external I/O, a worker, or an actual fixture write.
        for owner, name in ((subprocess, "Popen"), (subprocess, "run"), (socket, "create_connection"),
                            (jobs.Runner, "submit"), (inventory, "apply")):
            self.enterContext(mock.patch.object(owner, name, side_effect=AssertionError("Probe escaped read-only fixture scope")))

    def test_every_method_path_has_one_known_explicit_access_class(self):
        gets, posts = feature_routes.route_tables()
        actual = {(method, "/".join(route)) for method, rows in (("GET", gets), ("POST", posts)) for route in rows}
        self.assertEqual(actual, set(feature_routes.ACCESS))
        self.assertTrue(set(feature_routes.ACCESS.values()) <= CLASSES)
        for method, path in actual:
            self.assertEqual(feature_routes.declared_access(method, path.split("/")), feature_routes.ACCESS[(method, path)])
        with self.assertRaises(RuntimeError):
            feature_routes.declared_access("POST", ("future", "unreviewed"))

    def test_legacy_fixed_branches_and_write_tables_are_in_the_reviewed_inventory(self):
        source = (ROOT / "decklab/lib/server_http.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name) \
                    and node.test.left.id == "route" and len(node.test.comparators) == 1 \
                    and isinstance(node.test.comparators[0], ast.List):
                route = ast.literal_eval(node.test.comparators[0])
                path = "/api/" + "/".join(route)
                for call in (item for item in ast.walk(node) if isinstance(item, ast.Call)
                             and isinstance(item.func, ast.Attribute) and item.func.attr == "_allow"):
                    for arg in call.args:
                        if isinstance(arg, ast.Starred):
                            found.add(("GET", path))
                        elif isinstance(arg, ast.Constant):
                            found.add((arg.value, path))
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict) and any(
                    isinstance(name, ast.Name) and name.id in {"writes", "matchup_writes", "coord_writes"} for name in node.targets):
                found.update(("POST", "/api/" + "/".join(ast.literal_eval(key))) for key in node.value.keys)
        dynamic = {(method, f"/api/profiles/{{profile}}/{kind}") for kind, methods in (
            ("settings", ("GET", "PUT")), ("wishlist", ("GET", "POST"))) for method in methods}
        files = {("GET", path) for path in ("/img/{set}/{number}/{size}", "/symbols/{symbol}",
                 "/accessory-img/{name}", "/accessory-img/staged/{token}", "/{static-file}")}
        self.assertEqual(found | dynamic | files, set(feature_routes.LEGACY_ACCESS))
        self.assertEqual(feature_routes.LEGACY_ACCESS[("GET", "/img/{set}/{number}/{size}")], "open")
        self.assertTrue(set(feature_routes.LEGACY_ACCESS.values()) <= CLASSES)

    def test_route_dictionaries_have_no_silently_overwritten_keys(self):
        tree = ast.parse((ROOT / "decklab/lib/feature_routes.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            names = {name.id for name in node.targets if isinstance(name, ast.Name)}
            if not names & {"ACCESS", "LEGACY_ACCESS", "gets", "posts"}:
                continue
            value = node.value.args[0] if isinstance(node.value, ast.Call) else node.value
            keys = [ast.literal_eval(key) for key in value.keys]
            self.assertEqual(len(keys), len(set(keys)), names)

    def test_security_document_tracks_every_source_migration(self):
        text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        for path in (ROOT / "decklab/db/migrations").glob("*.sql"):
            self.assertIn(path.name, text, f"Security migration inventory omits {path.name}")

    def query(self, route):
        params = {"id": DECK, "deck": DECK, "version": "target", "space": "user3", "a": DECK,
                  "av": "target", "b": "user2/casual/r-elves", "bv": "target", "q": "ROUTE_PRIVATE",
                  "name": "Llanowar Elves", "file": "TestDinos_TST", "order": "fixture-order", "stem": "fixture-product",
                  "revision": "1", "sha256": "b" * 64, "format": "commander", "row": "1"}
        if route[:1] == ("activity",):
            params["id"] = "1"
        if route in (("play", "sideboard-preview"), ("play", "sideboard-tests")):
            params["id"] = RECORD
        if route in (("deck", "edhrec"), ("deck", "wishlist")):
            params.pop("space")
        if route == ("rankings",):
            params["format"] = "Constructed"
        return params

    def value(self, key, who):
        selected = {"id": DECK, "version": "target", "sha256": "b" * 64}
        values = {"profile": who, "space": "user3", "id": DECK, "version": "target", "sha256": "b" * 64,
                  "a": selected, "b": selected, "deck": selected, "source": DECK, "opponent": selected,
                  "decks": [{"id": DECK, "version": "target"}], "date": "2026-11-11", "notes": "Fixture",
                  "reason": "Fixture reason", "confirmed": True, "confirm_owned": True, "preview": True,
                  "file": "TestDinos_TST", "title": "Fixture", "kind": "casual", "action": "edit",
                  "ids": ["fixture-notice"], "rows": [], "fields": {}, "expect": {}, "fingerprint": "b" * 64,
                  "list": {"Deck": [{"name": "Llanowar Elves", "qty": 4}]}, "key": "b" * 64,
                  "samples": [], "changes": [], "record": {"id": RECORD}, "result": "a", "seats": [], "row": {}}
        values.update(mode="pod", game_version=2, test="b" * 64,
                      holder=DECK, field="sleeves", holder_sha256="b" * 64,
                      seats=[{"seat_id": name, "type": "deck", "player": "Fixture", "deck": selected}
                             for name in ("s1", "s2", "s3")])
        return values.get(key)

    def probe(self, method, route, who, access_class, *, source_id=1, legacy_path=None):
        observed = []
        watched = proof_codes()
        def trace(frame, event, arg):
            if event == "call" and frame.f_code in watched:
                observed.append(frame.f_code.co_name)
        body = {"profile": who, "space": "user3", "id": DECK}
        if access_class == "profile" and who is not None:
            body["profile"] = "user3"     # another profile's state, not the caller's own notices
        if route[:1] == ("play",):
            body["id"] = RECORD
        if route[:1] == ("activity",):
            body["id"] = source_id
        if route[:1] == ("accessories",):
            body["id"] = None if route == ("accessories", "assign") else "private-probe-mat"
        if route == ("accessories", "save"):
            body["action"] = "edit"
            body["sha256"] = None      # this fixture has no accessory rows visible to these viewers
        if legacy_path == "/api/visibility":
            body = {"profile": who, "owner": "user3", "thing": "collection", "public": True}
        if legacy_path and "{profile}" in legacy_path:
            body = {"theme": "dark"} if legacy_path.endswith("settings") else {"action": "add", "name": "Llanowar Elves"}
        if legacy_path in ("/api/deck/check", "/api/deck/save"):
            body.pop("space")
        if legacy_path == "/api/tables/update":
            body["decks"] = [{"id": DECK, "sha256": "b" * 64}]
        for _ in range(20):
            prior = sys.getprofile()
            try:
                sys.setprofile(trace)
                with requester(who):
                    handler = ProbeHandler(method, self.query(route), body,
                                           path=legacy_path.replace("{profile}", "user3") if legacy_path else None)
                    if legacy_path:
                        if route == ("variant",):
                            handler.params["test"] = "b" * 64
                        server_http.Handler._route(handler)
                    else:
                        feature_routes.dispatch(handler, route, "")
                status, answer = handler.answer
            except ApiError as error:
                status, answer = error.status, {"error": error.message}
            finally:
                sys.setprofile(prior)
            message = (answer.get("error") or "") if isinstance(answer, dict) else ""
            missing = re.fullmatch(r"The request needs (.+)", message)
            unknown = re.match(r"Unknown key ('[^']*')", message)
            if method in ("POST", "PUT") and status == 400 and missing:
                for key in missing.group(1).split(", "):
                    body[key] = self.value(key, who)
                continue
            if method in ("POST", "PUT") and status == 400 and unknown:
                key = ast.literal_eval(unknown.group(1))
                if key in body:
                    body.pop(key)
                    continue
            return status, answer, observed
        self.fail(f"{method} {'/'.join(route)} needs a bounded probe body")

    def test_every_nonopen_feature_route_rejects_or_filters_cross_space_requests(self):
        before = self.persisted()
        failures = []
        for (method, path), access_class in feature_routes.ACCESS.items():
            if access_class == "open":
                continue
            route = tuple(path.split("/"))
            viewers = (None, "user2", "user1", "matt") if access_class in {
                "inventory", "inventory-edit", "deck", "deck-edit", "draft", "play", "accessories", "profile"} \
                else (None, "user2", "user1")
            for who in viewers:
                with self.subTest(method=method, path=path, viewer=who):
                    status, answer, observed = self.probe(method, route, who, access_class)
                    self.assertNotIn(PRIVATE, json.dumps(answer))
                    strict = access_class in {"admin", "home-admin", "inventory", "inventory-edit", "draft", "deck", "deck-edit", "deck-run"}
                    strict |= access_class == "home-records" and who in (None, "user2")
                    strict |= method == "POST" and access_class in {"play", "accessories"}
                    if strict and status not in (403, 404):
                        failures.append((method, path, who, status, answer, bool(observed)))
                    # This backend has no supported inventory inverse for a game audit. Its fixed
                    # refusal must be identical for missing sources, as checked separately below.
                    ineligible = route == ("activity", "undo") and status == 400 and answer.get("error") == activity_undo.UNSUPPORTED
                    if method == "POST" and status not in (403, 404) and not observed and not ineligible:
                        failures.append((method, path, who, status, answer, "no access decision observed"))
        self.assertEqual(failures, [], "\n".join(str(row) for row in failures))
        self.assertEqual(self.persisted(), before)

    def test_unsupported_inverse_discloses_nothing_about_a_hidden_source(self):
        for who in ("user2", "user1"):
            existing = self.probe("POST", ("activity", "undo"), who, "activity", source_id=1)
            missing = self.probe("POST", ("activity", "undo"), who, "activity", source_id=999999)
            self.assertEqual(existing[:2], missing[:2])

    def test_public_inventory_never_widens_loan_detail_routes(self):
        before = self.persisted()
        with mock.patch.object(guard, "public_spaces", return_value=frozenset({"user3"})):
            for who in (None, "user2", "user1", "matt"):
                for method, path in (("GET", "collection/loans"), ("POST", "collection/lend"), ("POST", "collection/return")):
                    with self.subTest(viewer=who, method=method, path=path):
                        status, answer, _ = self.probe(method, tuple(path.split("/")), who, feature_routes.ACCESS[(method, path)])
                        self.assertEqual(status, 403)
                        self.assertNotIn(PRIVATE, json.dumps(answer))
        self.assertEqual(self.persisted(), before)

    def test_public_inventory_never_publishes_private_other_deck_category_choices(self):
        before = self.persisted()
        with mock.patch.object(guard, "public_spaces", return_value=frozenset({"user3"})):
            for who in (None, "user2", "user1", "matt"):
                with self.subTest(viewer=who):
                    status, answer, _ = self.probe("GET", ("cards", "categories"), who, "inventory")
                    self.assertEqual(status, 403)
                    self.assertNotIn(PRIVATE, json.dumps(answer))
                    self.assertNotIn("categories", answer)
        self.assertEqual(self.persisted(), before)

    def test_legacy_private_routes_keep_their_existing_cross_space_boundaries(self):
        before = self.persisted()
        failures = []
        for (method, path), access_class in feature_routes.LEGACY_ACCESS.items():
            if access_class == "open" or not path.startswith("/api/"):
                continue
            route = tuple(path.removeprefix("/api/").split("/"))
            viewers = (None, "user2", "user1", "matt") if access_class in {
                "inventory", "inventory-edit", "deck", "deck-edit", "draft", "play", "accessories", "profile"} \
                else (None, "user2", "user1")
            for who in viewers:
                with self.subTest(method=method, path=path, viewer=who):
                    status, answer, observed = self.probe(method, route, who, access_class, legacy_path=path)
                    self.assertNotIn(PRIVATE, json.dumps(answer))
                    strict = access_class in {"admin", "home-admin", "inventory", "inventory-edit", "deck", "deck-edit", "deck-run"}
                    strict |= access_class == "home-records" and who in (None, "user2")
                    strict |= "{profile}" in path
                    if strict and status not in (403, 404):
                        failures.append((method, path, who, status, answer, observed))
        self.assertEqual(failures, [], "\n".join(str(row) for row in failures))
        self.assertEqual(self.persisted(), before)
