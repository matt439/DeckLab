"""Self-service exports/needs use only disposable members, files, snapshots and HTTP."""
import contextlib
import json
import tempfile
import unittest
import zipfile
from unittest import mock

from decklab.db import space_export
from decklab.lib import access, feature_routes, inventory
from decklab.lib.api import space_download as member
from decklab.lib.api.common import ApiError, Download
from decklab.tests.test_api import _write
from decklab.tests.test_api_permissions import PermissionTestCase, R_DECK
from decklab.tests.test_control import wait_until
from decklab.tests.test_server import ServerTestCase


@contextlib.contextmanager
def viewer(name):
    identity = {"profile": name, "email": "", "remote": True} if name else None
    with access.using(identity), access.viewing(None), access.answering(False):
        yield


class MemberSelfServiceTests(PermissionTestCase):
    def test_every_other_viewer_including_admin_script_and_public_reader_is_refused_before_reads(self):
        for who in (None, "matt", "user1", "user2"):
            for requested in ("user3", "home", "../user2"):
                with self.subTest(who=who, requested=requested), viewer(who), \
                        mock.patch.object(space_export, "database_snapshot") as read, \
                        mock.patch.object(member, "_require_cards") as cards:
                    for call in (member.download_view, member.needed_view):
                        with self.assertRaises(ApiError) as caught:
                            call(requested)
                        self.assertEqual((caught.exception.status, caught.exception.message), (403, member.REFUSAL))
                    read.assert_not_called()
                    cards.assert_not_called()
        with viewer(None), mock.patch.object(member.guard, "script", return_value=True):
            with self.assertRaises(ApiError):
                member.download_view("user2")

    def test_zip_has_exact_own_files_hashes_personal_marker_and_no_departure_receipt(self):
        files = {"collection.csv": b"name,set,collector_number,finish,quantity,condition,language,notes\n",
                 "tokens.csv": b"front,quantity\n", "imports/own.csv": b"raw unmodified upload\n",
                 "decks/casual/own.md": R_DECK.encode(), "loans.csv": b"Own borrower only\n"}
        before = self.box.state.changes()
        with viewer("user2"), mock.patch.object(space_export, "database_snapshot", return_value=(files, "departure-secret")) as read:
            download = member.download_view()
        self.addCleanup(download.close)
        self.assertEqual(download.content_type, "application/zip")
        self.assertEqual(download.size, len(download.stream.read()))
        download.stream.seek(0)
        with zipfile.ZipFile(download.stream) as archive:
            self.assertEqual(set(archive.namelist()), {*files, "locations.csv", "dice.csv", "manifest.json", "PERSONAL-COPY.txt"})
            for name, value in files.items():
                self.assertEqual(archive.read(name), value)
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual((manifest["space"], manifest["purpose"], manifest["departure_export"]), ("user2", "personal-copy", False))
            self.assertNotIn("snapshot_sha256", manifest)
            self.assertNotIn("departure-secret", json.dumps(manifest))
            self.assertEqual(set(manifest["files"]), {*files, "locations.csv", "dice.csv"})
            for name, facts in manifest["files"].items():
                import hashlib
                self.assertEqual(facts["sha256"], hashlib.sha256(archive.read(name)).hexdigest())
        read.assert_called_once_with("user2", personal=True)
        self.assertEqual(self.box.state.changes(), before)

    def test_download_limits_and_failures_release_temporary_resources_without_partial_artifact(self):
        with viewer("user2"), mock.patch.object(space_export, "database_snapshot", return_value=({"collection.csv": b"x"}, "sha")):
            first, second = member.download_view(), member.download_view()
            self.addCleanup(first.close)
            self.addCleanup(second.close)
            with self.assertRaises(ApiError) as caught:
                member.download_view()
            self.assertEqual(caught.exception.status, 429)
            first.close()
            third = member.download_view()
            third.close()
            second.close()
        for files, code in (({"collection.csv": b"x" * 20}, 413), ({"private-settings.json": b"SECRET"}, 503)):
            with viewer("user2"), mock.patch.object(space_export, "database_snapshot", return_value=(files, "sha")), \
                    mock.patch.object(member, "MAX_BYTES", 10 if code == 413 else 10000):
                with self.assertRaises(ApiError) as caught:
                    member.download_view()
                self.assertEqual(caught.exception.status, code)
        self.assertTrue(member._downloads.acquire(blocking=False))
        member._downloads.release()

    def test_all_own_planned_decks_compete_for_copies_once_and_other_spaces_do_not_change_needs(self):
        _write(self.box.magic / "people/user2/decks/casual/second.md", R_DECK.replace("User2 Elves", "Second plan"))
        _write(self.box.magic / "people/user2/collection.csv", "name,set,collector_number,finish,quantity,condition,language,notes\n"
               "Llanowar Elves,fdn,227,nonfoil,3,NM,en,\n")
        before = self.box.state.changes()
        with viewer("user2"), mock.patch.object(inventory, "apply", side_effect=AssertionError("No write")):
            answer = member.needed_view()
            _write(self.box.magic / "decks/casual/private.md", R_DECK.replace("User2 Elves", "PRIVATE_HOME"))
            self.assertEqual(member.needed_view(), answer)
        self.assertTrue(answer["ready"])
        self.assertEqual([(row["name"], row["quantity"]) for row in answer["rows"]], [("Llanowar Elves", 5)])
        self.assertEqual({deck["title"] for deck in answer["rows"][0]["decks"]}, {"User2 Elves", "Second plan"})
        self.assertNotIn("PRIVATE_HOME", json.dumps(answer))
        self.assertNotIn("price", json.dumps(answer))
        self.assertEqual(self.box.state.changes(), before)

    def test_one_unrecognized_deck_prevents_a_partial_success_list(self):
        _write(self.box.magic / "people/user2/decks/casual/second.md", R_DECK.replace("Llanowar Elves", "Unknown synthetic card"))
        with viewer("user2"):
            answer = member.needed_view()
        self.assertFalse(answer["ready"])
        self.assertEqual(answer["rows"], [])
        self.assertIn("recognized", answer["reason"])


