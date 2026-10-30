"""Source checks of each page's contract: its route, endpoints, active-page guards and phone-first CSS.

They read field.js, accessories.js, tokens.js, collection.js and core.js's may/can helpers;
no network, no server. The shared helpers stay in test_web.
"""
import re
import unittest

from decklab.tests.test_web import STYLES, _function, _scripts, _text


class PageSourceTests(unittest.TestCase):

    def test_the_field_part(self):
        # Wave 3's "Against the field" (forge-trial/sim-wave3-contract.md section 10.6): every class field.js and
        # field.css add starts with "fv-" (the editor owns .field and its relatives); the rest are the page's
        # shared ones, defined in the other stylesheets.
        css = re.sub(r"/\*.*?\*/", "", _text("field.css"), flags=re.S)
        own = set(re.findall(r"\.([A-Za-z][\w-]*)", re.sub(r":not\([^)]*\)", "", css)))    # what it styles
        self.assertTrue(own)
        self.assertEqual({name for name in own if not name.startswith("fv-")}, set())
        others = "\n".join(_text(name) for name in STYLES if name != "field.css")
        shared = set(re.findall(r"\.([A-Za-z][\w-]*)", re.sub(r"/\*.*?\*/", "", others, flags=re.S)))
        script = _scripts(["field.js", "field-membership.js"])
        used = {name for value in re.findall(r'class: "([^"]+)"', script) for name in value.split()}
        used |= set(re.findall(r"`(fv-[\w-]+)", script))
        self.assertEqual({name for name in used if not name.startswith("fv-") and name not in shared}, set())
        self.assertEqual({name for name in used if name.startswith("fv-") and name not in own}, set())
        # A Beginner Box half has no part (so no "Field" button); the others get id "sec-field".
        section = _function(script, "fieldSection")
        self.assertIn("s.id.startsWith(BOX_PREFIX)) return null;", section)
        self.assertIn('id: "sec-field"', section)
        # It asks /api/field with the profile, writes only through apiWrite, asks before Stop, and stops asking
        # once the page is left.
        self.assertIn("/api/field?id=", section)
        self.assertIn('fvWrite(ctx, "/api/field/run"', _function(script, "fvPlay"))
        self.assertIn('fvWrite(ctx, "/api/field/stop"', _function(script, "fvStop"))
        self.assertIn("await ask(", _function(script, "fvStop"))           # a sheet, as every Stop asks
        self.assertIn("apiWrite(path", _function(script, "fvWrite"))
        self.assertIn("ctx.token === routeToken", _function(script, "fvHere"))
        self.assertIn("fvHere(ctx)", _function(script, "fvSchedule"))
        # The headline, the trust note (in "How this is worked out", MU-09) and the budgets in the run vocabulary
        # (MU-05); one empty state with Play when nothing is played (MU-08).
        self.assertIn("Against an average house deck:", _function(script, "fvHeadline"))
        self.assertIn('winRateFigure(average, { size: "hero"', _function(script, "fvHeadline"))
        self.assertIn("only to about ±8 points of win rate", script)
        self.assertIn("FV_TRUST", _function(script, "fvHow"))
        self.assertIn('[["quick", "Quick look"], ["standard", "Settle it"], ["thorough", "Precise"]]', script)
        self.assertIn("games a deck", _function(script, "fvBudgetWords"))
        self.assertIn('class: "empty fv-empty"', _function(script, "fvDraw"))
        self.assertIn('"data-run": true', _function(script, "fvPlayBox"))
        # Phone first; mini bars from 600 px, two columns of rows from 1,000 px, a table beside the tiles from
        # 1,600 px (the breakpoint ladder, decklab/UI-REVIEW.md 2.1).
        for width in ("600px", "1000px", "1600px"):
            self.assertIn(f"@media (min-width: {width})", css)
        # Touch targets of at least 44 px.
        for name in (".fv-row", ".fv-chip"):
            block = css[css.index(name + " {"):]
            self.assertIn("min-height: 44px", block[:block.index("}")], name)

    def test_the_accessories_page(self):
        # The Accessories page and picture helpers: its route, the globals the deck page, library,
        # packing plan and editor use, the endpoints it calls, and the link it never fetches itself.
        script = _text("accessories.js") + "\n" + _text("accessory-pictures.js")
        for name in ("openAccessorySheet", "accessoryThumb", "kitPicker", "kitChip", "showAccessories"):
            with self.subTest(name=name):
                self.assertRegex(script, rf"(?m)^(?:async )?function {name}\(")
        self.assertIn('if (path === "accessories") return mayDo("see_accessories") ? showAccessories(token) : '
                      'showNoAccessories();', _function(_text("app.js"), "route"))
        for path in ('"/api/accessories"', '"/api/accessories/fetch"', '"/api/accessories/save"',
                     '"/api/accessories/assign"'):
            with self.subTest(path=path):
                self.assertIn(path, script)
        # Phase 4: saves are the database's; nothing about git, commits or retrying them is left.
        for gone in ('"/api/accessories/commit"', "commit_pending", "uncommitted", "Retry saving history",
                     "accCommitWords"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, script)
        self.assertIn('placeholder: "Product or picture link"', script)
        self.assertIn('type: "url", inputmode: "url"', script)
        self.assertIn('type: "number", inputmode: "numeric"', script)
        self.assertIn("Count every sleeve of this design, loose ones too", script)
        # Stored pictures use Deck Lab's route; local drafts opt into data URLs. Shop links stay links.
        self.assertIn('url.startsWith("/accessory-img/")', _function(script, "accessoryThumb"))
        self.assertIn("sourceLink(", _function(script, "accLink"))
        # Writes stay tied to the page and person that started them.
        self.assertIn("view.token === routeToken", _function(script, "accessoriesActive"))
        self.assertIn("state.profile.id === view.profile", _function(script, "accessoriesActive"))
        css = _text("accessories.css")
        for width in ("600px", "1600px"):
            self.assertIn(f"@media (min-width: {width})", css)
        self.assertIn("minmax(min(100%, 150px), 1fr)", css)
        self.assertIn("@media (forced-colors: active)", css)
        self.assertIn("min-height: 44px", css)
        # WP9: click to edit (Remove at the sheet's bottom), no "Not in use" chip (unused is the usual case), a
        # read-only visitor's details sheet (notes and shop link), a dashed slot for nothing chosen,
        # products' sleeves and boxes through the kit picker (no select that saves on change), and the built
        # decks without sleeves.
        self.assertNotIn("Remove", _function(script, "accCard"))
        self.assertNotIn("Not in use", _function(script, "accCard"))
        self.assertIn("accDetails(view, item)", _function(script, "accCard"))
        details = _function(script, "accDetails")
        for part in ("item.notes", "accLink(item)", "used_by"):
            self.assertIn(part, details)
        self.assertNotIn('"Free"', script)
        self.assertIn("acc-slot-none", _function(script, "accessoryThumb"))
        self.assertIn(".acc-slot-none {", css)
        self.assertIn("accChoose(view, product, field, ref)", _function(script, "accProductsPanel"))
        self.assertNotIn('el("select"', _function(script, "accProductsPanel"))
        self.assertIn("kitPicker(", _function(script, "accChoose"))
        self.assertIn("Built decks without sleeves (", _function(script, "accUnsleevedPanel"))
        self.assertIn('"Remove…", kind: "danger btn-quiet"', _function(script, "accSheetFoot"))
        # The accessories page's field-by-field rebase is core.js's, which the Tokens page shares.
        self.assertIn("rebaseFields(mine, base, theirs, ACC_ROW_KEYS)", _function(script, "rebaseAccessory"))

    def test_the_tokens_page(self):
        # The Tokens page (tokens.js, tokens-edit.js, tokens-page.css): its route, the globals the deck page, library and packing plan
        # use, the endpoints it calls, the active-page guard on writes, and the phone-first layout.
        script = _scripts(("tokens.js", "tokens-edit.js"))
        for name in ("showTokens", "drawTokens", "updateTokens", "tokensActive", "tokenStateChip", "tokenNeedList",
                     "tokenThumb", "openTokenSheet"):
            with self.subTest(name=name):
                self.assertRegex(script, rf"(?m)^(?:async )?function {name}\(")
        self.assertIn('if (path === "tokens") return showTokens(token, params);', _function(_text("app.js"), "route"))
        for path in ('"/api/tokens"', '"/api/tokens/save"'):
            with self.subTest(path=path):
                self.assertIn(path, script)
        # Phase 4: saves are the database's; nothing about git, commits or retrying them is left.
        for gone in ('"/api/tokens/commit"', "commit_pending", "uncommitted", "Retry saving history",
                     "retryTokensCommit", "tokCommitWords", "Commit them"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, script)
        self.assertIn("view.token === routeToken", _function(script, "tokensActive"))
        self.assertIn("state.profile.id === view.profile", _function(script, "tokensActive"))
        # Every write checks the page is still the one that started it, and the answer is the latest asked.
        for name in ("refreshTokens", "removeToken"):
            with self.subTest(write=name):
                body = _function(script, name)
                self.assertIn("const seq = ++view.seq", body)
                self.assertIn("tokensActive(view) || seq !== view.seq", body)
        # Pictures only from Deck Lab's own card-image route; the details field's help as the plan words it.
        self.assertIn('url.startsWith("/img/")', _function(script, "tokenThumb"))
        self.assertIn('placeholder: "e.g. 1/1; green; flying"', script)
        self.assertIn('type: "number", inputmode: "numeric"', script)
        self.assertIn("rebaseFields(", _function(script, "showTokenConflict"))
        self.assertIn("function rebaseFields(mine, base, theirs, keys)", _text("core.js"))
        # The search and filter are remembered on the device.
        self.assertIn('local.get("tokens.search")', script)
        self.assertIn('local.set("tokens.filter", key)', script)
        css = _text("tokens-page.css")
        for width in ("600px", "1600px"):
            self.assertIn(f"@media (min-width: {width})", css)
        self.assertIn("@media (max-width: 359px)", css)
        self.assertIn(".tok-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }", css)   # 2 a row on a phone
        self.assertIn("@media (forced-colors: active)", css)
        self.assertIn("min-height: 44px", css)
        self.assertIn("object-fit: contain", css)
        # WP9: token tiles (cards-ui.js tokenTile) that open their sheet, with Remove at the sheet's bottom and the
        # notes in it; example art for a face name labelled as such, never taken for the printing; deck chips;
        # one "Details to check"; the missing tokens split into Missing and On the way.
        card = _function(script, "tokCard")
        self.assertIn("tokenTile(", card)
        self.assertIn('unrecorded: example ? "Example art" : null', card)
        self.assertIn('status("warn", "Details to check")', card)
        self.assertNotIn("Remove", card)
        self.assertIn("face.example", _function(script, "tokTileParts"))
        self.assertIn('"Printing not recorded"', _function(script, "tokTileParts"))
        self.assertIn('"Remove…", kind: "danger btn-quiet"', _function(script, "openTokenSheet"))
        missing = _function(script, "tokMissingPanel")
        for words in ("Tokens your decks make that you don't have", '"Missing"', '"On the way"'):
            self.assertIn(words, missing)
        # 16 px inputs wherever there's no fine pointer, so iOS doesn't zoom (DensityTokenTests checks the token).
        self.assertIn("font-size: var(--fs-input)", _text("base.css"))
        # The deck page's Tokens part is on its Cards tab, right after the decklist and before the prices.
        cards = _function(_text("deck.js"), "cardsParts")
        self.assertIn("return [screen.cardsBar, list, deckConsideringSection(data), deckEdhrecSection(data), deckSwapsSection(data), tokensSection(data),\n"
                      "    deckPrintingsSection(data), ownedSection(data)];", cards)
        self.assertIn('id: "sec-tokens"', _function(_text("deck.js"), "tokensSection"))
        # The shell's navigation (core.js's routes table) and the packing plan link to it.
        self.assertIn('{ path: "tokens", label: "Tokens"', _text("core.js"))
        self.assertIn('href: "#/tokens"', _function(_text("assembly.js"), "drawAssembly"))

    def test_the_activity_page(self):
        # The Activity page (activity.js, activity.css): its route and nav place for everyone, the endpoint,
        # "Load older" dropping an answer for a page left or an older click, every global prefixed, and the CSS.
        script = _text("activity.js")
        self.assertIn('if (path === "activity") return showActivity(params, token);', _function(_text("app.js"), "route"))
        self.assertRegex(_text("core.js"), r'\{ path: "activity", label: "Activity", [^\n]*nav: "more" \}')
        self.assertIn("activityPath(filter)", _function(script, "showActivity"))
        path = _function(script, "activityPath")
        self.assertIn("/api/activity?", path)
        self.assertIn('query.set("before", before)', path)
        older = _function(script, "activityOlder")
        self.assertIn("api(activityPath(view.filter, view.next))", older)
        self.assertIn("const seq = ++view.seq", older)
        self.assertIn("view.token !== routeToken || seq !== view.seq", older)
        self.assertNotIn("apiWrite", script)
        names = re.findall(r"(?m)^(?:async )?function (\w+)\(", script) + re.findall(r"(?m)^const (\w+)", script)
        self.assertEqual([n for n in names if n != "showActivity" and not n.lower().startswith("activity")], [])
        css = _text("activity.css")
        self.assertNotRegex(re.sub(r"/\*.*?\*/", "", css, flags=re.S), r"#[0-9a-fA-F]{3,8}\b|rgb|hsl")
        for width in ("600px", "1600px"):
            self.assertIn(f"@media (min-width: {width})", css)
        self.assertIn("@media (forced-colors: active)", css)
        self.assertIn("min-height: 44px", css)
        self.assertIn("overflow-wrap: anywhere", css)

    def test_the_collection_page_edits_a_space(self):
        # The Collection page (collection.js): spaces, the endpoints of the accounts milestone, writes tied to
        # the page that started them, conflicts put back on top field by field, and a phone-first layout.
        script = "\n".join(_text(name) for name in ("collection.js", "collection-import-groups.js", "collection-rows.js", "collection-cards.js", "collection-bulk.js",
                                                     "collection-guards.js", "collection-trade.js", "collection-scan.js",
                                                     "precon-coverage.js"))
        self.assertIn('if (path === "collection") return showCollection(params, token);', _function(_text("app.js"), "route"))
        for path in ('"/api/collection"', '"/api/collection/rows"', '"/api/collection/save"', '"/api/collection/bulk"',
                     '"/api/collection/import/preview"', '"/api/collection/import/apply"', "/api/printings?name=",
                     '"/api/collection/trade/preview"', '"/api/collection/trade"', '"/api/collection/scan"',
                     "/api/cards/search?q=", "/api/precons?", "/api/precons/preview?", '"/api/precons/add"',
                     "/api/precons/coverage?", "/api/precons/coverage/deck?", '"/api/precons/start"'):
            with self.subTest(path=path):
                self.assertIn(path, script)
        self.assertIn("openPreconSheet(cv)", _function(script, "colHead"))
        self.assertIn("openTradeSheet(cv)", _function(script, "colHead"))
        self.assertIn("openScanSheet(cv)", _function(script, "colHead"))
        self.assertIn("openCoverageSheet(cv)", _function(script, "colHead"))
        self.assertIn("seq !== ctx.seq", _function(script, "searchPrecons"))
        self.assertIn("seq !== ctx.seq", _function(script, "previewPrecon"))
        # A search typed just before a pick doesn't cover the preview; an add leaves the deck page's box about
        # the new deck (its warnings and stale tables), and never offers to add again once the cards may be in.
        self.assertIn("clearTimeout(ctx.timer)", _function(script, "previewPrecon"))
        self.assertIn("onClose: () => clearTimeout(ctx.timer)", _function(script, "openPreconSheet"))
        add = _function(script, "addPrecon")
        self.assertIn("state.saved = { hash", add)
        self.assertIn("error.status >= 500 || !error.data", add)
        self.assertIn("data.blocks", add)
        self.assertIn("a.precon", _function(_text("editor-deckpage.js"), "savedBox"))
        self.assertIn("cv.token === routeToken", _function(script, "colActive"))
        body = _function(script, "removeCollectionRow")
        self.assertIn("const seq = ++cv.seq", body)
        self.assertIn("colActive(cv) || seq !== cv.seq", body)
        for gone in ('"/api/collection/commit"', "retryCollectionCommit", "colCommitWords", "Retry saving history",
                     "commit"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, script)
        self.assertIn("rebaseFields(", _function(script, "showCollectionConflict"))
        self.assertIn("FileReader", _function(script, "readImportFile"))
        self.assertIn('accept: ".csv,.txt,text/csv,text/plain"', script)
        self.assertIn('type: "number", inputmode: "numeric"', script)
        # Find cards keeps lab tiles and a separate casual row viewer group, automatic filters and pagers
        # at the top and bottom; the Card list a sortable, paged table with thumbnails and a "not recorded" filter,
        # whose rows open their sheet (Remove at its bottom); Add card's printing strip.
        tile = _function(script, "colTile")
        self.assertIn("cardTile(", tile)
        self.assertIn('viewerGroup: "collection"', tile)
        self.assertIn("colFindCaption(cv, row)", tile)
        self.assertIn("Edit copies", _function(script, "colFindCaption"))
        self.assertIn('viewerItem(node, row.card, "collection-find", caption)', _function(script, "colFindRows"))
        self.assertIn('colFilter(cv, key, node.value)', _function(script, "colFilters"))
        self.assertIn("history.replaceState(", _function(script, "colLoadFind"))
        self.assertEqual(_function(script, "drawCollectionResults").count("colPager("), 2)
        self.assertEqual(_function(script, "drawColRowList").count("colPager("), 2)
        self.assertIn("th-sort", _function(script, "colRowTable"))
        self.assertIn('"collection-rows"', _function(script, "colRowLine"))
        self.assertIn("Condition or language not recorded", _function(script, "drawColRowList"))
        self.assertNotIn("Remove", _function(script, "colRowLine"))
        self.assertIn('"Remove…", kind: "danger btn-quiet"', _function(script, "openCollectionSheet"))
        self.assertIn("pickPrinting(", _function(script, "colPickBig"))
        self.assertIn("col-strip-tile", _function(script, "drawColStrip"))
        self.assertIn('viewerGroup: "precon"', _function(script, "drawPreconPreview"))
        css = _text("collection.css")
        # Its switches (segmented links) are 44 px on touch from components.css's floor, not a height of their own.
        self.assertNotRegex(css, r"\.col-views > a[^{]*\{[^}]*min-height")
        self.assertIn(".col-find-casual { display: none; }", css)
        self.assertIn(".col-find-lab { display: block; }", css)
        # 16 px inputs wherever there's no fine pointer, so iOS doesn't zoom (DensityTokenTests checks the token).
        self.assertIn("font-size: var(--fs-input)", _text("base.css"))
        self.assertIn("@media (forced-colors: active)", css)

    def test_the_wishlist_page(self):
        # WP9: card tiles that open their sheet (notes, printing, source; Remove at the bottom), an Undo toast
        # after Remove that puts the card back as it was, zero counts hidden, and a deck source as its title.
        script = _text("wishlist.js")
        self.assertIn("cardTile(", _function(script, "wishlistTile"))
        self.assertIn('viewerItem(open, card, "wishlist"', _function(script, "wishlistTile"))
        sheet = _function(script, "openWishlistSheet")
        self.assertIn('action: "set"', sheet)
        self.assertIn("pickPrinting(", sheet)
        self.assertIn('{ text: "Remove", kind: "danger btn-quiet"', sheet)
        remove = _function(script, "removeWishlist")
        self.assertIn("showToast(", remove)
        self.assertIn("undo:", remove)
        for key in ("body.notes = entry.notes", "body.source = entry.source", "body.set = entry.set"):
            self.assertIn(key, _function(script, "undoWishlistRemove"))
        self.assertIn("entry.source_deck", _function(script, "wishlistSource"))
        self.assertIn("have.owned ? ", _function(script, "wishlistAvailability"))
        # Undo sends its own add for the captured profile: the toast outlives the page.
        undo = _function(script, "undoWishlistRemove")
        self.assertIn("apiWrite(`/api/profiles/${encodeURIComponent(view.profile.id)}/wishlist`", undo)
        self.assertIn("wishlistActive(view)", undo)

    def test_no_nodelist_is_used_as_an_array(self):
        # A browser's querySelectorAll returns a NodeList, which has no find/filter/map; the Node tests' fake DOM
        # returns arrays, so only this check catches the mistake (the wishlist's Zoom once threw on it).
        from decklab.tests.test_web import WEB
        misuse = re.compile(r"querySelectorAll\([^)]*\)\s*\.(find|filter|map|some|every|reduce|findIndex|indexOf)\(")
        found = [f"{path.name}: {line.strip()}" for path in sorted(WEB.glob("*.js"))
                 for line in path.read_text(encoding="utf-8").splitlines() if misuse.search(line)]
        self.assertEqual(found, [])

    def test_pages_hide_what_the_visitor_may_not_change(self):
        # /api/me's "may" (state.may) decides what's drawn; the server checks every write anyway.
        core = _text("core.js")
        for name in ("mayDo", "canEditSpace", "canEditDeck", "createTargets", "spaceList", "deriveMay"):
            with self.subTest(name=name):
                self.assertRegex(core, rf"(?m)^function {name}\(")
        self.assertIn("loadMe()", _function(_text("app.js"), "start"))
        self.assertIn("canEditDeck(s)", _function(_text("editor-deckpage.js"), "deckActions"))
        self.assertIn('mayDo("accessories")', _function(_text("accessories.js"), "drawAccessories"))
        self.assertIn('mayDo("receipts")', _function(_text("receipts.js"), "drawReceipt"))
        self.assertIn("canEditSpace(space)", _function(_text("tokens.js"), "drawTokens"))
        self.assertIn("createTargets()", _function(_text("library.js"), "drawLibrary"))

    def test_the_lists_have_one_name_on_every_page(self):
        # Owner decision 2 (UI-REVIEW.md): the page calls a deck's two lists "Planned list" and "Play-now list"
        # (core.js listName). The old names stay only in comments and in the deck text's own headings.
        from decklab.tests.test_web import WEB
        old = re.compile(r"(?i:\b(owned-only|target list|substitute (list|version)|target availability)\b)|\b(Target|Owned-only): ")
        found = []
        for path in sorted(WEB.glob("*.js")):
            code = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
            for n, line in enumerate(code.splitlines(), 1):
                if line.strip().startswith("//"):
                    continue
                line = re.sub(r"\s//\s.*$", "", line)          # a comment after the code
                if old.search(line):
                    found.append(f"{path.name}: {line.strip()}")
        self.assertEqual(found, [])
        self.assertIn('const LIST_NAME = { target: "Planned list", owned: "Play-now list" };', _text("core.js"))

    def test_the_receipts_page_says_nothing_about_git(self):
        # Phase 4: a receipt is one change in the database; no Git commit can fail after it.
        script = _text("receipts.js") + _text("receipt-workflow.js")
        for gone in ("Git commit", "answer.commit", "commit_pending"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, script)


if __name__ == "__main__":
    unittest.main()
