"""Home-only export planning uses synthetic rows/files and fake Git, never real records or pushes."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from decklab.db import export, export_scope as scope


class ScopeTests(unittest.TestCase):
    def test_table_queries_bind_home_before_rows_are_written_including_retired_decks_and_accessory_owners(self):
        class Connection:
            def __init__(self, rows):
                self.rows = rows
                self.queries = []
            def execute(self, query, params=None):
                if isinstance(query, str) and "information_schema.columns" in query:
                    return mock.Mock(fetchall=lambda: [(key,) for key in self.rows[0]])
                text = query.as_string()
                self.queries.append((text, params))
                rows = self.rows
                if " where owner in" in text:
                    rows = [row for row in rows if row["owner"] in ("shared", "", "matt", "user1") and params == ("home",)]
                elif " where space_id = %s" in text:
                    rows = [row for row in rows if row["space_id"] == params[0]]
                elif " where split_part(deck_id" in text:
                    rows = [row for row in rows if row["deck_id"].split("/")[0] in ("casual", "commander")]
                elif "unnest(deck_ids)" in text:
                    rows = [row for row in rows if json.loads(row["content"]).get("space", "home") == "home"
                            and all(deck.split("/")[0] in ("casual", "commander", "product", "pairing") for deck in row["deck_ids"])]
                return [tuple(row.values()) for row in rows]
        cases = [("public.profile", "id", [{"id": "matt", "space_id": "home", "name": "HOME"},
                                            {"id": "user2", "space_id": "user2", "name": "PRIVATE"}]),
                 ("public.collection_card", "name", [{"name": "HOME", "space_id": "home"}, {"name": "PRIVATE", "space_id": "user2"}]),
                 ("public.deck_revision", "deck_id", [{"deck_id": "casual/retired", "text": "HOME"},
                                                       {"deck_id": "user2/casual/retired", "text": "PRIVATE"}]),
                 ("public.accessory", "id", [{"id": "home", "owner": "matt", "name": "HOME"},
                                              {"id": "other", "owner": "user2", "name": "PRIVATE"}]),
                 ("public.play_record", "id", [
                     {"id": "home", "kind": "games", "deck_ids": ["casual/home"],
                      "content": '{"space":"home","notes":"HOME","sides":[{"id":"casual/home"},{"id":"commander/home"}]}'},
                     {"id": "member", "kind": "games", "deck_ids": ["casual/home"],
                      "content": '{"space":"user2","notes":"PRIVATE","sides":[{"id":"casual/home"},{"id":"commander/home"}]}'},
                     {"id": "mixed", "kind": "games", "deck_ids": ["user2/casual/private"],
                      "content": '{"space":"home","notes":"PRIVATE","sides":[{"id":"casual/home"},{"id":"user2/casual/private"}]}'},
                     {"id": "bad-index", "kind": "games", "deck_ids": ["casual/home"],
                      "content": '{"space":"home","notes":"PRIVATE","sides":[{"id":"casual/home"},{"id":"user2/casual/private"}]}'}])]
        for table, order, rows in cases:
            with self.subTest(table=table):
                connection = Connection(rows)
                data = export.table_csv(connection, table, (order,), scope="home")
                self.assertIn(b"HOME", data)
                self.assertNotIn(b"PRIVATE", data)
                self.assertIn(" where ", connection.queries[0][0])
                self.assertIn(b"PRIVATE", export.table_csv(Connection(rows), table, (order,)), "legacy full export remains full")

    def test_default_and_every_export_table_have_an_explicit_reviewed_policy(self):
        self.assertIsNone(scope.setting({}))
        self.assertEqual(scope.setting({"export_remote_scope": "home"}), "home")
        with self.assertRaises(ValueError):
            scope.setting({"export_remote_scope": "unknown"})
        self.assertEqual(set(scope.FILTERS) | scope.EXCLUDED, {name for name, _ in export.TABLES})
        self.assertFalse(set(scope.FILTERS) & scope.EXCLUDED)
        with self.assertRaises(ValueError):
            scope.included("public.future_private_table")
        for name in ("public.profile_email", "public.wishlist_entry", "audit.change_set"):
            self.assertFalse(scope.included(name))

    def test_member_files_and_other_owners_pictures_never_enter_the_output(self):
        files = {"magic/collection.csv": b"HOME_CARDS", "magic/people/user2/collection.csv": b"PRIVATE_CARDS",
                 "magic/people/user2/decks/casual/private.md": b"PRIVATE_DECK",
                 "magic/accessories.csv": b"id,owner,image,name\nhome-kit,matt,home.jpg,Home\nother,user2,other.jpg,PRIVATE\n",
                 "magic/accessories/images/home.jpg": b"HOME_IMAGE", "magic/accessories/images/other.jpg": b"PRIVATE_IMAGE",
                 "magic/accessories/images/orphan.jpg": b"PRIVATE_ORPHAN"}
        found = scope.files_home(files, {"matt", "shared"})
        self.assertEqual(set(found), {"magic/collection.csv", "magic/accessories.csv", "magic/accessories/images/home.jpg"})
        self.assertNotIn(b"PRIVATE", b"".join(found.values()))
        self.assertIn(b"PRIVATE", files["magic/accessories.csv"], "cached input is never mutated")
        self.assertIsNone(scope.files_home(None, {"matt"}))
        with self.assertRaises(ValueError):
            scope.files_home({"magic/../private": b"x"}, {"matt"})

    def test_fresh_home_history_is_marked_and_full_history_is_never_relabelled(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            scope.check_history(folder, "home", lambda *args: (0, ""))
            commit = "a" * 40
            def git(repo, *args):
                if args[0] == "show":
                    return 0, scope.MARKER_TEXT
                return 0, commit + "\n"
            (folder / scope.MARKER).write_text(scope.MARKER_TEXT, encoding="utf-8")
            scope.check_history(folder, "home", git)
            with self.assertRaisesRegex(ValueError, "separate repository"):
                scope.check_history(folder, None, git)
            old = mock.Mock(side_effect=[(0, commit), (0, ""), (1, "PRIVATE_OLD_DATA")])
            with self.assertRaisesRegex(ValueError, "fresh export repository") as refused:
                scope.check_history(folder, "home", old)
            self.assertNotIn("PRIVATE", str(refused.exception))
            self.assertEqual(json.loads((folder / scope.MARKER).read_text()), {"version": 1, "scope": "home"})

    def test_remote_old_branches_and_unmanaged_files_cannot_enter_a_home_only_export(self):
        commit, old = "a" * 40, "b" * 40
        scope.check_remote("unused", mock.Mock(side_effect=[(0, commit), (0, "")]))
        scope.check_remote("unused", mock.Mock(side_effect=[(0, commit), (0, commit + "\trefs/heads/main")]))
        with self.assertRaisesRegex(ValueError, "empty remote"):
            scope.check_remote("unused", mock.Mock(side_effect=[(0, commit), (0, old + "\trefs/heads/old-private")]))
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "private.txt").write_text("PRIVATE", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unmanaged"):
                scope.check_tree(folder)

    def test_scoped_files_replace_member_exports_without_reading_wishlists_or_retaining_missing_tables(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "tables").mkdir()
            (folder / "tables/public.profile_email.csv").write_bytes(b"PRIVATE_EMAIL")
            (folder / "wishlists").mkdir()
            (folder / "wishlists/user2.json").write_bytes(b"PRIVATE_WISHLIST")
            (folder / "magic/people/user2").mkdir(parents=True)
            (folder / "magic/people/user2/collection.csv").write_bytes(b"PRIVATE_COLLECTION")
            connection = mock.MagicMock()
            connection.__enter__.return_value = connection
            connection.execute.return_value.fetchone.return_value = (False,)
            generated = {"magic/collection.csv": b"HOME_CARDS", "magic/people/user2/collection.csv": b"PRIVATE_CARDS"}
            asked = []
            def table(c, name, order, **options):
                self.assertEqual(options, {"scope": "home"})
                asked.append(name)
                return b"header\nHOME\n"
            with mock.patch.object(export.db, "connect", return_value=connection), \
                    mock.patch.object(export, "table_csv", side_effect=table), \
                    mock.patch.object(export, "wishlist_files", side_effect=AssertionError("private wishlists were read")), \
                    mock.patch.object(export, "inventory_files", return_value=generated), \
                    mock.patch.object(scope, "home_owners", return_value={"matt", "shared"}):
                export.write_tables(folder, scope="home")
            self.assertEqual(set(asked), set(scope.FILTERS))
            self.assertFalse((folder / "wishlists").exists())
            self.assertFalse((folder / "magic/people").exists())
            self.assertFalse((folder / "tables/public.profile_email.csv").exists())
            self.assertTrue((folder / scope.MARKER).is_file())
            self.assertNotIn(b"PRIVATE", b"".join(path.read_bytes() for path in folder.rglob("*") if path.is_file()))

    def test_full_default_keeps_unscoped_behavior_and_invalid_history_stops_before_export_or_push(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            for settings, refused in (({}, False), ({"export_remote_scope": "home"}, True)):
                commit = "a" * 40
                git = mock.Mock(side_effect=[(0, commit), (0, ""), (1, "PRIVATE_OLD_HISTORY")])
                with mock.patch.object(export.db, "settings", return_value=settings), \
                        mock.patch.object(export, "ensure_repo", return_value=False), \
                        mock.patch.object(export, "git", git), mock.patch.object(export, "write_tables", return_value=4) as write, \
                        mock.patch.object(export, "commit", return_value="fixture") as commit_export, \
                        mock.patch.object(export, "has_origin", return_value=False), mock.patch.object(export.backup, "record"):
                    self.assertEqual(export.run_export(folder, push=False, say=lambda text: None), int(refused))
                if refused:
                    write.assert_not_called()
                    commit_export.assert_not_called()
                else:
                    write.assert_called_once_with(folder)
                    git.assert_not_called()
