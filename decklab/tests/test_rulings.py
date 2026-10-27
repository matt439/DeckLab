"""Scryfall's rulings (decklab/lib/rulings.py, E1-S25): reducing the bulk file, the update step, the
card viewer's endpoint and its fold under the card's words. Fixture data only; no network."""
import gzip
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
from datetime import timedelta
from pathlib import Path
from unittest import mock

from decklab.lib import card_index, cards, rulings
from decklab.lib.api.card_rulings import card_rulings
from decklab.lib.api.common import ApiError
from decklab.tests import test_card_inspector
from decklab.tests.test_cards import LLANOWAR, FixtureIndex

OTHER = "00000000-0000-0000-0000-000000000001"
NEWER = "2026-10-20T21:00:00.000+00:00"
OLDER = "2026-10-01T21:00:00.000+00:00"
BULK = [
    {"object": "ruling", "oracle_id": LLANOWAR, "source": "wotc", "published_at": "2021-03-19",
     "comment": "Later ruling about {T}."},
    {"object": "ruling", "oracle_id": LLANOWAR, "source": "scryfall", "published_at": "2004-10-04",
     "comment": "Earlier ruling."},
    {"object": "ruling", "oracle_id": OTHER, "source": "wotc", "published_at": "2020-01-01", "comment": "  "},
]


