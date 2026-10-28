"""Checks of the page's own files in decklab/web/ (Milestone 2).

The server only serves what its allow-list finds in web/, web/icons/ and web/fonts/, so
these make sure every file the page refers to is actually served with a known
type, that the page loads nothing from the internet (PLAN.md part 7: no CDNs;
the two typefaces are self-hosted in web/fonts/), that the manifest and icons are fit for "Add to Home Screen",
that the dark theme follows both the system and the profile setting, and
(Milestone 4) that every write sends the header the server's write check
wants, and (Milestone 5) that the matchup screens read the contract's JSON,
ask before stopping a run, stop polling when their page is left, and keep the
review's fixes (wording, tap targets, focus, status icons, shared helpers).
They only read files: no network, no server. PageScriptTests also run a few of
the page's functions under Node.js, when it's installed, with a small stand-in
for the browser's document, to check what their words come out as.

Milestone 8 added per-card numbers from the card log to the matchup page and
the deck page: these check they read forge's keys and thresholds, fit a phone,
and say what they can and can't tell in words.

Milestone 7 split long files, so a check finds what it looks for in every
script the page loads (_scripts), every stylesheet (_styles) or a whole lib
module or package (_lib_text), not in one named file: moving a function to
another file then needs no test changed, and no check quietly reads less.

Run from the repo root: python -m unittest discover -s decklab/tests -t .
Interactive matchup and adaptive-play checks live in test_web_matchups.py; the
matchup screens' and per-card stats' source checks in test_web_matchup_files.py;
each page's source contract (route, endpoints, guards, phone CSS) in
test_web_pages.py. Static asset contracts, page-wide script and CSS rules and
the shared JavaScript test helpers remain here.
"""
import json
import random
import re
import shutil
import struct
import subprocess
import unittest
import zlib
from html.parser import HTMLParser

from decklab import server

WEB = server.WEB_DIR
MATCHUP_SCRIPTS = ("sim-ui.js", "matchups.js", "matchups-overview.js", "matchups-summary.js", "matchups-detail.js", "matchups-results.js", "matchups-play.js",
                   "matchups-cards.js")
PLAY_SCRIPTS = ("deck-tools.js", "deck-print.js", "qr.js", "deck-label.js", "collection.js", "precon-token-choices.js", "precon-coverage.js", "collection-rows.js", "collection-cards.js", "collection-bulk.js", "collection-guards.js", "collection-trade.js", "storage-locations.js", "assembly.js", "assembly-chooser.js", "assembly-switcher.js", "assembly-finish.js", "assembly-steps.js", "assembly-overlap.js", "assembly-sections.js", "assembly-progress.js", "assembly-sheets.js", "assembly-boxcheck.js", "box-collection.js", "box-editor.js", "box-repair.js", "hands.js", "play.js", "life-counter.js", "deck-sideboard.js", "deck-opponents.js", "deck-standins.js", "printings-in-box.js", "deck-swaps.js", "deck-considering.js", "deck-categories.js", "product-storage.js", "history.js", "compare.js", "activity.js", "activity-undo.js",
                "order-check-targets.js", "receipts.js", "receipt-tiles.js", "receipt-layout.js", "receipt-workflow.js", "accessories.js", "accessory-pictures.js", "tokens.js", "token-plan.js", "product-tokens.js")
SHELL_SCRIPTS = ("keyboard-help.js", "shell.js", "settings.js", "settings-members.js", "visibility.js", "arrival-notices.js")  # account pages, just before app.js
CARD_SCRIPTS = ("ui.js", "symbols.js", "cards-ui.js", "card-viewer.js")     # the shared card pieces (UI-KIT.md)
SCRIPTS = ("core.js", *CARD_SCRIPTS, "library.js", "library-boxchecks.js", "library-glance.js", "library-tables.js", "cover.js", "deck-availability.js", "deck.js", "deck-header.js", "deck-overview.js", "deck-retirement.js", "deck-rename.js", "deck-prices.js", "guide.js", "stats.js", "commander-readiness.js", "commander-night.js", "practice.js", "version.js", "wishlist.js", "shopping.js", "shopping-buying.js", "shopping-queue.js", "shopping-reprints.js", "shopping-snapshot.js", "shopping-orders.js", "shopping-order-edit.js", "shopping-order-rows.js", "shopping-order-split.js", "app.js",
           "editor.js", "editor-screen.js", "editor-details.js", "editor-lines.js", "editor-forge.js", "editor-cards.js", "editor-search-quantity.js", "editor-search-dock.js", "editor-swaps.js", "editor-save.js", "editor-deckpage.js",
           *MATCHUP_SCRIPTS, "field.js", "variant.js", "runs-pill.js", *PLAY_SCRIPTS, *SHELL_SCRIPTS)    # every script the page loads