class MemberDownloadHttpTests(ServerTestCase):
    def artifact(self):
        stream = tempfile.TemporaryFile("w+b")
        stream.write(b"z" * 150000)
        stream.seek(0)
        return Download(stream, "decklab-user2-personal.zip", 150000)

    def test_binary_stream_and_head_keep_security_headers_and_close_resources(self):
        for method in ("GET", "HEAD"):
            artifact = self.artifact()
            with mock.patch.object(member, "download_view", return_value=artifact):
                status, headers, raw = self.request(method, "/api/space/download?space=user2")
            self.assertEqual(status, 200)
            self.assertEqual(raw, b"z" * 150000 if method == "GET" else b"")
            self.assertEqual(headers["Content-Length"], "150000")
            self.assertEqual(headers["Content-Type"], "application/zip")
            self.assertEqual(headers["Cache-Control"], "no-store, private")
            self.assertIn('attachment; filename="decklab-user2-personal.zip"', headers["Content-Disposition"])
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
            # The server thread closes the stream once the answer has gone, so the client may
            # have it all a moment before: wait for the close, with a deadline.
            self.assertTrue(wait_until(lambda: artifact.stream.closed, timeout=5, step=0.01))

    def test_disconnected_receiver_closes_artifact_and_releases_admission(self):
        from types import SimpleNamespace
        artifact = self.artifact()
        artifact.release = mock.Mock()
        release = artifact.release
        handler = SimpleNamespace(command="GET", _allow=lambda *args: None, _query=lambda *args: {},
                                  _send=mock.Mock(side_effect=BrokenPipeError()))
        with mock.patch.object(member, "download_view", return_value=artifact):
            with self.assertRaises(BrokenPipeError):
                feature_routes.dispatch(handler, ("space", "download"), {})
        self.assertTrue(artifact.stream.closed)
        release.assert_called_once_with()
