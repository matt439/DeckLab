"""Real HTTP/UI over disposable data, with no production startup or network fetches.

Use only in a dedicated test process: the application stores its backend and paths
process-wide. The context restores them after stopping its HTTP thread. No server.main(),
database, live config, household cards, tunnel, updater or Forge worker is started.
"""
import contextlib
import hashlib
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from unittest import mock

from . import fixture_data as data

SOURCE_ROOT = Path(__file__).resolve().parents[2]


def _forbidden(*args, **kwargs):
    raise RuntimeError("The Safari fixture forbids databases, downloads and simulation workers")


def _history_inventory(root):
    """FileInventory's ordinary write path plus fixture-only in-memory history.

    FileInventory deliberately has no history. Keep the real editor/history HTTP APIs
    under test without adding a database dependency or changing that backend's contract.
    """
    from decklab.lib.inventory.files import FileInventory
    from decklab.lib.inventory.model import DeckRevision

    class FixtureInventory(FileInventory):
        def __init__(self):
            super().__init__(root)
            self.history = {}
            for deck in self.load().decks.values():
                self._remember(deck.id, deck.text, "matt", "Create disposable Safari fixture", "A")

        def _remember(self, deck_id, text, actor, message, op):
            revisions = self.history.setdefault(deck_id, [])
            revisions.insert(0, DeckRevision(deck_id, len(revisions) + 1, datetime.now(timezone.utc),
                                            actor, message, op, text=text))

        def apply(self, op, actor, message, reason=None, expected_revision=None):
            with self._lock:
                before = dict(self.load().decks)
                after, summary = super().apply(op, actor, message, reason, expected_revision)
                current = dict(after.decks)
                for deck_id in before.keys() | current.keys():
                    old, new = before.get(deck_id), current.get(deck_id)
                    if old != new:
                        self._remember(deck_id, new.text if new else None, actor.id, message,
                                       "D" if new is None else "M" if old else "A")
                return after, summary

        def deck_revisions(self, deck_id):
            with self._lock:
                return list(self.history.get(deck_id, []))

        def deck_revision(self, deck_id, number):
            return next((r for r in self.deck_revisions(deck_id)
                         if r.revision == number or r.git_commit == number), None)

        def last_revision(self, deck_id):
            return next(iter(self.deck_revisions(deck_id)), None)

    return FixtureInventory()


