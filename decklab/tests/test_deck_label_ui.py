"""Print box label (E8-S21): the QR encoder against known vectors, and the label on the real deck page scripts.

The QR vectors are the standard's (the format and version information, the Reed-Solomon example of
"HELLO WORLD" at 1-M) and whole symbols made by another encoder (python-qrcode 8, byte mode, level M,
the mask given), kept as SHA-256 digests of their rows. The deck page fixture drives the real scripts; no
server is touched, and nothing is written.
"""
import hashlib
import json
import subprocess
import unittest

from decklab.tests.test_deck_page_ui import PAGE
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

# (text, mask, version, sha256 of the rows as "0101.../0110...", dark as 1), from python-qrcode.
SYMBOLS = [
    ("hello", 0, 1, "6fe97a21d94f523cd7af352f4f2387869acf40d931417ece6f96d803fb178795"),
    ("https://decklab.example.com/#/deck?id=casual%2Fgruul-ramp", 5, 4,
     "c39422b017754949c3cad3a8daef851c4ee6d7afe2b86fe1b90ca99e74bea7e0"),
    ("y" * 120, 3, 7, "8bd2119196cb2e6c9243685f23bda608d9160290a2d4642ec20c55da62f24be1"),
    ("Ünïcödé ✓ " * 8, 6, 8, "42df96e5a753a14e806d50c8d382e861c6f13c6fb788efb22b6c04cbe61147a8"),
    ("a" * 213, 7, 10, "6977ced80eea5735d1197dc0c754eb8f0d3e213b95eccc4c3a47277dc07f0ed3"),
]