# The design tokens, the base and the shared components first (decklab/UI-REVIEW.md 2.1-2.3), then the shell
# and the page files, which only lay the components out.
FOUNDATION = ("tokens.css", "base.css", "components.css")
STYLES = (*FOUNDATION, "cards-ui.css", "shell.css", "library.css", "deck.css", "deck-overview.css", "stats.css", "matchups.css", "field.css", "variant.css",
          "editor.css", "guide.css", "wishlist.css", "shopping.css", "shopping-orders.css", "collection.css", "play.css", "assembly.css", "assembly-steps.css", "assembly-overlap.css",
          "deck-tools.css", "receipts.css", "accessories.css", "tokens-page.css", "activity.css", "history.css", "compare.css")
SVG_NAMESPACE = "http://www.w3.org/2000/svg"     # a name, not something loaded


def _text(name):
    """A page file's text: web/<name>."""
    return (WEB / name).read_text(encoding="utf-8")


def _scripts(names=SCRIPTS):
    """The scripts' text, joined (each ends with a line break, so _function still finds the last one)."""
    return "\n".join(_text(name) for name in names)


def _styles():
    """Every stylesheet's text, joined in the order the page loads them (so the cascade order holds)."""
    return "\n".join(_text(name) for name in STYLES)


NODE = shutil.which("node")
# Runs page scripts under Node.js with a stand-in for the browser's document: enough for el() and for
# reading the text an element or a list of parts comes out as. stdin: [[script paths], [expressions]];
# stdout: each expression's text, as JSON. An expression starting "await " is waited for (a promise's value).
NODE_RUNNER = r"""
const fs = require("fs"), vm = require("vm");
class Node {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  getAttribute(key) { return key in this.attrs ? this.attrs[key] : null; }
  addEventListener() {}
  append(...items) { for (const item of items) this.children.push(typeof item === "string" ? new Text(item) : item); }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...items) { this.children = []; this.append(...items); }
  set textContent(value) { this.children = [new Text(String(value))]; }
  get textContent() { return this.children.map((child) => child.textContent).join(""); }
}
class Text extends Node {
  constructor(data) { super("#text"); this.data = data; }
  get textContent() { return this.data; }
}
const quiet = { addEventListener() {}, removeEventListener() {} };
const document = Object.assign({ createElement: (tag) => new Node(tag), createElementNS: (ns, tag) => new Node(tag),
  createTextNode: (data) => new Text(data), querySelector: () => null, querySelectorAll: () => [],
  documentElement: new Node("html"), body: new Node("body") }, quiet);
const context = { document, Node, console, setTimeout, clearTimeout, navigator: {}, location: { hash: "" },
  history: {}, fetch: () => Promise.reject(new Error("no network")),
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  window: Object.assign({ location: { hash: "" },
    matchMedia: () => Object.assign({ matches: false }, quiet) }, quiet) };
context.globalThis = context;
vm.createContext(context);
const [files, calls] = JSON.parse(fs.readFileSync(0, "utf8"));
for (const file of files) vm.runInContext(fs.readFileSync(file, "utf8"), context, { filename: file });
const text = (part) => part == null || part === false ? "" : Array.isArray(part) ? part.map(text).join("")
  : typeof part === "object" ? part.textContent : String(part);
(async () => {
  const out = [];
  for (const call of calls) {
    out.push(text(call.startsWith("await ") ? await vm.runInContext(call.slice(6), context) : vm.runInContext(call, context)));
  }
  process.stdout.write(JSON.stringify(out));
})();
"""


def _run_page(calls, names=("core.js", *MATCHUP_SCRIPTS)):
    """The text each of calls (JavaScript expressions, run in turn after the scripts names) comes out as,
    under Node.js with NODE_RUNNER's stand-in for the document."""
    done = subprocess.run([NODE, "-e", NODE_RUNNER], input=json.dumps([[str(WEB / n) for n in names], calls]),
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    if done.returncode:
        raise AssertionError(f"node failed: {done.stderr[-2000:]}")
    return json.loads(done.stdout)


def _lib_text(name):
    """A lib module's source: lib/<name>.py, or every file of the lib/<name>/ package, joined."""
    lib = WEB.parent / "lib"
    if (lib / f"{name}.py").exists():
        return (lib / f"{name}.py").read_text(encoding="utf-8")
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted((lib / name).rglob("*.py")))


