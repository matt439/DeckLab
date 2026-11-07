"""Disposable rendered-review data and HTTP worker; never production startup.

Imports are standard library only. The CLI installs fixture guards before importing
application code. Tests may use review_fixture inside their already guarded process.
Result JSON is invented renderer input, not simulation or authentication acceptance.
"""
import argparse
import contextlib
import copy
import ipaddress
import json
import os
import re
import sys
import time
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

REPO = Path(__file__).resolve().parents[2]
FIXTURE_TYPE = "decklab-ui-review-v1"
HOME = "casual/safari-fixture"
MEMBER = "user2/casual/member-fixture"
HOME_TEST = "a" * 64
MEMBER_TEST = "b" * 64
PAIR_KEY = "d" * 64
PROFILES = ("matt", "user2")
CASES = ("complete", "stale", "failed", "running", "unknown-counts", "library-failed")
FORGE = {"ok": True, "installed": True, "version": "synthetic-review", "error": None, "workers": 1}


def _write_json(path, value):
    """Publish a complete control record, so a polling parent never sees half JSON."""
    pending = path.with_name(path.name + ".pending")
    pending.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)


def validate_runtime(runtime, run_id, *, _fresh=True):
    """Accept only the parent's new, explicitly marked runtime directory."""
    if not isinstance(run_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{16,128}", run_id) is None:
        raise ValueError("Review run id must contain 16 to 128 safe characters")
    supplied = Path(runtime)
    if not supplied.is_absolute() or supplied.is_symlink():
        raise ValueError("Review runtime must be an absolute, unlinked directory")
    runtime = supplied.resolve(strict=True)
    if not runtime.is_dir() or runtime == Path(runtime.anchor) or runtime.is_relative_to(REPO):
        raise ValueError("Review runtime must be a new temporary directory outside the checkout")
    expected = {"fixture_type": FIXTURE_TYPE, "run_id": run_id}
    marker = runtime / "owner.json"
    if marker.is_symlink() or not marker.is_file() or marker.stat().st_size > 1024:
        raise ValueError("Review runtime lacks its parent's ownership marker")
    try:
        owner = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("Review runtime ownership marker is invalid") from error
    initial = {p.name for p in runtime.iterdir()}
    log = runtime / "fixture.log"
    if owner != expected or (_fresh and not {"owner.json"} <= initial <= {"owner.json", "fixture.log"}) \
            or ("fixture.log" in initial and (log.is_symlink() or not log.is_file())):
        raise ValueError("Review runtime is not a fresh directory owned by this run")
    return runtime


def worker_audit(event, args):
    """Dedicated-worker accident guard; installed only by main, never at import."""
    if event in {"socket.connect", "socket.bind", "socket.sendto", "socket.sendmsg"}:
        address = args[1]
        if not isinstance(address, tuple) or not address:
            raise RuntimeError("Review fixture permits loopback sockets only")
        try:
            local = ipaddress.ip_address(address[0]).is_loopback
        except ValueError:
            local = address[0] == "localhost"
        if not local:
            raise RuntimeError("Review fixture denies non-loopback access")
    if event in {"socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyname_ex", "socket.gethostbyaddr"} \
            and args[0] not in {None, "127.0.0.1", "::1", "localhost"}:
        raise RuntimeError("Review fixture denies external DNS")
    if event == "socket.getnameinfo":
        try:
            local = ipaddress.ip_address(args[0][0]).is_loopback
        except (ValueError, TypeError, IndexError):
            local = False
        if not local:
            raise RuntimeError("Review fixture denies external reverse DNS")
    if event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.spawn", "os.exec", "pty.spawn"}:
        raise RuntimeError("Review fixture denies child processes")


def install_worker_audit():
    """Fail closed if an earlier audit hook silently refuses this registration."""
    marker, installed = object(), False

    def audit(event, args):
        nonlocal installed
        if event == "decklab.ui_review.audit.ready" and args == (marker,):
            installed = True
        worker_audit(event, args)

    sys.addaudithook(audit)
    sys.audit("decklab.ui_review.audit.ready", marker)
    if not installed:
        raise RuntimeError("Review worker accident guards could not be installed")


def _template(name):
    return json.loads(Path(__file__).with_name("data").joinpath(name + ".json").read_text(encoding="utf-8"))


def variant_payload(member=False, case="complete"):
    answer = _template("variant")
    test = answer["test"]
    test["test"] = MEMBER_TEST if member else HOME_TEST
    test["base"].update(id=MEMBER if member else HOME,
                        title="Synthetic member woodland deck" if member else "Synthetic home woodland deck")
    test["by"] = "User2" if member else "Matt"
    if case == "failed":
        answer.update(status="error", verdict="error", words="This synthetic test failed",
                      error="Synthetic fixture: no games could be read.")
        test.update(outcome="error", looks=[])
    elif case == "running":
        answer.update(status="running", verdict=None, words=None,
                      job={"status": "running", "done": 200, "total": 1600, "next_look": 400,
                           "seconds": 90, "ahead": 0, "pairs": {}, "may_stop": False,
                           "range": {"delta": .02, "low": -.03, "high": .07}})
    return answer


def board_payload(fmt):
    return _template("board-commander" if fmt == "commander" else "board-constructed")


def pair_payload(case="complete"):
    answer = _template("pair")
    if case == "stale":
        answer["sides"][0]["current"] = False
    elif case == "failed":
        answer.update(status="error", result=None, error="Synthetic fixture: the saved run failed.")
    return answer


def _control(path, permitted, default):
    if not path.exists():
        return default
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64:
        raise RuntimeError("Review control is not a bounded regular file")
    value = path.read_text(encoding="utf-8").strip()
    if value not in permitted:
        raise RuntimeError("Review control contains an unsupported value")
    return value


def _seed_kept_draft(fixture):
    """Keep a real MemoryStore draft from the fresh synthetic edit response."""
    with urlopen(fixture.base_url + "/api/deck/edit?id=" + HOME, timeout=10) as response:
        current = json.load(response)
    fields = {key: value for key, value in current["fields"].items() if key != "format"}
    base_lists = {section: [{key: value for key, value in row.items()
                             if key in {"qty", "name", "set", "number"}} for row in rows]
                  for section, rows in current["lists"]["target"].items() if section != "considering"}
    draft_lists = copy.deepcopy(base_lists)
    forest = next(row for row in draft_lists["Deck"] if row["name"] == "Forest")
    if forest["qty"] != 52:
        raise RuntimeError("Fresh review fixture must begin with 52 Forest")
    forest["qty"] = 53
    prose = {key: value or "" for key, value in current["prose"].items()}
    content = {"v": 1, "saved": 946684800000, "sha256": current["sha256"], "starting": False,
               "base": {"lists": base_lists, "fields": fields, "prose": prose, "considering": []},
               "lists": draft_lists, "fields": copy.deepcopy(fields), "addSection": "Deck",
               "considering": [], "consideringMoves": [], "promotionReview": False,
               "promotionAccepted": None, "promotionAcknowledged": None, "promotionUnavailable": False,
               "prose": copy.deepcopy(prose), "markCurrent": False}
    fixture.state.deck_draft_put("matt", HOME, "target", content, 0, device="Synthetic review device")


def _install_handler(fixture, runtime, run_id):
    base_handler = fixture.httpd.RequestHandlerClass
    profile_path, case_path = runtime / "profile.txt", runtime / "case.txt"

    class ReviewHandler(base_handler):
        def _identify(self, host):
            who = _control(profile_path, PROFILES, "matt")
            return {"profile": who, "email": f"{who}@example.com", "remote": True}

        def _route(self):
            from decklab.lib.api import ApiError

            split = urlsplit(self.path)
            path, query = split.path, parse_qs(split.query)
            if self.command not in {"GET", "HEAD"}:
                if self.command != "POST" or path != "/api/deck/check":
                    raise ApiError(403, "This synthetic review fixture permits only reads and dry-run deck checks.")
                return super()._route()
            if path == "/_ui_review/ready":
                if self.headers.get("X-DeckLab-Review-Run") != run_id:
                    raise ApiError(403, "Review identity challenge did not match this disposable run.")
                return self._send_json(200, {"fixture_type": FIXTURE_TYPE, "run_id": run_id, "isolated": True})
            case = _control(case_path, CASES, "complete")
            if path == "/api/activity":
                from .family_data import activity

                return self._send_json(200, activity())
            if path in {"/api/settings/maintenance", "/api/visits", "/api/settings/members"}:
                from .family_data import settings

                return self._send_json(200, settings(path))
            if path == "/api/decks" and case == "library-failed":
                return self._send_json(503, {"error": "Synthetic fixture: the deck library could not be read.",
                                             "reason": "database"})
            if path == "/api/variant":
                from decklab.lib.api import variant_page

                answer = variant_payload(query.get("test", [HOME_TEST])[0] == MEMBER_TEST, case)
                answer["may_edit"] = variant_page._may_edit(answer["test"]["base"]["id"])
                return self._send_json(200, answer)
            wishlist = re.fullmatch(r"/api/profiles/(matt|user2)/wishlist", path)
            if wishlist:
                from decklab.lib.api import wishlists

                answer = wishlists.get_wishlist(wishlist[1])
                if case == "unknown-counts":
                    for entry in answer["entries"]:
                        entry["have"] = {"owned": None, "on_the_way": None}
                    answer["warnings"].append("Synthetic fixture: collection counts unavailable.")
                return self._send_json(200, answer)
            if path == "/api/matchup":
                return self._send_json(200, pair_payload(case))
            if path == "/api/matchups":
                running = ([{"key": "synthetic-shell-run", "status": "running", "kind": "gauntlet",
                             "title": "Synthetic shell run", "done": 200, "total": 1600, "may_stop": False}]
                           if case == "running" else [])
                return self._send_json(200, {"running": running, "results": [], "choices": [200, 400, 800, 1600, 3200],
                                             "default_games": 800, "forge": FORGE, "workers": 1, "batch_size": 25})
            if path == "/api/gauntlet/board":
                if case == "failed":
                    return self._send_json(503, {"error": "Synthetic fixture: popular board unavailable."})
                return self._send_json(200, board_payload(query.get("format", ["commander"])[0]))
            if path == "/api/library/forge":
                return self._send_json(200, {"decks": {}, "forge": FORGE})
            if path in {"/api/field", "/api/variants"}:
                return self._send_json(200, {"results": [], "tests": [], "rows": [], "forge": FORGE})
            if path == "/api/gauntlet/summary":
                return self._send_json(200, {"overall": None, "played": 0, "of": 20, "games": 0})
            if path == "/api/gauntlet":
                return self._send_json(200, {"catalogue": False, "format": "constructed", "build_command": None})
            if path == "/api/gauntlet/catalogue":
                return self._send_json(200, {"built": None, "format": query.get("format", ["commander"])[0],
                                             "build_command": None, "standard": None})
            return super()._route()

    fixture.httpd.RequestHandlerClass = ReviewHandler
    fixture.httpd.remote = True  # Synthetic identity adapter only, never authentication acceptance.


@contextlib.contextmanager
def review_fixture(runtime, run_id, *, lifecycle=None, _validated=False):
    """Real web assets over disposable inventory; restore all patches on exit.

    Call only inside a dedicated worker or the guarded fixture test runner. This
    context changes the same process-global app backends as FixtureServer.
    """
    # The CLI validates freshness before install(), whose guarded test support may
    # create its own temporary log/slot directories under the parent's TMPDIR.
    # Still verify marker, nonce and path after install; only that internal call
    # skips the second empty-directory check. Direct factory calls stay strict.
    runtime = validate_runtime(runtime, run_id, _fresh=not _validated)
    from decklab.safari import fixture_data
    from decklab.safari.fixture import FixtureServer

    config = copy.deepcopy(fixture_data.CONFIG)
    config["profiles"].append({"id": "user2", "name": "User2", "role": "member", "space": "user2",
                               "emails": ["user2@example.com"]})
    from . import composition_data
    original_rows = fixture_data.card_rows
    with mock.patch.object(fixture_data, "CONFIG", config), \
            mock.patch.object(fixture_data, "card_rows", lambda: composition_data.card_rows(original_rows)), \
            mock.patch("tempfile.tempdir", str(runtime)), FixtureServer() as fixture:
        if lifecycle is not None:
            lifecycle["root"] = fixture.root
            lifecycle["fixture"] = fixture
        home_path = fixture.root / f"magic/decks/{HOME}.md"
        text = fixture_data.DECK.replace("# Safari Fixture", "# Synthetic home woodland deck", 1)
        text = text.replace("## Notes\n", "## Notes\n\n### Game plan\n\n"
                            "Develop mana with the Elves, then use the extra mana for your threats.\n", 1)
        home_path.write_text(text, encoding="utf-8")
        member_path = fixture.root / "magic/people/user2/decks/casual/member-fixture.md"
        member_path.parent.mkdir(parents=True, exist_ok=True)
        member_text = text.replace("# Synthetic home woodland deck", "# Synthetic member woodland deck").replace(
            "- **Played by:** user\n", "")
        member_path.write_text(member_text, encoding="utf-8")
        (fixture.root / "magic/people/user2/collection.csv").write_text(fixture_data.COLLECTION, encoding="utf-8")
        from decklab.lib import purchases
        from decklab.lib.state import Actor

        (fixture.root / "magic/watchlist.csv").write_text(",".join(purchases.QUEUE_FIELDS) + "\n", encoding="utf-8")
        fixture.state._seeded_mode["mode"] = "everyone"  # UI branches only; every simulation mutation is refused.
        fixture.state.visibility_set("home", "decks", True, Actor("matt", "Matt"),
                                     "Synthetic fixture public-deck control")
        for name in ("Llanowar Elves", "Forest"):
            fixture.state.wishlist_add("matt", {"name": name, "set": "", "number": "",
                "notes": "Synthetic saved note: keep me after Zoom.",
                "source": "magic/buylists/2000-01-01-synthetic-suggestions.md"},
                Actor("matt", "Matt"), "Seed disposable review wishlist")
        for deck_id, body in ((HOME, text), (MEMBER, member_text)):
            fixture.inventory._remember(deck_id, body, "matt", "Create synthetic UI fixture", "A")
        composition_data.seed(fixture, text)
        from . import family_data
        family_data.seed(fixture)
        from . import receipt_data
        receipt_data.seed(fixture)
        (runtime / "profile.txt").write_text("matt\n", encoding="utf-8")
        (runtime / "case.txt").write_text("complete\n", encoding="utf-8")
        _install_handler(fixture, runtime, run_id)
        _seed_kept_draft(fixture)
        fixture.runtime = runtime
        fixture.ready = {"fixture_type": FIXTURE_TYPE, "run_id": run_id, "pid": os.getpid(),
                         "base_url": fixture.base_url, "root": str(fixture.root),
                         "profile_control": str(runtime / "profile.txt"), "profile_values": list(PROFILES),
                         "case_control": str(runtime / "case.txt"), "case_values": list(CASES),
                         "stop_file": str(runtime / "stop"),
                         "routes": {"home_variant": f"/#/variant?test={HOME_TEST}",
                                    "member_variant": f"/#/variant?test={MEMBER_TEST}",
                                    "board": "/#/matchups?view=popular", "pair": f"/#/matchup?key={PAIR_KEY}",
                                    "editor": "/#/edit?id=casual%2Fsafari-fixture&v=target",
                                    "wishlist": "/#/wishlist", "library": f"/#/library?deck={HOME}",
                                    "populated_library": f"/#/library?deck={composition_data.COMMANDER}",
                                    "commander": f"/#/deck?id={composition_data.COMMANDER}",
                                    "casual": f"/#/deck?id={HOME}",
                                    "empty_deck": f"/#/deck?id={composition_data.EMPTY}",
                                    "commander_guide": f"/#/deck?id={composition_data.COMMANDER}&part=guide",
                                    "guide": "/#/deck?id=casual%2Fsafari-fixture&part=guide",
                                    "large_receipt": f"/#/receipt?order={receipt_data.LARGE}",
                                    "split_receipt": f"/#/receipt?order={receipt_data.SPLIT}",
                                    "receipt": f"/#/receipt?order={fixture.order_id}"}}
        yield fixture


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    runtime = validate_runtime(args.runtime, args.run_id)
    from scripts.fixture_runtime import install

    install(REPO)  # BEFORE any application imports.
    install_worker_audit()
    started, lifecycle = time.monotonic(), {}
    cleanup = {"fixture_type": FIXTURE_TYPE, "run_id": args.run_id, "stopped": False,
               "temporary_root_removed": False}
    try:
        with review_fixture(runtime, args.run_id, lifecycle=lifecycle, _validated=True) as fixture:
            _write_json(runtime / "ready.json", fixture.ready)
            while not (runtime / "stop").exists():
                if time.monotonic() - started > 1800:
                    raise TimeoutError("Review fixture exceeded its 30 minute lifetime")
                time.sleep(.1)
        cleanup["stopped"] = True
    finally:
        root = lifecycle.get("root")
        fixture = lifecycle.get("fixture")
        cleanup["stopped"] = fixture is not None and not fixture.thread.is_alive()
        cleanup.update(pid=os.getpid(), root=str(root) if root else None,
                       temporary_root_removed=root is not None and not root.exists(),
                       elapsed_seconds=round(time.monotonic() - started, 2))
        _write_json(runtime / "cleanup.json", cleanup)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