class RulingsFiles(unittest.TestCase):
    """A temporary scryfall folder for rulings.py and cards.py's meta file."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for patcher in (mock.patch.object(cards, "SCRYFALL_DIR", self.tmp),
                        mock.patch.object(cards, "BULK_META_FILE", self.tmp / "bulk.json"),
                        mock.patch.object(rulings, "_loaded", None)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.log = []

    def bulk_file(self, name="bulk.json", entries=BULK, jsonl=False, gz=False):
        text = "\n".join(json.dumps(e) for e in entries) if jsonl else json.dumps(entries, indent=1)
        path = self.tmp / name
        if gz:
            with gzip.open(path, "wt", encoding="utf-8") as f:
                f.write(text)
        else:
            path.write_text(text, encoding="utf-8")
        return path

    def listing(self, updated_at=NEWER, **extra):
        entry = {"type": "rulings", "updated_at": updated_at,
                 "download_uri": "https://example.invalid/rulings.json", **extra}
        return {"data": [{"type": "default_cards"}, entry]}

    def update(self, listing, download=None, force=False):
        def copy_bulk(url, dest, **kwargs):
            shutil.copy(self.bulk_file("source.json"), dest)
            return 1
        get_json = listing if isinstance(listing, mock.Mock) else mock.Mock(return_value=listing)
        with mock.patch.object(cards, "_get_json", get_json), \
                mock.patch.object(cards, "_download", download or mock.Mock(side_effect=copy_bulk)) as fetch:
            return rulings.update(force=force, log=self.log.append), fetch


class ReduceTests(RulingsFiles):
    def test_every_bulk_shape_reads_the_same(self):
        expected = {LLANOWAR: [["2004-10-04", "scryfall", "Earlier ruling."],
                               ["2021-03-19", "wotc", "Later ruling about {T}."]]}
        for jsonl in (False, True):
            for gz in (False, True):
                with self.subTest(jsonl=jsonl, gz=gz):
                    self.assertEqual(rulings.reduce(self.bulk_file(jsonl=jsonl, gz=gz)), expected)

    def test_an_unreadable_entry_refuses_the_file(self):
        for bad in ({"source": "wotc", "comment": "No oracle id"}, "not an object",
                    {"oracle_id": LLANOWAR, "comment": None}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                rulings.reduce(self.bulk_file(entries=[*BULK, bad]))

    def test_an_unknown_source_and_date_are_kept_blank(self):
        path = self.bulk_file(entries=[{"oracle_id": LLANOWAR, "source": "elsewhere", "comment": "Text"}])
        self.assertEqual(rulings.reduce(path), {LLANOWAR: [["", "", "Text"]]})


class UpdateTests(RulingsFiles):
    def test_downloads_reduces_and_then_stays_fresh(self):
        changed, fetch = self.update(self.listing())
        self.assertTrue(changed)
        self.assertEqual(fetch.call_args.args[0], "https://example.invalid/rulings.json")
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["bulk.json", "rulings.json.gz", "source.json"])
        self.assertEqual(rulings.updated(), "2026-10-20")
        self.assertEqual([r["text"] for r in rulings.for_card({"oracle_id": LLANOWAR})],
                         ["Earlier ruling.", "Later ruling about {T}."])
        self.assertEqual(rulings.for_card({"oracle_id": OTHER}), [], "blank rulings are dropped")
        meta = cards._read_json(self.tmp / "bulk.json", {})
        self.assertEqual(meta["rulings"]["updated_at"], NEWER)
        changed, fetch = self.update(mock.Mock(side_effect=AssertionError("no network when fresh")))
        self.assertFalse(changed)
        self.assertIn("rulings: fresh", self.log[-1])

    def test_the_jsonl_file_is_preferred(self):
        _, fetch = self.update(self.listing(jsonl_download_uri="https://example.invalid/rulings.jsonl.gz"))
        self.assertEqual(fetch.call_args.args[0], "https://example.invalid/rulings.jsonl.gz")

    def test_the_card_files_meta_is_kept(self):
        cards._write_json(self.tmp / "bulk.json", {"default_cards": {"updated_at": "x"}, "index": {"version": 1}})
        self.update(self.listing())
        meta = cards._read_json(self.tmp / "bulk.json", {})
        self.assertEqual((meta["default_cards"], meta["index"]), ({"updated_at": "x"}, {"version": 1}))

    def test_unchanged_on_scryfall_restarts_the_clock(self):
        self.update(self.listing(OLDER))
        meta = cards._read_json(self.tmp / "bulk.json", {})
        meta["rulings"]["downloaded_at"] = (card_index._now() - timedelta(days=8)).isoformat(timespec="seconds")
        cards._write_json(self.tmp / "bulk.json", meta)
        changed, fetch = self.update(self.listing(OLDER), mock.Mock(side_effect=AssertionError("no download")))
        self.assertFalse(changed)
        self.assertFalse(rulings._is_stale(cards._read_json(self.tmp / "bulk.json", {})))
        changed, _ = self.update(self.listing(OLDER), force=True)
        self.assertTrue(changed, "force downloads anyway")

    def test_failures_keep_the_rulings_on_the_pc(self):
        self.update(self.listing(OLDER))
        before = (self.tmp / "rulings.json.gz").read_bytes()
        meta = cards._read_json(self.tmp / "bulk.json", {})

        def damaged(url, dest, **kwargs):
            dest.write_text('[{"oracle_id": "x", "comment": 3}]', encoding="utf-8")
            return 1
        for name, listing, download in (
                ("offline", mock.Mock(side_effect=urllib.error.URLError("offline")), None),
                ("cut off", self.listing(), mock.Mock(side_effect=OSError("got 5 bytes, expected 10"))),
                ("damaged", self.listing(), mock.Mock(side_effect=damaged)),
                ("not listed", {"data": []}, None)):
            with self.subTest(name):
                changed, _ = self.update(listing, download, force=True)
                self.assertFalse(changed)
                self.assertIn("keeping the rulings on the PC", self.log[-1])
                self.assertEqual((self.tmp / "rulings.json.gz").read_bytes(), before)
                self.assertEqual(cards._read_json(self.tmp / "bulk.json", {}), meta)
                self.assertFalse((self.tmp / "rulings.download").exists())

    def test_missing_damaged_or_other_format_reads_as_no_rulings(self):
        self.assertIsNone(rulings.for_card({"oracle_id": LLANOWAR}))
        self.assertIsNone(rulings.updated())
        self.update(self.listing())
        self.assertTrue(rulings.available())
        path = self.tmp / "rulings.json.gz"
        path.write_bytes(b"\x1f\x8b damaged")
        os.utime(path, ns=(10**9, 10**9))
        self.assertIsNone(rulings.for_card({"oracle_id": LLANOWAR}))
        rulings._write({}, NEWER, path)
        with gzip.open(path, "rt", encoding="utf-8") as f:
            data = json.load(f)
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump({**data, "format": rulings.FORMAT + 1}, f)
        os.utime(path, ns=(2 * 10**9, 2 * 10**9))
        self.assertFalse(rulings.available())

    def test_a_new_file_is_read_again(self):
        rulings._write({LLANOWAR: [["2020-01-01", "wotc", "One"]]}, OLDER, rulings.index_path())
        os.utime(rulings.index_path(), ns=(10**9, 10**9))
        self.assertEqual(len(rulings.for_card({"oracle_id": LLANOWAR})), 1)
        rulings._write({LLANOWAR: [["2020-01-01", "wotc", "One"], ["2021-01-01", "wotc", "Two"]]}, NEWER,
                       rulings.index_path())
        os.utime(rulings.index_path(), ns=(2 * 10**9, 2 * 10**9))
        self.assertEqual(len(rulings.for_card({"oracle_id": LLANOWAR})), 2)


class CardsUpdateStepTests(unittest.TestCase):
    def test_rulings_are_a_step_whose_failure_never_fails_the_update(self):
        logs = []
        with mock.patch.object(rulings, "update", side_effect=RuntimeError("disk full")):
            cards._update_rulings(False, logs.append)
        self.assertIn("Rulings: not updated (RuntimeError: disk full)", logs[0])

    def test_every_update_runs_the_rulings_step_after_the_index(self):
        seen = []
        with mock.patch.object(cards, "download_bulk", return_value=[]), \
                mock.patch.object(cards, "_update_index", side_effect=lambda *a: seen.append("index") or False), \
                mock.patch.object(cards, "_update_rulings", side_effect=lambda *a: seen.append(("rulings", a[0]))), \
                mock.patch.object(cards, "_update_combos"), mock.patch.object(cards, "_update_official_lists"):
            cards.update(force=True, log=lambda *a: None)
        self.assertEqual(seen, ["index", ("rulings", True)])


class EndpointTests(FixtureIndex):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp_dir, True)
        for patcher in (mock.patch.object(cards, "SCRYFALL_DIR", self.tmp_dir), mock.patch.object(rulings, "_loaded", None)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_cards_rulings_none_and_not_yet(self):
        self.assertEqual(card_rulings("llanowar elves"),
                         {"name": "Llanowar Elves", "available": False, "updated": None, "rulings": []})
        rulings._write({LLANOWAR: [["2004-10-04", "wotc", "A ruling."]]}, NEWER, rulings.index_path())
        self.assertEqual(card_rulings("Llanowar Elves"),
                         {"name": "Llanowar Elves", "available": True, "updated": "2026-10-20",
                          "rulings": [{"date": "2004-10-04", "source": "wotc", "text": "A ruling."}]})
        self.assertEqual(card_rulings("Fire // Ice")["rulings"], [])

    def test_bad_and_unknown_names(self):
        for name, status in (("", 400), ("x" * 151, 400), ("a\nb", 400), (None, 400), ("Nonsense Card", 404)):
            with self.subTest(name=name), self.assertRaises(ApiError) as caught:
                card_rulings(name)
            self.assertEqual(caught.exception.status, status)


# The viewer's rulings fold, under Node.js with the card viewer test's stand-in DOM and a stand-in fetch.
VIEWER_SCENARIO = r"""
const answers = {
  'Ruled': { status: 200, body: { name: 'Ruled', available: true, updated: '2026-10-20', rulings: [
    { date: '2004-10-04', source: 'wotc', text: 'Tap it: {T}.' }, { date: '2021-03-19', source: 'scryfall', text: 'Second.' }] } },
  'Plain': { status: 200, body: { name: 'Plain', available: true, updated: '2026-10-20', rulings: [] } },
  'Early': { status: 200, body: { name: 'Early', available: false, updated: null, rulings: [] } },
  'Token': { status: 404, body: { error: "No card named 'Token'" } },
  'Down': { status: 503, body: { error: 'No card data yet' } },
};
const asked = [];
ctx.fetch = async (path) => {
  const name = decodeURIComponent(path.split('name=')[1]);
  asked.push(name);
  const a = answers[name];
  return { ok: a.status === 200, status: a.status, json: async () => a.body };
};
let d;
const rulingsBox = () => find('viewer-rulings', d.text);
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
(async () => {
  run('openCardViewer')(['Ruled', 'Plain', 'Early', 'Token', 'Down'].map((name) => ({ name, type_line: 'Creature', oracle_text: 'Words' })), 0);
  d = run('viewerDom');
  await settle();
  const fold = find('viewer-rulings-fold', d.text);
  assert(fold && fold.tagName === 'DETAILS' && !('open' in fold.attrs), 'rulings are folded away by default');
  assert.equal(text(fold.children[0]), 'Rulings (2)');
  const items = fold.all().filter((n) => n.classList.contains('viewer-ruling'));
  assert.deepEqual(items.map((n) => text(n.children[0])), ['2004-10-04 · Wizards of the Coast', '2021-03-19 · Scryfall']);
  assert(items[0].all().some((n) => n.tagName === 'IMG' && n.getAttribute('src') === '/sym/T.svg'), 'symbols are drawn');
  assert(text(fold).includes('From Scryfall, 2026-10-20.'));
  const order = (n) => d.text.children.indexOf(n);
  assert(order(rulingsBox()) > order(find('viewer-face', d.text)), 'under the rules text');

  run('stepViewer')(1); await settle();
  assert.equal(rulingsBox().children.length, 0, 'a card with no rulings shows nothing extra');
  run('stepViewer')(1); await settle();
  assert.equal(text(rulingsBox()), "Rulings aren't available yet.");
  run('stepViewer')(1); await settle();
  assert.equal(rulingsBox().children.length, 0, 'a name that is not a card shows nothing');
  run('stepViewer')(1); await settle();
  assert(text(rulingsBox()).includes("Rulings couldn't load"));

  const before = asked.length;
  run('goViewer')(0); await settle();
  assert.equal(asked.length, before, 'an answer is kept for the opening of the page');
  assert(find('viewer-rulings-fold', d.text));
  run('goViewer')(4); await settle();
  assert.equal(asked.length, before + 1, 'a failure is asked again');
  console.log('ok');
})().catch((e) => { console.error(e); process.exit(1); });
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ViewerRulingsTests(unittest.TestCase):
    def test_the_fold_none_not_yet_and_failures(self):
        runner = test_card_inspector.NODE_RUNNER
        prelude = runner[:runner.index("// One card:")]
        done = subprocess.run([shutil.which("node"), "-e", prelude + VIEWER_SCENARIO, str(test_card_inspector.WEB)],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("ok", done.stdout)


if __name__ == "__main__":
    unittest.main()
