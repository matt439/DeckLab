"""The Simulator suite's HTTP fixture is safe to run on Windows, without Appium."""
import http.client
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from urllib.parse import urlsplit
from unittest import mock

from decklab.safari.fixture import FixtureServer


class SafariFixtureTests(unittest.TestCase):
    def request(self, fixture, path, payload=None, status=200):
        address = urlsplit(fixture.base_url)
        conn = http.client.HTTPConnection(address.hostname, address.port, timeout=10)
        headers = {"X-Deck-Lab-Viewer": fixture.profile_id, "Connection": "close"}
        body = None
        if payload is not None:
            headers.update({"X-Deck-Lab": "1", "Content-Type": "application/json"})
            body = json.dumps(payload)
        try:
            conn.request("GET" if payload is None else "POST", path, body, headers)
            response = conn.getresponse()
            content = response.read()
            self.assertEqual(response.status, status, content[:1000])
            return json.loads(content) if response.headers.get_content_type() == "application/json" else content
        finally:
            conn.close()

    def test_real_http_save_history_receipt_and_cleanup(self):
        # None of these production entry points is needed by the real HTTP/API stack.
        from decklab.db import conn
        from decklab.lib import config, cards, inventory, state
        from decklab import server
        old_config = config.CONFIG_FILE
        with mock.patch.object(conn, "connect", side_effect=AssertionError("database")) as db, \
                mock.patch.object(cards, "update", side_effect=AssertionError("update")) as update, \
                mock.patch.object(server, "main", side_effect=AssertionError("startup")) as startup:
            with FixtureServer() as fixture:
                root = fixture.root
                self.assertEqual(urlsplit(fixture.base_url).hostname, "127.0.0.1")
                self.assertNotEqual(urlsplit(fixture.base_url).port, 8642)
                self.assertEqual(config.CONFIG_FILE, root / "config.json")
                self.assertIs(inventory.backend(), fixture.inventory)
                self.assertIs(state.store(), fixture.state)
                status = self.request(fixture, "/api/status")
                self.assertTrue(status["cards"]["ready"])
                self.assertFalse(status["updating"])
                refused = self.request(fixture, f"/api/goldfish?id={fixture.deck_id}", status=403)
                self.assertIn("does not run simulations", refused["error"])
                self.assertEqual(self.request(fixture, "/api/profiles")["profiles"][0]["name"], "Matt")
                edit = self.request(fixture, f"/api/deck/edit?id={fixture.deck_id}")
                self.assertEqual(sum(row["qty"] for row in edit["lists"]["target"]["Deck"]), 60)
                payload = {"profile": fixture.profile_id, "id": fixture.deck_id,
                           "sha256": edit["sha256"], "fields": {"archetype": "Saved in disposable data"}}
                saved = self.request(fixture, "/api/deck/save", payload)
                self.assertTrue(saved["saved"])
                self.assertEqual(saved["deck"]["fields"]["archetype"], "Saved in disposable data")
                history = self.request(fixture, f"/api/deck/history?id={fixture.deck_id}")
                self.assertEqual(history["revisions"][0]["author"], "Matt")
                self.assertEqual(history["revisions"][0]["actor"], fixture.profile_id)
                self.assertEqual(len(history["revisions"]), 2)
                delivery = self.request(fixture, f"/api/receipt?order={fixture.order_id}")
                component = delivery["components"][0]
                self.assertEqual(len(component["rows"]), 3)
                picture = component["pictures"][0]["card"]["img"]
                self.assertTrue(self.request(fixture, picture).startswith(b"\xff\xd8"))
                before = fixture.inventory.load()
                preview = self.request(fixture, "/api/receipt/preview", {
                    "profile": fixture.profile_id, "order": fixture.order_id,
                    "fingerprint": delivery["fingerprint"], "received_on": "2000-01-02",
                    "components": [{"id": "cards", "verified": True}]})
                self.assertTrue(preview["ready"], preview)
                self.assertEqual(fixture.inventory.load(), before)
                received = self.request(fixture, "/api/receipt/apply", {
                    "profile": fixture.profile_id, "preview": preview["preview"]})
                self.assertTrue(received["received"])
                after = fixture.inventory.load()
                self.assertNotEqual(after.revision, before.revision)
                self.assertEqual(after.order(fixture.order_id).components[0].status, "received")
                self.assertFalse((root / "decklab/data/server.json").exists())
                self.assertFalse((root / "decklab/data/db.log").exists())
            self.assertFalse(root.exists())
            self.assertEqual(config.CONFIG_FILE, old_config)
            db.assert_not_called()
            update.assert_not_called()
            startup.assert_not_called()

    def test_repeatable_initial_data_and_page_version(self):
        initial = []
        for _ in range(2):
            with FixtureServer() as fixture:
                initial.append(fixture.inventory.load().decks_revision)
                old = fixture.web_revision
                self.assertIn(old.encode(), self.request(fixture, "/"))
                new = fixture.advance_version()
                self.assertNotEqual(old, new)
                self.assertEqual(self.request(fixture, "/api/status")["build"]["web_revision"], new)
                self.assertIn(new.encode(), self.request(fixture, "/"))
        self.assertEqual(initial[0], initial[1])

    def test_fresh_process_does_not_read_production_data(self):
        # Importing decklab.tests sets protective defaults. The runner does not import
        # that package, so exercise its first import in a process without those defaults.
        root = Path(__file__).resolve().parents[2]
        script = '''
import http.client, json
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit
from decklab.safari.fixture import FixtureServer
source = Path.cwd().resolve()
private = [source / "magic", source / "decklab/data", source / "decklab/config.json"]
real_open = Path.open
def checked_open(path, *args, **kwargs):
    resolved = path.resolve()
    if any(resolved == p or p in resolved.parents for p in private):
        raise AssertionError("Production data access: " + str(resolved))
    return real_open(path, *args, **kwargs)
with mock.patch.object(Path, "open", checked_open):
    with FixtureServer() as fixture:
        address = urlsplit(fixture.base_url)
        conn = http.client.HTTPConnection(address.hostname, address.port, timeout=5)
        conn.request("GET", "/api/status")
        response = conn.getresponse()
        assert response.status == 200, response.read()
        assert json.loads(response.read())["cards"]["ready"]
        conn.close()
        temporary = fixture.root
    assert not temporary.exists()
print("fresh-process-isolation-ok")
'''
        env = {key: value for key, value in os.environ.items() if not key.startswith("DECKLAB_")}
        result = subprocess.run([sys.executable, "-c", script], cwd=root, env=env,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("fresh-process-isolation-ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
