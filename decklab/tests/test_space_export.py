"""Member exports use disposable PostgreSQL databases and temporary directories only."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from decklab.db import conn as db, space_export
from decklab.lib import config
from decklab.tests import db_support

SPACE = "sample"
DECK = "# A member deck\n\n```\nDeck\n60 Forest\n```\n"
SECRET = "OTHER-SPACE-PRIVATE-SENTINEL"


class ExportInputTests(unittest.TestCase):
    def test_command_is_registered_without_dispatcher_changes(self):
        from decklab.db.__main__ import parser
        args = parser().parse_args(["space", "export", SPACE, "unused"])
        self.assertEqual((args.command, args.action, args.space, args.dir), ("space", "export", SPACE, "unused"))

    def test_refuses_home_bad_ids_and_existing_or_repo_destinations_before_reading(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(space_export, "database_snapshot") as read:
            for space in ("home", "casual", "commander", "product", "pairing", "people", "claude", "system", "test",
                          "../sample", "Sample", "sample/other", "", "a" * 41, None):
                with self.assertRaises(ValueError):
                    space_export.export_to(space, Path(tmp) / "new")
            for path in (Path(tmp), Path(config.REPO) / "never-create-space-export"):
                with self.assertRaises(ValueError):
                    space_export.export_to(SPACE, path)
            read.assert_not_called()

    def test_refuses_unsafe_portable_paths(self):
        for rel in ("../bad", "/bad", "imports/../bad", "imports/C:bad", "imports/a\\b", "imports/NUL.csv",
                    "imports/scan.", "imports/a?b", "imports//scan"):
            with self.assertRaises(ValueError, msg=rel):
                space_export._relative(rel)
        self.assertEqual(str(space_export._relative("imports/.scan.csv")), "imports/.scan.csv")


class MemberExportTests(db_support.DbTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with db.connect("owner", dbname=cls.dbname, autocommit=True) as c:
            with db.change("test", "test", "Member export fixture spaces", conn=c) as (cur, _):
                cur.execute("insert into space (id) values ('home'), ('sample'), ('other') on conflict do nothing")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="decklab-member-export-")
        self.addCleanup(self.tmp.cleanup)
        self.dest = Path(self.tmp.name) / "export"
        self.results = Path(self.tmp.name) / "forge"
        self.results.mkdir()
        db_support.reset(self.dbname, db_support.INVENTORY_TABLES + db_support.STATE_TABLES)
        with self.connect() as c:
            with db.change("test", "test", "Member export fixture", conn=c) as (cur, _):
                for space, text in ((SPACE, "member"), ("home", SECRET), ("other", SECRET)):
                    cur.execute("insert into collection_card (space_id, set_code, collector_number, finish, name, "
                                "quantity, notes) values (%s, 'fdn', '227', 'nonfoil', 'Llanowar Elves', 2, %s)",
                                (space, text))
                    cur.execute("insert into token_card (space_id, position, front, quantity, notes) "
                                "values (%s, 0, 'Elf', 1, %s)", (space, text))
                    deck_id = "casual/current" if space == "home" else f"{space}/casual/current"
                    cur.execute("insert into deck (id, space_id, kind, slug, revision) "
                                "values (%s, %s, 'casual', 'current', 1)", (deck_id, space))
                    cur.execute("insert into deck_text (deck_id, text) values (%s, %s)",
                                (deck_id, DECK if space == SPACE else SECRET))
                    cur.execute("insert into deck_revision (deck_id, revision, at, actor, message, op, text) "
                                "values (%s, 1, now(), 'test', %s, 'A', %s)",
                                (deck_id, text, DECK if space == SPACE else SECRET))
                    cur.execute("insert into collection_import (space_id, file_name, size, sha256) "
                                "values (%s, 'scan.csv', %s, %s) returning id",
                                (space, len(text.encode()), space_export._sha(text.encode())))
                    import_id = cur.fetchone()[0]
                    cur.execute("insert into collection_import_content (import_id, content) values (%s, %s)",
                                (import_id, text.encode()))
                cur.execute("insert into deck_revision (deck_id, revision, at, actor, message, op, text) values "
                            "('sample/casual/retired', 1, now(), 'test', 'first', 'A', %s), "
                            "('sample/casual/retired', 2, now(), 'test', 'retire', 'D', null)", (DECK + "Retired.\n",))
                cur.execute("insert into deck_alias (alias_id, deck_id) values "
                            "('sample/casual/former', 'sample/casual/current')")
                cur.execute("insert into deck_revision (deck_id, revision, at, actor, message, op, text) "
                            "values ('sample/casual/former', 1, now(), 'test', 'old name', 'A', %s)", (DECK,))
                cur.execute("insert into wishlist_entry (profile_id, position, name, notes) values "
                            "('sample', 0, 'Opt', 'member-only'), ('other', 0, 'Opt', %s)", (SECRET,))
                cur.execute("insert into profile_setting (profile_id, key, value) values "
                            "('sample', 'theme', 'dark'), ('other', 'theme', %s)", (SECRET,))
                from psycopg.types.json import Jsonb
                cur.execute("insert into play_record (kind, id, revision, created_on, updated_on, updated_by, "
                            "deck_ids, content) values ('games', %s, 1, '2026-10-18T00:00:00Z', "
                            "'2026-10-18T00:00:00Z', 'test', %s, %s)",
                            ("a" * 32, ["sample/casual/current", "other/casual/current"], Jsonb({"notes": SECRET})))

    def change(self, sql, params=()):
        with self.connect() as c:
            with db.change("test", "test", "Change export fixture", conn=c) as (cur, _):
                cur.execute(sql, params)

    def export(self):
        return space_export.export_to(SPACE, self.dest, self.dbname, self.results)

    def match(self, manifest):
        return space_export.matching_export(SPACE, self.dest, manifest["snapshot_sha256"], self.dbname, self.results)

    def test_scoped_files_exact_formats_retired_text_and_no_cross_space_contents(self):
        with mock.patch("decklab.db.export.inventory_files", side_effect=AssertionError("all-space export used")):
            manifest = self.export()
        self.assertEqual(set(manifest["files"]), {"collection.csv", "tokens.csv", "imports/scan.csv",
                         "decks/casual/current.md", "retired/decks/casual/retired.md"})
        self.assertEqual((self.dest / "decks/casual/current.md").read_bytes(), DECK.encode())
        self.assertEqual((self.dest / "retired/decks/casual/retired.md").read_bytes(), (DECK + "Retired.\n").encode())
        self.assertEqual((self.dest / "collection.csv").read_bytes(),
                         b"name,set,collector_number,finish,quantity,condition,language,notes\n"
                         b"Llanowar Elves,fdn,227,nonfoil,2,,,member\n")
        self.assertEqual((self.dest / "imports/scan.csv").read_bytes(), b"member")
        self.assertFalse(manifest["forge_results_included"])
        for path in self.dest.rglob("*"):
            if path.is_file():
                self.assertNotIn(SECRET.encode(), path.read_bytes())
        self.assertEqual(self.match(manifest), manifest)

    def test_export_is_read_only_and_deterministic(self):
        with self.connect() as c:
            before = c.execute("select count(*) from audit.change_set").fetchone()
        manifest = self.export()
        second = Path(self.tmp.name) / "second"
        self.assertEqual(space_export.export_to(SPACE, second, self.dbname, self.results), manifest)
        with self.connect() as c:
            self.assertEqual(c.execute("select count(*) from audit.change_set").fetchone(), before)
        self.assertEqual((second / "manifest.json").read_bytes(), (self.dest / "manifest.json").read_bytes())

    def test_other_space_changes_do_not_stale_the_export(self):
        manifest = self.export()
        self.change("update collection_card set quantity = 9 where space_id = 'other'")
        self.change("update deck_text set text = text || 'changed' where deck_id = 'other/casual/current'")
        self.change("update profile_setting set value = 'light' where profile_id = 'other'")
        self.assertEqual(self.match(manifest), manifest)

    def test_current_other_space_list_protects_a_result_without_seen_as_provenance(self):
        from decklab.lib.forge import lists
        from decklab.tests.test_space_remove_preview import forge_result
        self.change("insert into deck_line (deck_id, version, section, position, quantity, name) "
                    "values ('casual/current', 'target', 'Deck', 0, 60, 'Forest')")
        card_sha = lists._list_text({"Main": [[60, "Forest"]]}, "constructed")[1]
        key = "e" * 64
        value = forge_result(key)
        value["sides"][0]["card_sha"] = card_sha
        (self.results / (key + ".json")).write_text(json.dumps(value))
        manifest = self.export()
        self.assertEqual(manifest["forge_files"], {})
        self.assertEqual(self.match(manifest), manifest)
        self.change("update deck_line set quantity = 59 where deck_id = 'casual/current'")
        with self.assertRaisesRegex(ValueError, "snapshot has changed"):
            self.match(manifest)

    def test_member_card_change_requires_a_fresh_export(self):
        manifest = self.export()
        self.change("update collection_card set quantity = 3 where space_id = 'sample'")
        with self.assertRaisesRegex(ValueError, "snapshot has changed"):
            self.match(manifest)

    def test_member_non_file_state_changes_require_a_fresh_export(self):
        for sql in ("update profile_setting set value = value || 'x' where profile_id = 'sample'",
                    "update wishlist_entry set notes = notes || 'x' where profile_id = 'sample'",
                    "update play_record set revision = revision + 1"):
            with self.subTest(sql=sql):
                self.dest = Path(self.tmp.name) / str(len(list(Path(self.tmp.name).iterdir())))
                manifest = self.export()
                self.change(sql)
                with self.assertRaisesRegex(ValueError, "snapshot has changed"):
                    self.match(manifest)

    def test_changed_missing_extra_or_wrong_space_artifacts_are_refused(self):
        manifest = self.export()
        with self.assertRaisesRegex(ValueError, "does not match"):
            space_export.matching_export("other", self.dest, manifest["snapshot_sha256"], self.dbname, self.results)
        with self.assertRaises(ValueError):
            space_export.matching_export(SPACE, self.dest, "bad", self.dbname, self.results)
        path = self.dest / "collection.csv"
        original = path.read_bytes()
        path.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "files no longer match"):
            self.match(manifest)
        path.write_bytes(original)
        extra = self.dest / "extra.txt"
        extra.write_text("extra")
        with self.assertRaisesRegex(ValueError, "files no longer match"):
            self.match(manifest)
        extra.unlink()
        path.unlink()
        with self.assertRaisesRegex(ValueError, "files no longer match"):
            self.match(manifest)

    def test_missing_manifest_and_unknown_spaces_are_refused(self):
        self.export()
        (self.dest / "manifest.json").unlink()
        with self.assertRaisesRegex(ValueError, "complete matching"):
            space_export.matching_export(SPACE, self.dest, "a" * 64, self.dbname, self.results)
        with self.assertRaisesRegex(ValueError, "No member space"):
            space_export.export_to("missing", Path(self.tmp.name) / "missing", self.dbname, self.results)

    def test_empty_member_has_header_only_lists(self):
        with self.connect() as c:
            with db.change("test", "test", "Empty export fixture", conn=c) as (cur, _):
                cur.execute("insert into space (id) values ('empty') on conflict do nothing")
        manifest = space_export.export_to("empty", Path(self.tmp.name) / "empty", self.dbname, self.results)
        self.assertEqual(set(manifest["files"]), {"collection.csv", "tokens.csv"})

    def test_command_prints_count_and_sha_only(self):
        from decklab.db.__main__ import main
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["space", "export", SPACE, str(self.dest), "--dbname", self.dbname,
                                   "--results-dir", str(self.results)]), 0)
        self.assertIn("Wrote 5 member files", output.getvalue())
        self.assertIn("Snapshot SHA:", output.getvalue())
        self.assertNotIn(DECK, output.getvalue())


if __name__ == "__main__":
    unittest.main()