class FixtureServer:
    """Disposable HTTP/UI context; allow_precons opts into seeded local lists only.

    Precons remain blocked by default. Even when enabled, their cache is temporary
    and downloads are forbidden, as are databases and simulation workers.
    """
    deck_id = data.DECK_ID
    order_id = data.ORDER_ID
    profile_id = data.PROFILE_ID
    profile_name = data.PROFILE_NAME

    def __init__(self, *, allow_precons=False):
        if not isinstance(allow_precons, bool):
            raise ValueError("allow_precons must be a boolean")
        self._stack = contextlib.ExitStack()
        self.logs = []
        self._generation = 0
        self.root = None
        self.base_url = None
        self._allow_precons = allow_precons

    def __enter__(self):
        try:
            self._start()
        except BaseException:
            self._stack.close()
            raise
        return self

    def __exit__(self, *exc):
        self._stack.close()
        return False

    def _patch(self, target, name, value):
        self._stack.enter_context(mock.patch.object(target, name, value))

    def advance_version(self):
        """Make status newer than an already loaded page; reload gets the new HTML token."""
        self._generation += 1
        return self.web_revision

    @property
    def web_revision(self):
        return hashlib.sha256(f"safari-fixture-web-{self._generation}".encode()).hexdigest()

    def _build_status(self):
        return {"running_commit": None, "latest_commit": None, "started_at": None,
                "running_dirty": False, "latest_dirty": False, "restart_required": False,
                "assets_changed": self._generation > 0, "code_changed": self._generation > 0,
                "web_revision": self.web_revision,
                "running_web_revision": hashlib.sha256(b"safari-fixture-web-0").hexdigest(),
                "error": None}

    def _start(self):
        self.root = Path(self._stack.enter_context(tempfile.TemporaryDirectory(prefix="decklab-safari-")))
        data.seed(self.root)
        cache = self.root / "decklab/data"
        # Install fail-closed defaults before importing any request handlers or DB code.
        self._stack.enter_context(mock.patch.dict("os.environ", {
            "DECKLAB_STATE_EXPLICIT": "1", "DECKLAB_DB_NAME": "decklab_safari_must_not_connect",
            "DECKLAB_DB_LOG": str(cache / "db.log"), "DECKLAB_STATE_FILE": str(cache / "server.json"),
            "DECKLAB_FORGE_SLOTS": str(cache / "forge-slots"), "DECKLAB_CONFIG_EXTRA": ""}))
        from decklab.lib import config
        for name, value in (("REPO", self.root), ("DECKLAB", self.root / "decklab"),
                            ("DATA", cache), ("MAGIC", self.root / "magic"),
                            ("CONFIG_FILE", self.root / "config.json")):
            self._patch(config, name, value)
        from decklab.lib import cards, inventory, precons, state
        from decklab.lib.state.memory import MemoryStore
        for name, value in (("CACHE", cache / "mtgjson"), ("_fetch", _forbidden), ("_failed", {}), ("_kept", {})):
            self._patch(precons, name, value)
        for name, value in (("SCRYFALL_DIR", cache / "scryfall"),
                            ("INDEX_FILE", cache / "scryfall/index.json.gz"),
                            ("FX_FILE", cache / "fx.json"), ("IMAGES_DIR", cache / "images"),
                            ("_index", None), ("_download", _forbidden), ("_open_url", _forbidden),
                            ("update", _forbidden), ("usd_to_aud", lambda: (1.0, "2000-01-01"))):
            self._patch(cards, name, value)
        index = cards.build_index(cache / "scryfall/cards.jsonl", cache / "scryfall/tags.jsonl",
                                  log=lambda *a: None)
        index["built_at"] = "2000-01-01T00:00:00+00:00"
        cards.write_index(index, cards.INDEX_FILE)
        image = Path(__file__).with_name("card.jpg")
        for size in ("small", "normal", "large", "art_crop"):
            for number in range(1, 5):
                dest = cards.IMAGES_DIR / size / "sft" / f"{number}.jpg"
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(image, dest)
        self.state = MemoryStore(mode="paused")
        self._stack.callback(state.use(self.state))
        self.inventory = _history_inventory(self.root)
        self._stack.callback(inventory.use(self.inventory))
        self._configure_http(cache)

    def _configure_http(self, cache):
        from decklab.lib import accessories, api, build, dbstatus, decks, server_http, tokens, visits
        from decklab.lib.api import symbols
        from decklab.db import conn
        for target, name, value in (
                (decks, "DECKS_DIR", self.root / "magic/decks"),
                (accessories, "PATH", self.root / "magic/accessories.csv"),
                (accessories, "IMAGES", self.root / "magic/accessories/images"),
                (conn, "LOG_FILE", cache / "db.log"), (conn, "connect", _forbidden),
                (api.common, "_log", self.logs.append), (server_http, "log", self.logs.append),
                (dbstatus, "view", lambda *a, **k: {"ok": True, "usable": True}),
                (build, "web_revision", lambda: self.web_revision),
                (build, "status", self._build_status),
                (api.deck_page, "_deck_practice", lambda *a: None),
                (api.deck_page, "_deck_matchups", lambda *a: None),
                (api.practice, "_goldfish_module", _forbidden),
                (api.forge_runs, "_forge_module", _forbidden),
                (api.variant_page, "_forge_module", _forbidden),
                (api.simulations, "_slots", lambda: SimpleNamespace(limit=lambda: None, _budget=lambda _: 1)),
                (symbols, "SYMBOLS_DIR", cache / "symbols"),
                (symbols, "symbol_svg", lambda code: self._symbol(code))):
            self._patch(target, name, value)
        self._stack.callback(visits.use(visits.Recorder()))
        tokens.clear_cache()
        self._stack.callback(tokens.clear_cache)
        self.httpd = server_http.make_server("127.0.0.1", 0, web_dir=SOURCE_ROOT / "decklab/web")

        allow_precons = self._allow_precons  # Only explicit local fixtures may use seeded lists; fetching stays forbidden.

        class FixtureHandler(server_http.Handler):
            def _route(self):
                path = urlsplit(self.path).path
                blocked = ("/api/goldfish", "/api/matchups", "/api/matchup", "/api/field",
                           "/api/variant", "/api/variants", "/api/accessories/fetch")
                if not allow_precons:
                    blocked += ("/api/precons",)
                if any(path == prefix or path.startswith(prefix + "/") for prefix in blocked):
                    raise api.ApiError(403, "This disposable Safari fixture does not run simulations "
                                           "or fetch external data")
                return super()._route()

        self.httpd.RequestHandlerClass = FixtureHandler
        self.base_url = f"http://127.0.0.1:{self.httpd.server_port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="safari-fixture", daemon=True)
        self.thread.start()
        self._stack.callback(self._stop_http)

    @staticmethod
    def _symbol(code):
        # Small local SVGs keep mana/rules layouts intact without fetching Scryfall.
        from html import escape
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
                f'<circle cx="12" cy="12" r="11" fill="#abd3ad"/>'
                f'<text x="12" y="17" text-anchor="middle" font-size="14">{escape(code)}</text></svg>').encode()

    def _stop_http(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(5)
        if self.thread.is_alive():
            raise RuntimeError("The disposable Safari HTTP server did not stop")