class _References(HTMLParser):
    """Every src and href in a page, and its <meta> and <link> tags."""

    def __init__(self):
        super().__init__()
        self.refs, self.metas, self.links = [], [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for key in ("src", "href"):
            if attrs.get(key):
                self.refs.append((tag, attrs[key]))
        if tag == "meta":
            self.metas.append(attrs)
        if tag == "link":
            self.links.append(attrs)


def png_size(data):
    """(width, height) of a PNG, checking its signature, chunk CRCs and pixel data."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    pos, chunks = 8, {}
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        crc, = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])
        assert zlib.crc32(kind + body) & 0xFFFFFFFF == crc, f"bad CRC in {kind}"
        chunks[kind] = chunks.get(kind, b"") + body
        pos += 12 + length
    width, height, depth, colour = struct.unpack(">IIBB", chunks[b"IHDR"][:10])
    channels = {2: 3, 6: 4}[colour]
    assert depth == 8
    assert len(zlib.decompress(chunks[b"IDAT"])) == height * (1 + width * channels)
    assert b"IEND" in chunks
    return width, height


def _skip_string(text, i):
    """The index just past the string literal that starts at text[i] (' " or `, with ${...} in a template)."""
    quote = text[i]
    i += 1
    while text[i] != quote:
        if text[i] == "\\":
            i += 2
            continue
        if quote == "`" and text.startswith("${", i):
            i = _skip_group(text, i + 1)
            continue
        i += 1
    return i + 1


def _starts_regex(text, i):
    """True when text[i] is the "/" that opens a regular expression literal (not a division or a comment)."""
    return (text[i] == "/" and not text.startswith("//", i)
            and re.search(r"(^|[(,=:\[!&|?{};])\s*$", text[max(0, i - 40):i]) is not None)


def _skip_regex(text, i):
    """The index just past the regular expression literal that starts at text[i] (and its flags)."""
    i += 1
    in_class = False
    while in_class or text[i] != "/":
        if text[i] == "\\":
            i += 1
        elif text[i] == "[":
            in_class = True
        elif text[i] == "]":
            in_class = False
        i += 1
    i += 1
    while text[i].isalpha():
        i += 1
    return i


def _skip_group(text, i):
    """The index just past the bracket that closes the one at text[i] (strings inside are skipped)."""
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack = [pairs[text[i]]]
    i += 1
    while stack:
        c = text[i]
        if c in "'\"`":
            i = _skip_string(text, i)
            continue
        if c == "/" and text.startswith("//", i):
            i = text.index("\n", i)
            continue
        if _starts_regex(text, i):
            i = _skip_regex(text, i)
            continue
        if c in pairs:
            stack.append(pairs[c])
        elif c == stack[-1]:
            stack.pop()
        i += 1
    return i


def _top_level(arg):
    """arg with every bracketed part and string emptied, so only its own operators are left."""
    out, i = [], 0
    while i < len(arg):
        c = arg[i]
        if c in "'\"`":
            i = _skip_string(arg, i)
            out.append('""')
        elif _starts_regex(arg, i):
            i = _skip_regex(arg, i)
            out.append("/x/")
        elif c in "([{":
            i = _skip_group(arg, i)
            out.append("()")
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _native_appends(script):
    """[(arguments, line)] of every node.append(...) call in a script, each argument as written."""
    found = []
    for match in re.finditer(r"\.append\(", script):
        start = match.end() - 1
        end = _skip_group(script, start)
        inner, args, i, begin = script[start + 1:end - 1], [], 0, 0
        while i < len(inner):
            c = inner[i]
            if c in "'\"`":
                i = _skip_string(inner, i)
                continue
            if _starts_regex(inner, i):
                i = _skip_regex(inner, i)
                continue
            if c in "([{":
                i = _skip_group(inner, i)
                continue
            if c == ",":
                args.append(inner[begin:i].strip())
                begin = i + 1
            i += 1
        if inner[begin:].strip():
            args.append(inner[begin:].strip())
        found.append((args, script.count("\n", 0, match.start()) + 1))
    return found


def _enclosing_function(script, pos):
    """The top-level function (its whole text) that the character at pos is in."""
    starts = [m for m in re.finditer(r"^(?:async )?function (\w+)\(", script, re.M) if m.start() < pos]
    start = starts[-1].start()
    return script[start:script.index("\n}\n", start) + 2]


def _function(script, name):
    """A top-level function's whole text, by name."""
    match = re.search(rf"^(?:async )?function {name}\(", script, re.M)
    return script[match.start():script.index("\n}\n", match.start()) + 2]


def _inner(body, name):
    """A function's text inside another one's (body), by name: up to its closing brace."""
    match = re.search(rf"(?:async )?function {name}\(", body)
    return body[match.start():_skip_group(body, body.index("{", match.end()))]


class WebFileTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.files = server.static_files(WEB)
        cls.page = _References()
        cls.page.feed((WEB / "index.html").read_text(encoding="utf-8"))

    def served(self, url):
        return self.files.get(url.split("?", 1)[0])

    def test_every_file_in_web_is_served(self):
        for path in WEB.rglob("*"):
            if path.is_file():
                with self.subTest(path=path.name):
                    self.assertIn("/" + path.relative_to(WEB).as_posix(), self.files)
        for name in ("/", "/index.html", "/manifest.webmanifest", *("/" + n for n in SCRIPTS + STYLES)):
            self.assertIn(name, self.files)

    def test_the_page_refers_only_to_served_files(self):
        self.assertTrue(self.page.refs)
        for tag, url in self.page.refs:
            with self.subTest(url=url):
                if url.startswith("#"):
                    continue
                self.assertTrue(url.startswith("/") and not url.startswith("//"), url)
                self.assertIsNotNone(self.served(url), url)

    def test_nothing_is_loaded_from_the_internet(self):
        for tag, url in self.page.refs:
            self.assertNotRegex(url, r"^(https?:)?//", url)
        css = "\n".join(path.read_text(encoding="utf-8") for path in WEB.rglob("*.css"))
        self.assertNotIn("@import", css)
        for url in re.findall(r"url\(\s*['\"]?([^'\")]+)", css):
            self.assertTrue(url.startswith("data:") or url.startswith("/"), url)
        for name in SCRIPTS:
            script = _text(name).replace(SVG_NAMESPACE, "")
            self.assertNotRegex(script, r"https?://", name)
            self.assertNotRegex(script, r"\bimport\s*\(|importScripts", name)
            for call in re.findall(r"\bapi(?:Write)?\(\s*[`'\"]([^`'\"]*)", script):
                self.assertTrue(call.startswith("/api/"), call)

    def test_the_typefaces_are_self_hosted_and_preloaded(self):
        # design/visual-design.md 2.3: Figtree (upright and italic) and JetBrains Mono are woff2 files in
        # web/fonts/, declared in base.css, with the system fonts after them in --font and --font-mono and
        # their licences kept in the repo. Figtree's upright face and (since E11-S30 slice 6 put Forge's mono
        # figures in the first view of Matchups and every lab table) JetBrains Mono are preloaded, each at exactly
        # its @font-face URL (any other URL would fetch the file twice); Figtree's italic loads when it's used.
        base = _text("base.css")
        faces = re.findall(r'font-family:\s*"([^"]+)";\s*src:\s*url\("([^"]+)"\) format\("woff2"\);'
                           r'\s*font-weight:[^;]+;\s*font-style:\s*(\w+);', base)
        self.assertEqual(faces, [("Figtree", "/fonts/figtree.woff2", "normal"),
                                 ("Figtree", "/fonts/figtree-italic.woff2", "italic"),
                                 ("JetBrains Mono", "/fonts/jetbrains-mono.woff2", "normal")])
        self.assertEqual(server.STATIC_TYPES[".woff2"], "font/woff2")
        for family, url, style in faces:
            with self.subTest(url=url):
                self.assertIsNotNone(self.served(url), url)
                self.assertEqual(self.served(url).read_bytes()[:4], b"wOF2")
        preloads = [link["href"] for link in self.page.links if link.get("rel") == "preload"]
        self.assertEqual(preloads, ["/fonts/figtree.woff2", "/fonts/jetbrains-mono.woff2"])
        for link in self.page.links:
            if link.get("rel") == "preload":
                self.assertEqual((link.get("as"), link.get("type")), ("font", "font/woff2"))
                self.assertIn("crossorigin", link)      # fonts are fetched in CORS mode, even same-origin
        tokens = _text("tokens.css")
        self.assertRegex(tokens, r'--font: "Figtree", system-ui,')
        self.assertRegex(tokens, r'--font-mono: "JetBrains Mono", ui-monospace,')
        for name in ("figtree-OFL.txt", "jetbrains-mono-OFL.txt"):
            self.assertIn("SIL Open Font License", (WEB.parent / "fonts-licences" / name).read_text(encoding="utf-8"))

    def test_scripts_load_in_order(self):
        # The editor and matchup scripts define what app.js's routes call, so they come first (all deferred).
        # sim-ui.js supplies Forge's result pieces and matchups.js shared constants; overview, detail, results and
        # card stats follow in order.
        # The matchup detail screen uses editor.js's ask(). core.js comes first of the
        # rest (practice.js reads its NAV_SPACE as it loads), and app.js last (its start() needs every other file).
        scripts = [url for tag, url in self.page.refs if tag == "script"]
        self.assertEqual(scripts, ["/editor.js", "/editor-screen.js", "/editor-details.js", "/editor-lines.js",
                         "/editor-forge.js", "/editor-cards.js", "/editor-search-quantity.js", "/editor-search-dock.js", "/editor-swaps.js", "/editor-save.js", "/editor-deckpage.js", *["/" + name for name in MATCHUP_SCRIPTS], "/field.js",
                                   "/variant.js", "/runs-pill.js", "/core.js", *["/" + name for name in CARD_SCRIPTS],
                               "/library.js", "/library-boxchecks.js", "/library-glance.js", "/library-tables.js", "/cover.js", "/deck-availability.js", "/deck.js", "/deck-header.js", "/deck-overview.js", "/deck-retirement.js", "/deck-rename.js", "/deck-prices.js", "/guide.js", "/stats.js", "/commander-readiness.js", "/commander-night.js", "/practice.js", "/version.js", "/wishlist.js", "/shopping.js", "/shopping-buying.js", "/shopping-queue.js", "/shopping-reprints.js", "/shopping-snapshot.js", "/shopping-orders.js", "/shopping-order-edit.js", "/shopping-order-rows.js", "/shopping-order-split.js",
                               *["/" + name for name in PLAY_SCRIPTS], *["/" + name for name in SHELL_SCRIPTS], "/app.js"])
        self.assertEqual(sorted(s.lstrip("/") for s in scripts), sorted(SCRIPTS))
        # Every script in web/ is one the page loads (and so one these tests read).
        self.assertEqual(sorted(path.name for path in WEB.glob("*.js")), sorted(SCRIPTS))

    def test_stylesheets_load_in_order(self):
        # The cascade depends on the order: tokens, base and components first (decklab/UI-REVIEW.md 2.1-2.3),
        # then the page files, which lay the components out.
        sheets = [link.get("href") for link in self.page.links if link.get("rel") == "stylesheet"]
        self.assertEqual(sheets, ["/" + name for name in STYLES])
        self.assertEqual(STYLES[:3], ("tokens.css", "base.css", "components.css"))
        self.assertEqual(sorted(path.name for path in WEB.glob("*.css")), sorted(STYLES))
        # Only tokens.css defines the theme: no other stylesheet sets a custom property on :root's theme.
        for name in STYLES[1:]:
            with self.subTest(sheet=name):
                self.assertNotIn("data-theme", _text(name))
                self.assertNotIn("prefers-color-scheme", _text(name))

    def test_page_files_use_the_scales(self):
        # WP3: font sizes, radii, shadows and colours come from tokens.css. A page file writes var(--fs-*),
        # var(--r-*), var(--shadow-*) and colour tokens, not literals (print styles, card-shaped radii in %,
        # the CSS-drawn mana symbols' glyphs and a mask's alpha excepted).
        for name in STYLES[1:]:
            css = re.sub(r"/\*.*?\*/", "", _text(name), flags=re.S)
            css = re.sub(r"@media print \{.*?\n\}", "", css, flags=re.S)
            css = re.sub(r'url\("data:[^"]*"\)', "", css)
            with self.subTest(sheet=name):
                sizes = re.findall(r"font-size:\s*([^;}]+)", css)
                self.assertEqual([v for v in sizes if not re.match(r"var\(--fs-|inherit|max\(16px, 1rem\)|\.[89]em", v.strip())
                                  and not re.fullmatch(r"(7\.5|8|10)px", v.strip())], [])
                radii = re.findall(r"border-radius:\s*([^;}]+)", css)
                self.assertEqual([v for v in radii if not re.fullmatch(r"((var\(--r-[a-z]+\)|0|50%|1px)\s*)+", v.strip())], [])
                shadows = re.findall(r"box-shadow:\s*([^;}]+)", css)
                self.assertEqual([v for v in shadows if re.search(r"rgba?\(|#[0-9a-f]{3}", v)], [])
                masks = re.sub(r"mask-image:[^;]+;", "", css)
                self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", masks), [])

    def test_every_script_is_strict(self):
        # Each classic script needs its own "use strict" (it isn't shared), before any code.
        for name in SCRIPTS:
            with self.subTest(script=name):
                code = re.sub(r"/\*.*?\*/", "", _text(name), count=1, flags=re.S).lstrip()
                self.assertTrue(code.startswith('"use strict";\n'), code[:60])

    def test_every_write_sends_the_write_check_header(self):
        # Milestone 4: the server refuses a POST or PUT without JSON and "X-Deck-Lab: 1" (check_write),
        # so every write goes through apiWrite(), and nothing else sends one.
        helper = _function(_scripts(), "apiWrite")
        self.assertIn('"X-Deck-Lab": "1"', helper)
        self.assertIn('"Content-Type": "application/json"', helper)
        for name in SCRIPTS:
            rest = _text(name).replace(helper, "")
            with self.subTest(script=name):
                self.assertNotRegex(rest, r"method:\s*[\"'`](POST|PUT|PATCH|DELETE)")
        # Crop Undo reads verified photo bytes with one explicit GET. All other
        # reads use api(); this exception must not allow another write path.
        photo = _function(_text("activity-undo.js"), "activityUndoPhotoPreview")
        self.assertEqual(len(re.findall(r"\bfetch\(", photo)), 1)
        self.assertEqual(re.findall(r"method:\s*[\"'`](\w+)[\"'`]", photo), ["GET"])
        rest = _scripts().replace(helper, "").replace(photo, "")
        self.assertEqual(len(re.findall(r"\bfetch\(", rest)), 1)
        self.assertIn("fetch(", _function(rest, "api"))

    def test_home_screen_tags(self):
        metas = {m.get("name"): m.get("content") for m in self.page.metas if m.get("name")}
        self.assertIn("width=device-width", metas["viewport"])
        self.assertEqual(metas["apple-mobile-web-app-capable"], "yes")
        self.assertEqual(metas["apple-mobile-web-app-title"], "Deck Lab")
        self.assertIn("theme-color", metas)
        rels = {link.get("rel"): link.get("href") for link in self.page.links}
        self.assertEqual(rels["manifest"], "/manifest.webmanifest")
        touch = self.served(rels["apple-touch-icon"])
        self.assertEqual(png_size(touch.read_bytes()), (180, 180))

    def test_manifest(self):
        manifest = json.loads((WEB / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "Deck Lab")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["start_url"], "/")
        for key in ("theme_color", "background_color"):
            self.assertRegex(manifest[key], r"^#[0-9a-f]{6}$")
        sizes = set()
        for icon in manifest["icons"]:
            with self.subTest(icon=icon["src"]):
                path = self.served(icon["src"])
                self.assertIsNotNone(path)
                self.assertEqual(icon["type"], "image/png")
                w, h = png_size(path.read_bytes())
                self.assertEqual(f"{w}x{h}", icon["sizes"])
                sizes.add(icon["sizes"])
        self.assertLessEqual({"192x192", "512x512"}, sizes)

    def test_every_icon_is_a_real_png(self):
        sizes = {"icon-32.png": 32, "icon-192.png": 192, "icon-512.png": 512, "apple-touch-icon.png": 180}
        found = sorted(p.name for p in (WEB / "icons").iterdir() if p.suffix == ".png")
        self.assertEqual(found, sorted(sizes))
        for name, size in sizes.items():
            with self.subTest(icon=name):
                self.assertEqual(png_size((WEB / "icons" / name).read_bytes()), (size, size))

    def test_themes(self):
        # The dark colours are written once (UI-REVIEW 2.1): <html> always has data-theme="light" or "dark",
        # "Auto" resolved from the system's (and followed as it changes) by app.js, and before the first paint by
        # index.html's own script, so a dark page never flashes light.
        css = re.sub(r"/\*.*?\*/", "", _text("tokens.css"), flags=re.S)
        self.assertEqual(css.count(':root[data-theme="dark"]'), 1)
        self.assertNotIn("prefers-color-scheme", _styles())
        light = re.search(r":root \{(.*?)\n\}", css, re.S).group(1)
        dark = re.search(r':root\[data-theme="dark"\] \{(.*?)\n\}', css, re.S).group(1)
        names = lambda block: set(re.findall(r"(--[\w-]+):", block))
        self.assertLessEqual(names(dark), names(light))         # dark only sets what light defines
        for token in ("--accent", "--link", "--page", "--surface", "--ink", "--shadow-1", "--shadow-2"):
            with self.subTest(token=token):
                self.assertIn(token, names(dark))
        self.assertIn("--accent: #6236c4;", light)              # violet: no mana colour is purple
        self.assertIn("--accent: #a68cf0;", dark)
        self.assertIn("--link: #43248f;", light)               # links dark violet, info boxes blue
        self.assertIn("background: var(--page)", _styles())
        head = _text("index.html").split("</head>")[0]
        self.assertIn('matchMedia("(prefers-color-scheme: dark)")', head)
        self.assertIn('setAttribute("data-theme", theme)', head)
        apply = _function(_text("app.js"), "applyTheme")
        self.assertIn('root.setAttribute("data-theme", shown)', apply.replace("document.documentElement", "root"))
        self.assertNotIn("removeAttribute", apply)
        self.assertIn('SYSTEM_DARK.addEventListener("change"', _text("app.js"))

    def test_nothing_that_can_be_null_goes_to_a_native_append(self):
        # Review finding: Element.append(null) inserts the text "null" (unlike the page's add() and el(),
        # which skip it), so a "null" showed under the owned-vs-needed table. A function that can return
        # null, or a "... ? x : null" part, is only ever handed to add() or el().
        # The scripts share one scope, so a function in one can be called from another.
        everything, can_be_null = _scripts(), set()
        for match in re.finditer(r"^function (\w+)\(", everything, re.M):
            end = everything.find("\n}\n", match.end())
            if "return null;" in everything[match.end():end]:
                can_be_null.add(match.group(1))
        for name in SCRIPTS:
            script = _text(name)
            for args, line in _native_appends(script):
                with self.subTest(script=name, line=line):
                    for arg in args:
                        call = re.fullmatch(r"(\w+)\(.*\)", arg, re.S)
                        self.assertFalse(call and call.group(1) in can_be_null, arg)
                        self.assertFalse(_top_level(arg).rstrip().endswith(": null"), arg)

    def test_history_entries_keep_their_place(self):
        # Review finding: the editor's leave guard wrote the editor's address over the deck page's entry
        # after Back, so the next Back skipped it. Entries carry their place (history.state.pos, app.js
        # entryPos) and replaceState keeps it.
        for name in SCRIPTS:
            script = _text(name)
            with self.subTest(script=name):
                self.assertNotIn("replaceState(null", script)
                # The one kind of new entry, the card viewer's and a sheet's (so a phone's Back closes them),
                # carries the next place.
                for call in re.findall(r"pushState\((.*?)\);", script):
                    self.assertIn("pos: here + 1", call)
        self.assertEqual(sum(_text(name).count("pushState(") for name in SCRIPTS), 1)
        self.assertIn("pushState(", _function(_scripts(), "pushHistoryEntry"))
        self.assertIn("pushHistoryEntry(", _function(_scripts(), "pushViewerEntry"))
        self.assertIn("pushHistoryEntry(", _function(_scripts(), "pushSheetEntry"))

    def test_every_discard_asks_first(self):
        # Review finding: "Discard my changes" in the save review's "the deck changed" branch threw the
        # changes away at once, while the same button in the banner asked first. Every such button goes
        # through askDiscardChanges() (a deck that was deleted asks in goneActions()), so discardChanges()
        # is only ever called once the person has said so.
        script = _scripts()
        asking = _function(script, "askDiscardChanges")
        calls = [m.start() for m in re.finditer(r"(?<![\w.])discardChanges\(", script)]
        callers = {_enclosing_function(script, pos).split("(")[0] for pos in calls
                   if not script.startswith("function discardChanges(", pos - len("function "))}
        self.assertEqual(callers, {"async function askDiscardChanges"})
        self.assertIn('value: "discard"', asking)
        gone = _function(script, "goneActions")
        self.assertLess(gone.index("await ask("), gone.index("removeDraft("))
        buttons = [line for line in script.splitlines() if 'text: "Discard my changes"' in line]
        self.assertGreaterEqual(len(buttons), 5)
        for line in buttons:
            with self.subTest(line=line.strip()):
                self.assertTrue("askDiscardChanges(" in line or 'value: "discard"' in line
                                or ("onclick: async" in line and line in gone), line)

    def test_table_updates_say_nothing_about_git(self):
        # Phase 4 (R8): a table update is one save in Deck Lab, so the page sends only the decks and
        # words nothing about commits or changes made outside Deck Lab.
        script = _scripts()
        writes = [m.start() for m in re.finditer(r'apiWrite\("/api/tables/update"', script)]
        self.assertEqual(len(writes), 2)       # "Update their tables" and the deck page's own table
        for pos in writes:
            body = _enclosing_function(script, pos)
            with self.subTest(function=body.split("(")[0]):
                self.assertNotIn("include_outside", body)
                self.assertNotIn("commit", body.lower())
        for name in ("savedBox", "staleTablesPart", "updatedWords", "staleTableBox", "tableConflictWords"):
            with self.subTest(function=name):
                self.assertNotRegex(_function(script, name), r"(?i)commit|git\b|outside Deck Lab")

    def test_the_page_reads_the_contract_additions(self):
        # Milestone 4's final round added keys both sides must spell the same way: the search's close
        # spellings and the cards each warning is about. The page falls back when one is missing (an
        # older server). (A check's 409 for a renamed deck's "moved_to" went in phase 5: decks can't be
        # renamed, so neither side spells it any more.)
        script = _scripts()
        server = _lib_text("api")
        # Ban the exact legacy identifier; removed_token_row_id is a distinct
        # stable-row Undo receipt that legitimately contains this substring.
        self.assertNotRegex(script, r"\bmoved_to\b")
        self.assertNotIn('"moved_to"', server)
        for key in ("did_you_mean", "warning_cards"):
            with self.subTest(key=key):
                self.assertIn(key, script)
                self.assertIn(f'"{key}"', server)
        self.assertIn("answer.did_you_mean || []", script)
        self.assertIn("closeCards(q)", _function(script, "lookUp"))
        self.assertIn("a.warning_cards.length === warnings.length", _function(script, "checkWarnings"))
        self.assertIn("goneFrom(e)", _function(script, "runCheck"))

    def test_keyboard_check_remembers_the_full_screen(self):
        # Review finding: the bar stayed over the suggestions when the on-screen keyboard was already up (for
        # the title, or a quantity) as the search box got the focus, because the height with no keyboard was
        # taken whenever the box didn't have the focus. It's the tallest height seen at that width now.
        script = _scripts()
        body = _function(script, "noteKeyboard")
        self.assertNotRegex(body, r"!typing\s*\|\|")
        self.assertIn("h > fullHeight", body)
        self.assertIn("fullWidth", body)

    def test_editor_layout_rules(self):
        # Review findings from the phone review (390 px wide).
        css = _styles()
        script = _scripts()
        # "Target list | Owned-only version (none yet)" stays one row; "(none yet)" wraps inside its button.
        self.assertRegex(css, r"\.edit-head \.version-pick \.segmented \{[^}]*flex-wrap: nowrap")
        self.assertRegex(css, r"\.edit-head \.version-pick \.segmented > \* \{[^}]*flex-wrap: wrap[^}]*white-space: nowrap")
        # The collapsed "Deck details": chevron and words in the middle of its 44 px; the words wrap together.
        summary = re.search(r"details\.edit-details > summary \{([^}]*)\}", css).group(1)
        self.assertIn("align-items: center", summary)
        self.assertIn('class: "details-line"', _function(script, "detailsPart"))
        # What an update did (or its error) doesn't run into the next heading.
        self.assertRegex(css, r"\.stale-part > h3:not\(:first-child\) \{ margin-top: var\(--s-\d\); \}")

    def test_no_name_is_defined_twice(self):
        # The scripts share one global scope (classic scripts), so a function or constant defined in two of
        # them would make the page stop with a SyntaxError, or quietly use the wrong one.
        seen = {}
        for name in SCRIPTS:
            script = _text(name)
            for match in re.finditer(r"^(?:async )?function ([\w$]+)\(|^(?:const|let|var|class) ([\w$]+)",
                                     script, re.M):
                defined = match.group(1) or match.group(2)
                with self.subTest(name=defined):
                    self.assertNotIn(defined, seen, f"{defined} is in {seen.get(defined)} and {name}")
                seen[defined] = name

    def test_shadow_token_works_inside_a_list_of_shadows(self):
        # Review finding: dark mode's "--shadow: none" made "box-shadow: 0 0 0 1px ..., var(--shadow)"
        # invalid, so the selected button of a segmented switch lost its outline in dark mode.
        css = _styles()
        self.assertRegex(css, r"box-shadow: [^;]+, var\(--shadow-1\);")
        for value in re.findall(r"--shadow(?:-[\w]+)?:\s*([^;]+);", css):
            self.assertNotEqual(value.strip(), "none")

    def test_desktop_layout(self):
        # A maximised window on the PC's QHD screen is about 2,545 px: from 1,600 px the page spreads out.
        # The decklist's pictures are its Cards tab's "Pictures" view at every width (WP7: a phone and an iPad
        # get them too), remembered on the device. The card peek shows only with a mouse; anywhere else it's
        # display: none, so a phone never fetches its lazy image.
        css = _styles()
        wide = re.findall(r"@media \(min-width: 1600px\) \{\n(.*?)\n\}", css, re.S)
        self.assertGreaterEqual(len(wide), 1)
        desktop = "\n".join(wide)
        self.assertIn(".wrap { max-width: 2560px; }", desktop)
        cards = _function(_scripts(), "redrawCards")
        self.assertIn('el("div", { class: "card-tiles deck-tiles" }, items)', cards)
        self.assertIn("local.set(CARDS_VIEW_KEY, mode)", cards)
        self.assertIn("local.get(CARDS_VIEW_KEY)", _function(_scripts(), "cardsMode"))
        self.assertIn(".card-peek { display: none; }", css)
        # From 1,400 px: a laptop (MacBook Air 13, 1,470 px) has the peek too, 280 px wide (tokens.css --peek-w).
        peek = re.findall(r"@media \(min-width: 1400px\) and \(hover: hover\) and \(pointer: fine\) \{\n(.*?)\n\}",
                          css, re.S)
        self.assertEqual(len(peek), 1)
        self.assertRegex(peek[0], r"\.card-peek \{[^}]*display: block")
        script = _scripts()
        # The normal image only where the wide layout shows the picture big: phones keep the small one.
        thumb = _function(script, "cardThumb")
        self.assertIn("${card.img_small} 146w, ${card.img} 488w", thumb)
        self.assertIn('cardThumb(card, "thumb", 40, opts.thumbWide)', _function(script, "cardRow"))
        self.assertIn('viewerGroup: "deck"', _function(script, "deckCardRow"))
        self.assertIn('viewerGroup: "deck"', _function(script, "deckCardTile"))
        # The editor's dense rows show a small crop of the art: the small image is enough at every width.
        self.assertIn('class: "edit-thumb", src: card.img_small', _function(script, "lineRow"))
        # Lazy, and for the eye only: screen readers have the overlay.
        layout = _function(script, "peekLayout")
        self.assertIn('loading: "lazy"', layout)
        self.assertIn('"aria-hidden": "true"', layout)
        for name in ("drawDeck", "drawEditor"):
            with self.subTest(page=name):
                self.assertIn("peekLayout(", _function(script, name))
        self.assertIn("setUpPeek();", _function(script, "start"))
        # The picture changes with the name: the last card's never shows under this one's.
        show = _function(script, "showPeek")
        self.assertLess(show.index('img.classList.add("is-loading")'), show.index("img.src = card.img"))
        self.assertIn(".peek-img.is-loading", peek[0])


if __name__ == "__main__":
    unittest.main()