QR_SCRIPT = """
const fs = require('fs');
eval(fs.readFileSync(process.argv[1], 'utf8') + '\\n;globalThis.qr = {qrMatrix, qrReedSolomon};');
const asks = JSON.parse(fs.readFileSync(0, 'utf8'));
const rows = (q) => q.modules.map((r) => r.map((b) => (b ? 1 : 0)).join('')).join('/');
console.log(JSON.stringify({
  symbols: asks.symbols.map(([text, mask]) => { const q = qr.qrMatrix(text, mask); return [q.version, q.mask, rows(q)]; }),
  auto: asks.auto.map((text) => { const q = qr.qrMatrix(text); return q && [q.version, q.mask]; }),
  rs: qr.qrReedSolomon([32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17], 10),
  format: [0, 5].map((m) => { const q = qr.qrMatrix('hello', m);
    return [0, 1, 2, 3, 4, 5, 7, 8].map((y) => q.modules[y][8]).concat([7, 5, 4, 3, 2, 1, 0].map((x) => q.modules[8][x]))
      .map((b) => (b ? 1 : 0)).reverse().join(''); }),
  version7: (() => { const q = qr.qrMatrix('y'.repeat(120), 0); const out = [];
    for (let i = 0; i < 18; i++) out.push(q.modules[Math.floor(i / 3)][q.size - 11 + i % 3] ? 1 : 0);
    return out.reverse().join(''); })(),
}));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class QrEncoderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        asks = {"symbols": [[t, m] for t, m, _, _ in SYMBOLS],
                "auto": ["hello", "a" * 213, "a" * 214, "€" * 71, "€" * 72]}
        result = subprocess.run([NODE, "-e", QR_SCRIPT, str(WEB / "qr.js")], input=json.dumps(asks),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        if result.returncode:
            raise AssertionError(result.stderr)
        cls.out = json.loads(result.stdout)

    def test_whole_symbols_match_another_encoder(self):
        for (text, mask, version, digest), (got_version, got_mask, rows) in zip(SYMBOLS, self.out["symbols"]):
            with self.subTest(text=text[:20], mask=mask):
                self.assertEqual((got_version, got_mask), (version, mask))
                self.assertEqual(len(rows.split("/")), version * 4 + 17)
                self.assertEqual(hashlib.sha256(rows.encode()).hexdigest(), digest)

    def test_reed_solomon_of_the_hello_world_example(self):
        self.assertEqual(self.out["rs"], [196, 35, 39, 119, 235, 215, 231, 226, 93, 23])

    def test_format_and_version_information(self):
        # Level M with masks 0 and 5, and version 7's information, as the standard's tables give them.
        self.assertEqual(self.out["format"], ["101010000010010", "100000011001110"])
        self.assertEqual(self.out["version7"], "000111110010010100")

    def test_the_smallest_version_up_to_ten(self):
        (v1, _), (v10, _), too_long, (euros, _), more = self.out["auto"]
        self.assertEqual((v1, v10, euros), (1, 10, 10))      # 213 bytes is version 10-M's most
        self.assertIsNone(too_long)
        self.assertIsNone(more)                               # 72 three-byte characters: 216 bytes


SETUP = PAGE + """
  location.origin = 'http://localhost:8642';
  let printed = 0; window.print = () => { printed += 1; };
  const toasts = []; toast = (text) => toasts.push(text);
  const settle = async () => { for (let i = 0; i < 5; i++) { await null; flushTimers(); } };
  const sheet = () => document.querySelector('.label-sheet');
  const menu = (page) => deckMoreItems(page).filter((i) => i && i !== 'sep').map((i) => i.label);
  const built = () => { const page = makePage(); page.summary.status = 'built'; return page; };
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckLabelUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)],
                                input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_offered_only_on_built_decks(self):
        self.run_js("""
          assert(!menu(makePage()).includes('Print box label'));          // building
          const idea = makePage(); idea.summary.status = 'idea';
          assert(!menu(idea).includes('Print box label'));
          assert(menu(built()).includes('Print box label'));
          const product = built(); product.summary.id = 'product/fdc-test'; product.summary.read_only = true;
          assert(!menu(product).includes('Print box label'));             // a product's label is a later slice
        """)

    def test_the_label_has_colours_title_player_and_the_code(self):
        self.run_js("""
          const page = built();
          deckMoreItems(page).find((i) => i && i.label === 'Print box label').onclick(); await settle();
          assert.equal(printed, 1);
          const label = sheet().querySelector('.box-label');
          assert.equal(label.parentNode.getAttribute('class'), 'card-page');
          assert.equal(label.querySelector('.box-label-title').textContent, 'Test Deck');
          assert.equal(label.querySelector('.box-label-player').textContent, 'Played by Matt');
          same(label.querySelector('.box-label-colours').querySelectorAll('img').map((i) => i.getAttribute('src')),
               ['/sym/R.svg', '/sym/G.svg']);
          const code = label.querySelector('.qr-code');
          assert(code.getAttribute('aria-label').includes('Test Deck'));
          assert(/^M\\d/.test(code.querySelector('path').getAttribute('d')));
          window.fire('afterprint');
          assert.equal(sheet(), null);
        """)

    def test_the_code_opens_the_deck_page_at_the_tunnels_address(self):
        self.run_js("""
          assert.equal(boxLabelAddress('casual/test'), 'http://localhost:8642/#/deck?id=casual%2Ftest');
          state.me = {address: 'https://decklab.example.com'};
          assert.equal(boxLabelAddress('user2/casual/elves'), 'https://decklab.example.com/#/deck?id=user2%2Fcasual%2Felves');
          state.me = {address: 'javascript:alert(1)'};                    // only an https address is used
          assert(boxLabelAddress('casual/test').startsWith('http://localhost:8642/'));
        """)

    def test_a_persons_deck_has_no_played_by(self):
        self.run_js("""
          state.may = {see_inventory: ['user2']};
          const page = built(); page.summary.id = 'user2/casual/elves'; page.summary.space = 'user2';
          page.summary.player = null;
          printBoxLabel(page); await settle();
          assert.equal(sheet().querySelector('.box-label-player'), null);
          assert.equal(sheet().querySelector('.box-label-title').textContent, 'Test Deck');
        """)

    def test_an_address_too_long_for_the_code_prints_nothing(self):
        self.run_js("""
          const page = built(); page.summary.id = 'casual/' + 'x'.repeat(200);
          printBoxLabel(page); await settle();
          assert.equal(printed, 0); assert.equal(sheet(), null);
          assert(toasts.at(-1).includes('too long'));
        """)


if __name__ == "__main__":
    unittest.main()
