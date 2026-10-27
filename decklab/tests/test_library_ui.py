"""The library as a deck shelf (decklab/UI-REVIEW.md WP8) and the deck picture picker (cover.js).

Loads every page script in its real order into the event/DOM double (fixtures/workspace_ui_runner.js), with
the API stubbed: no browser, server, inventory write or Forge run.

Run from the repo root: python -m unittest decklab.tests.test_library_ui
"""
import json
import subprocess
import unittest

from decklab.tests.test_accounts_ui import SETUP
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SHELF = SETUP + r"""
  const store = new Map();
  window.localStorage = { getItem: (k) => store.has(k) ? store.get(k) : null, setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k) };
  const art = (s, n) => `/img/${s}/${n}/art_crop`;
  const base = { kind: "casual", space: "home", player: "user", status: "building", versions: ["target"],
    card_count: 60, sideboard_count: 0, kit: null, tokens: null, colors: ["R", "G"], revision: 3, edited: null };
  const deck = (id, title, extra = {}) => ({ ...base, id, title, cover: { name: title + " Card", set: "fdn",
    number: "1", auto: true, art: art("fdn", "1"), img: "/img/fdn/1/normal" }, ...extra });
  const counts = (target, waiting = 0, extra = {}) => ({ missing: { target }, on_the_way: { target: waiting },
    availability_confirmed: { target: true }, ...extra });
  const DECKS = [
    deck("casual/gruul", "Gruul", { status: "built", format: "Casual 60-card, 1v1", ...counts(0),
      edited: "2026-10-01T10:00:00+10:00" }),
    deck("casual/otters", "Otters", { ...counts(8, 1, { versions: ["target", "owned"],
      missing: { target: 8, owned: 0 }, on_the_way: { target: 1, owned: 0 },
      availability_confirmed: { target: true, owned: true } }), versions: ["target", "owned"],
      edited: "2026-10-12T10:00:00+10:00" }),
    deck("casual/angels", "Angels", { ...counts(0), player: "either" }),
    deck("casual/vampires", "Vampires", { ...counts(0, 2), player: "either", edited: "2026-10-05T10:00:00+10:00" }),
    deck("commander/giada", "Giada", { kind: "commander", player: "wife", target_bracket: 2, ...counts(3), colors: ["W"] }),
    deck("product/fdn-beginner-box/cats", "Cats (Foundations Beginner Box)", { read_only: true, status: null,
      player: null, ...counts(0) }),
    deck("product/fdn-beginner-box/elves", "Elves (Foundations Beginner Box)", { read_only: true, status: null,
      player: null, ...counts(0) }),
  ];
  const DATA = { warnings: [], halves: [], decks: DECKS };
  const tiles = () => main.querySelectorAll(".deck-card");
  const titles = (root = main) => root.querySelectorAll(".deck-title").map((t) => t.textContent);
  const isOpen = (n) => n.open === true || (n.open !== false && n.getAttribute("open") !== null);
  const tile = (title) => tiles().find((t) => t.querySelector(".deck-title").textContent === title);
"""


class _Shelf(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SHELF + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")


@unittest.skipUnless(NODE, "Node.js isn't installed")
class LibraryShelfTests(_Shelf):
    """The tiles, readiness words, links, sorts, folded products and the phone's filter sheet."""

    def test_a_tile_is_one_link_with_art_pips_status_and_one_readiness_chip(self):
        self.run_js("""
          as("matt", MAY.admin);
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1")));
          const gruul = tile("Gruul");
          assert.equal(gruul.tag, "a");
          assert.equal(gruul.querySelectorAll("a").length, 0);             // nothing nested: the tile is the link
          assert.equal(gruul.querySelector(".deck-cover-img").getAttribute("src"), "/img/fdn/1/art_crop");
          // The deck's colour pieces (ui.js deckColourPieces): spoken pips over the art's corner, a silent stripe on
          // top, and the rest of the tile on the deck's tint.
          const pips = gruul.querySelector(".deck-cover").querySelector(".deck-pips");
          assert.equal(pips.getAttribute("role"), "img");
          assert.equal(pips.getAttribute("aria-label"), "Colours: red, green");
          same(pips.querySelectorAll(".id-pip").map((p) => p.textContent), ["R", "G"]);
          assert(pips.matches(".id-pips-md"));                              // 20 px, a casual tile's
          assert(pips.getAttribute("class").includes("is-over-art"));
          assert.equal(gruul.querySelector(".deck-body").getAttribute("class"), "deck-body deck-tint");
          assert.equal(gruul.children[0].getAttribute("class"), "deck-stripe");
          assert.equal(gruul.children[0].getAttribute("aria-hidden"), "true");
          // While the art loads, the cover is on the deck's art placeholder colour.
          assert.equal(gruul.querySelector(".deck-cover").getAttribute("class"), "deck-cover");
          assert(gruul.querySelector(".deck-cover").getAttribute("style").includes("--deck-art: var(--art-r)"));
          // Art that fails to load gives way to the deck's tint.
          gruul.querySelector(".deck-cover-img").fire("error");
          assert.equal(gruul.querySelector(".deck-cover-img"), null);
          assert(gruul.querySelector(".deck-cover").classList.contains("deck-tint"));   // the double's classList
          // A Built tile has no status pill (Matt, 2026-10-25); Building and Idea do.
          assert.equal(gruul.querySelector(".deck-status"), null);
          assert.equal(tile("Otters").querySelector(".deck-status").textContent, "Building");
          // The format line is gone (the group says it); one meta line instead.
          assert(!gruul.textContent.includes("Casual 60-card"));
          assert.equal(gruul.querySelector(".deck-meta").textContent, "Matt · 60 cards");
          // Each fact whole, its dot in front (a wrapped line's first dot is clipped by CSS); "Either" for both of you.
          same(gruul.querySelector(".deck-meta").querySelectorAll(".fact").map((f) => f.textContent), ["Matt", " · 60 cards"]);
          // A built deck with every card: the owned bar and its words, no chip at all (chips are for exceptions).
          assert.equal(gruul.querySelector(".deck-missing"), null);
          assert.equal(gruul.querySelector(".deck-owned-words").textContent, "60 owned");
          assert.equal(gruul.querySelector(".owned-bar").getAttribute("aria-hidden"), "true");
          assert.equal(gruul.querySelector(".owned-bar-fill").getAttribute("style"), "width: 100%");
          assert.equal(gruul.getAttribute("href"), deckHref("casual/gruul"));
          // Missing cards: the bar's words, a chip only for what they don't say (the Play-now list is ready), and the
          // link goes to the missing cards.
          const otters = tile("Otters");
          same(otters.querySelector(".deck-owned-words").querySelectorAll(".fact").map((f) => f.textContent),
               ["51 owned", " · 1 on the way", " · 8 to get"]);
          assert.equal(otters.querySelector(".owned-bar-fill").getAttribute("style"), "width: 85%");
          assert.equal(otters.querySelector(".owned-bar-way").getAttribute("style"), "width: 1.7%");
          same(otters.querySelectorAll(".status").map((s) => s.textContent), ["Play-now list ready"]);
          assert.equal(otters.getAttribute("href"), deckHref("casual/otters") + "&tab=cards&filter=missing");
          // Every card here is the usual case: no chip, mine or anyone's (Ready first puts them first).
          assert.equal(tile("Angels").querySelector(".deck-missing"), null);
          assert.equal(tile("Angels").querySelector(".deck-meta").textContent, "Either · 60 cards");
          assert.equal(tile("Giada").querySelector(".deck-owned-words").textContent, "57 owned · 3 to get");
          assert.equal(tile("Giada").querySelector(".status"), null);
          assert(!main.textContent.includes("Ready to play"));
          assert.equal(tile("Vampires").querySelector(".deck-owned-words").textContent, "58 owned · 2 on the way");
          // A count that can't be trusted keeps its chip and gets no bar.
          clear(main);
          drawLibrary({ ...DATA, decks: [deck("casual/q", "Q", { ...counts(2, 0, { availability_confirmed: { target: false } }) })] },
            libraryFilters(new URLSearchParams("all=1")));
          assert.equal(tile("Q").querySelector(".deck-owned"), null);
          assert.equal(tile("Q").querySelector(".status").textContent, "Availability needs checking");
          clear(main);
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1")));
          // The availability filter says what the chips say.
          same(Object.values(LIB_READINESS), ["All cards here", "Cards on the way", "Cards to get", "Availability needs checking"]);
          assert.equal(tile("Giada").querySelector(".deck-meta").textContent, "User1 · 60 cards · Bracket 2");
          // A visitor who may not see the space's collection gets no counts, so no chip and a plain link.
          clear(main);
          const hidden = DECKS.map(({ missing, on_the_way, availability_confirmed, ...rest }) => rest);
          drawLibrary({ ...DATA, decks: hidden }, libraryFilters(new URLSearchParams("all=1")));
          assert.equal(main.querySelectorAll(".deck-missing").length, 0);
          assert.equal(main.querySelectorAll(".deck-owned").length, 0);
          assert.equal(tile("Otters").getAttribute("href"), deckHref("casual/otters"));
          // No art: the deck's tint instead (tokens only).
          clear(main);
          drawLibrary({ ...DATA, decks: [deck("casual/x", "X", { cover: null, colors: ["B", "U"], ...counts(0) }),
            deck("casual/y", "Y", { cover: null, colors: [], ...counts(0) }),
            deck("casual/z", "Z", { cover: null, colors: [], card_count: 0, ...counts(0) }),
            deck("casual/w", "W", { cover: null, colors: null, ...counts(0) })] },
            libraryFilters(new URLSearchParams("all=1")));
          assert.equal(tile("X").querySelector(".deck-cover-img"), null);
          assert.equal(tile("X").querySelector(".deck-cover").getAttribute("class"), "deck-cover deck-tint");
          assert.equal(tile("X").querySelector(".deck-cover").getAttribute("style"),
            "--deck-stripe: linear-gradient(90deg, var(--stripe-u) 0% 50%, var(--stripe-b) 50% 100%); " +
            "--deck-tint: linear-gradient(135deg, var(--tint-u), var(--tint-b)); --deck-art: var(--art-u)");
          // A colourless deck says so with a C; a deck with no cards shows no colours at all.
          assert.equal(tile("Y").querySelector(".deck-pips").getAttribute("aria-label"), "Colourless");
          same(tile("Y").querySelectorAll(".id-pip").map((p) => p.textContent), ["C"]);
          assert.equal(tile("Z").querySelector(".id-pips"), null);
          assert.equal(tile("Z").querySelector(".deck-stripe"), null);
          assert.equal(tile("Z").querySelector(".deck-cover").getAttribute("style"), null);
          // Cards but none the server could read ("colors" null): no colours either, never a colourless C.
          assert.equal(tile("W").querySelector(".id-pips"), null);
          assert.equal(tile("W").querySelector(".deck-stripe"), null);
          assert.equal(tile("W").querySelector(".deck-cover").getAttribute("class"), "deck-cover");
          assert.equal(tile("W").querySelector(".deck-cover").getAttribute("style"), null);
        """)

    def test_the_lab_has_rows_beside_the_selected_decks_detail(self):
        # E11-S30 slice 8 (design/visual-design.md 4.2, 4.6): from 1000 px, rows under Built, Building and Ideas
        # in a list pane, the selected deck's overview beside them; a click selects, Enter opens, J and K move.
        self.run_js("""
          as("matt", MAY.admin);
          const addresses = [];
          history.replaceState = (s, t, url) => addresses.push(url);
          const wide = window.matchMedia(LIB_LAB_QUERY);
          wide.matches = true;
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1")));
          assert.equal(main.querySelectorAll(".deck-card").length, 2);          // only the products are tiles
          const rows = () => main.querySelectorAll(".deck-row");
          same(rows().map((r) => r.getAttribute("data-id")),
               ["commander/giada", "casual/gruul", "casual/angels", "casual/vampires", "casual/otters"]);
          same(main.querySelectorAll(".lib-status-head").map((h) => h.textContent), ["Building1", "Built1", "Building3"]);
          // The rows have no pill (the heading says it), 16 px pips and the owned bar's mono words.
          const gruul = rows()[1];
          assert.equal(gruul.querySelector(".deck-status"), null);
          assert(gruul.querySelector(".deck-pips").getAttribute("class").includes("id-pips-sm"));
          // The row says what each count is, as a tile does (not "51 +1").
          assert.equal(rows()[4].querySelector(".deck-owned-words").textContent, "51 owned · 1 on the way · 8 to get");
          // The first row is selected, and its detail is beside the list with every status pill and the ways in.
          assert.equal(rows()[0].getAttribute("aria-current"), "true");
          let detail = main.querySelector(".lib-detail");
          assert.equal(detail.getAttribute("data-id"), "commander/giada");
          assert.equal(detail.querySelector(".deck-status").textContent, "Building");
          same(detail.querySelectorAll(".btn").map((b) => b.textContent), ["Edit deck", "Open deck"]);
          assert.equal(detail.querySelector(".btn-primary").getAttribute("href"), editHref("commander/giada"));
          // A click selects (the page stays) and keeps the choice in the address.
          const click = rows()[4].fire("click", { detail: 1, button: 0 });
          assert(click.defaultPrevented);
          assert.equal(main.querySelector(".lib-detail").getAttribute("data-id"), "casual/otters");
          assert(addresses.at(-1).endsWith("deck=casual%2Fotters"));
          assert.equal(rows()[4].getAttribute("aria-current"), "true");
          assert.equal(rows()[0].getAttribute("aria-current"), null);
          // Enter (a click with no pointer) and a modified click follow the link.
          assert(!rows()[2].fire("click", { detail: 0 }).defaultPrevented);
          assert(!rows()[2].fire("click", { detail: 1, button: 0, metaKey: true }).defaultPrevented);
          // J and K move the selection and the focus; not while typing.
          document.fire("keydown", { key: "k", target: main });
          assert.equal(main.querySelector(".lib-detail").getAttribute("data-id"), "casual/vampires");
          assert.equal(document.activeElement.getAttribute("data-id"), "casual/vampires");
          for (let i = 0; i < 3; i += 1) document.fire("keydown", { key: "k", target: main });
          assert.equal(main.querySelector(".lib-detail").getAttribute("data-id"), "commander/giada");
          document.fire("keydown", { key: "j", target: main });
          detail = main.querySelector(".lib-detail");
          assert.equal(detail.getAttribute("data-id"), "casual/gruul");
          assert.equal(detail.querySelector(".deck-status").textContent, "Built");
          // Its art keeps its own size over a blurred copy of itself (a row's and a tile's have no copy).
          assert(detail.querySelector(".deck-cover").getAttribute("class").includes("deck-cover-wide"));
          assert.equal(detail.querySelector(".deck-cover-backdrop").getAttribute("src"), "/img/fdn/1/art_crop");
          assert.equal(detail.querySelector(".deck-cover-backdrop").getAttribute("aria-hidden"), "true");
          assert.equal(main.querySelectorAll(".deck-row .deck-cover-backdrop, .deck-card .deck-cover-backdrop").length, 0);
          same(main.querySelectorAll(".deck-group").map((g) => g.getAttribute("aria-label")), ["Commander decks", "60-card decks"]);
          // A deck the visitor can't change has Open deck as its one primary.
          rows()[4].fire("click", { detail: 1, button: 0 });
          as("user1", MAY.user1);
          clear(main);
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1&deck=casual/gruul")));
          detail = main.querySelector(".lib-detail");
          assert.equal(detail.getAttribute("data-id"), "casual/gruul");
          same(detail.querySelectorAll(".btn").map((b) => b.textContent), ["Open deck"]);
          assert(detail.querySelector(".btn").getAttribute("class").includes("btn-primary"));
          // Narrower than 1000 px, the tiles come back.
          wide.matches = false;
          wide.fire("change");
          assert.equal(main.querySelectorAll(".deck-row").length, 0);
          assert.equal(main.querySelector(".lib-detail"), null);
          assert(main.querySelectorAll(".deck-card").length > 2);
        """)

    def test_tested_decks_have_a_forge_line_tiles_rows_and_detail(self):
        # E11-S30 slice 8 (4.1, 4.2): the field average from /api/library/forge, drawn in once it comes. A tile
        # has a Forge line only when tested; a lab row has the column, "—" for an untested casual deck and blank
        # for a Commander deck; the detail pane has the summary with the way to the field view.
        self.run_js("""
          as("matt", MAY.admin);
          const asked = [];
          const tested = new Date(Date.now() - 2 * 864e5).toISOString();
          api = async (path) => {
            asked.push(path);
            if (path !== "/api/library/forge") throw new Error("not in this test");
            return { error: null, decks: {
              "casual/otters": { version: "target", rate: { value: 0.61, low: 0.59, high: 0.63 }, partial: true,
                counted: 3, of: 4, games: 1200, tested },
              "casual/angels": { version: "target", rate: null, partial: false, counted: 0, of: 4, games: 0, tested: null } } };
          };
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1")));
          assert.equal(main.querySelectorAll(".deck-forge").length, 0);        // nothing until the numbers come
          await flush();
          assert.equal(asked.filter((p) => p === "/api/library/forge").length, 1);
          const lines = main.querySelectorAll(".deck-forge");
          assert.equal(lines.length, 1);                                        // no "not tested" line
          const otters = tile("Otters");
          const figure = otters.querySelector(".wr");
          assert(figure.getAttribute("class").includes("wr-tile"));
          assert.equal(otters.querySelector(".wr-value").textContent, "61%");
          assert.equal(otters.querySelector(".wr-caption").textContent, "Forge field");
          assert(figure.getAttribute("aria-label").startsWith("Forge field win rate 61 percent, range 59 to 63"));
          assert(otters.querySelector(".fresh").getAttribute("class").includes("on-tint"));
          // The lab: the column on every row, the summary in the detail pane.
          const wide = window.matchMedia(LIB_LAB_QUERY);
          wide.matches = true;
          wide.fire("change");
          const cell = (id) => main.querySelectorAll(".deck-row").find((r) => r.getAttribute("data-id") === id)
            .querySelector(".deck-row-forge");
          assert.equal(cell("casual/otters").querySelector(".wr-value").textContent, "61%");
          assert.equal(cell("casual/otters").querySelector(".wr-range").textContent, "59–63");
          assert.equal(cell("casual/otters").querySelector(".range-bar").getAttribute("aria-hidden"), "true");
          assert(cell("casual/otters").querySelector(".fresh").getAttribute("class").includes("fresh-row"));
          assert.equal(cell("casual/angels").textContent, "—");               // tested but no rate yet
          assert.equal(cell("casual/gruul").textContent, "—");                // not in the answer
          assert.equal(cell("commander/giada").textContent, "");              // Commander: blank
          main.querySelectorAll(".deck-row").find((r) => r.getAttribute("data-id") === "casual/otters")
            .fire("click", { detail: 1, button: 0 });
          const summary = main.querySelector(".lib-detail-forge");
          assert.equal(summary.querySelector(".wr").getAttribute("class").includes("wr-hero"), true);
          assert.equal(summary.querySelector(".lib-detail-forge-note").textContent,
                       "Against 3 of the 4 decks in the field so far.");
          assert.equal(summary.querySelector(".btn").getAttribute("href"), deckHref("casual/otters", "target") + "&part=field");
          // Gruul (untested) has no summary; another profile's numbers are never shown.
          main.querySelectorAll(".deck-row")[0].fire("click", { detail: 1, button: 0 });
          assert.equal(main.querySelector(".lib-detail-forge"), null);
          as("user1", MAY.user1);
          state.libraryForge.profile = "matt";
          assert.equal(libForge(DECKS[1]), undefined);
          // The numbers can't be worked out: the lines are left out, not shown as untested.
          state.libraryForge = null;
          api = async () => ({ error: "The Forge numbers can't be worked out on the PC now.", decks: {} });
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1")));
          await flush();
          assert.equal(main.querySelectorAll(".deck-row-untested").length, 0);
        """)

    def test_the_token_line_names_each_token_once(self):
        self.run_js("""
          as("matt", MAY.admin);
          const node = deckTokens({ none: ["Dragon", "Dragon", "Dragon", "Treasure", "The Monarch"], differs: [],
            incoming: ["Fish"], reminders: ["The Monarch"] });
          same(node.querySelectorAll(".status").map((s) => s.textContent),
               ["No Dragon or Treasure tokens, The Monarch", "Fish token on the way"]);
          // Past three names the rest are counted in words, never "+1" (which reads like a counter).
          same(deckTokens({ none: ["Dragon", "Treasure", "Zombie", "Clue"], differs: [], incoming: [] })
            .querySelectorAll(".status").map((s) => s.textContent), ["No Dragon, Treasure or Zombie tokens and 1 more"]);
          same(deckTokens({ none: ["Raccoon", "Raccoon"], differs: ["Insect", "Insect"], incoming: [] })
            .querySelectorAll(".status").map((s) => s.textContent), ["No Raccoon token", "Insect token differs"]);
          same(deckTokens({ none: [], differs: ["Ape", "Insect"], incoming: [] })
            .querySelectorAll(".status").map((s) => s.textContent), ["Ape and Insect tokens differ"]);
          assert.equal(deckTokens({ none: [], differs: [], incoming: [] }), null);
        """)

    def test_sorts_ready_first_recently_changed_and_name(self):
        self.run_js("""
          as("matt", MAY.admin);
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1&format=casual")));
          // Ready first: built, every card here, waiting for a delivery, then missing cards (fewest first).
          same(titles(), ["Gruul", "Angels", "Vampires", "Otters"]);
          main.querySelector("#filter-sort").fire("change", { target: { value: "recent" } });
          same(titles(), ["Otters", "Vampires", "Gruul", "Angels"]);
          // Times are compared as times, not as text: a later edit with fractions of a second, in another zone.
          const timed = [deck("casual/a", "A", { edited: "2026-10-12T09:06:52+00:00" }),
            deck("casual/b", "B", { edited: "2026-10-12T19:06:52.464327+10:00" }),
            deck("casual/c", "C", { edited: "2026-10-12T19:06:53+10:00" }), deck("casual/d", "D", { edited: null })];
          same(sortDecks(timed, "recent").map((d) => d.title), ["C", "B", "A", "D"]);
          main.querySelector("#filter-sort").fire("change", { target: { value: "name" } });
          same(titles(), ["Angels", "Gruul", "Otters", "Vampires"]);
          same(libraryFilters(new URLSearchParams("sort=recent")).sort, "recent");
          same(libraryFilters(new URLSearchParams("sort=bogus")).sort, "ready");
          assert.equal(filtersHash({ all: true, format: "", status: "", readiness: "", sort: "name" }), "#/library?all=1&sort=name");
          assert.equal(filtersHash({ all: false, format: "", status: "", readiness: "", sort: "ready" }), "#/library");
        """)

    def test_products_fold_and_remember_and_their_caption_fits_the_viewer(self):
        self.run_js("""
          as("matt", MAY.admin);
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1")));
          let part = main.querySelector(".lib-products");
          assert.equal(part.tag, "details");
          assert.equal(isOpen(part), false);                        // folded at first
          assert(part.textContent.includes("Products(2)") || part.textContent.includes("Products"));
          assert(part.textContent.includes("The decks in your sealed products"));
          assert(!part.textContent.includes("both of you"));
          part.open = true; part.fire("toggle");
          clear(main); drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1")));
          assert.equal(isOpen(main.querySelector(".lib-products")), true);   // remembered
          // Asking for products opens them, whatever was remembered.
          main.querySelector(".lib-products").open = false; main.querySelector(".lib-products").fire("toggle");
          clear(main); drawLibrary(DATA, libraryFilters(new URLSearchParams("format=product")));
          assert.equal(isOpen(main.querySelector(".lib-products")), true);
          // A person: not among their own decks; among all decks, named as the home's.
          as("user2", MAY.user2);
          drawLibrary(DATA, libraryFilters(new URLSearchParams()));
          assert.equal(main.querySelector(".lib-products"), null);
          clear(main); drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1")));
          assert(main.querySelector(".lib-products").textContent.includes("the home collection's sealed products"));
          // No zero counts: User2 has no decks of his own, so no "Showing 0 decks".
          clear(main); drawLibrary(DATA, libraryFilters(new URLSearchParams()));
          assert(!main.textContent.includes("Showing 0"));
          // Only Mine is on (no filter chosen): it says so, and offers every deck.
          assert(main.querySelector(".empty").textContent.includes("You don't play any decks yet."));
          assert(main.querySelector(".empty").textContent.includes("Show every deck"));
        """)

    def test_the_phone_filter_sheet_counts_and_applies_filters(self):
        self.run_js("""
          as("matt", MAY.admin);
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1&status=building")));
          const filter = main.querySelector(".lib-filter-button");
          assert.equal(filter.textContent, "Filter (1)");
          filter.click();
          const sheet = openDialog();
          assert(sheet.textContent.includes("Format") && sheet.textContent.includes("Sort"));
          // The sheet's sort field has its label shown, so its options don't repeat "Sort:" (the row's do).
          same(sheet.querySelector("#sheet-filter-sort").querySelectorAll("option").map((o) => o.textContent),
               ["Ready first", "Recently changed", "Name"]);
          assert.equal(main.querySelector("#filter-sort").querySelector("option").textContent, "Sort: Ready first");
          const format = sheet.querySelector("#sheet-filter-format");
          format.focus();
          format.fire("change", { target: { value: "commander" } });
          // The field just changed is still there, with the focus: only the buttons are drawn again.
          assert.equal(sheet.querySelector("#sheet-filter-format"), format);
          assert.equal(document.activeElement, format);
          assert.equal(filter.textContent, "Filter (2)");
          same(titles(), ["Giada"]);
          assert.equal(main.querySelector("#filter-format").value, "commander");      // the row follows the sheet
          assert(button(sheet, "Show 1 deck"));
          let draws = 0;
          const real = drawLibraryResults;
          drawLibraryResults = (...args) => { draws += 1; return real(...args); };
          button(sheet, "Clear filters").click();
          drawLibraryResults = real;
          assert.equal(draws, 1);                                  // three filters cleared, one redraw
          assert.equal(filter.textContent, "Filter");
          assert.equal(sheet.querySelector("#sheet-filter-status").value, "");
          assert.equal(titles().length, 7);
        """)

    def test_a_persons_own_decks_have_no_extra_heading(self):
        self.run_js("""
          as("user2", MAY.user2);
          const theirs = deck("user2/commander/lathliss", "Lathliss", { kind: "commander", space: "user2", player: null });
          drawLibrary({ ...DATA, decks: [...DATA.decks, theirs] }, libraryFilters(new URLSearchParams()));
          assert.equal(main.querySelector(".space-person"), null);
          assert.equal(main.querySelector(".deck-group").querySelector("h2").textContent, "Commander decks(1)");
          same(titles(), ["Lathliss"]);
          assert.equal(tile("Lathliss").querySelector(".deck-meta").textContent, "60 cards");
          // Among all decks, theirs is a part of its own after the home decks.
          clear(main);
          drawLibrary({ ...DATA, decks: [...DATA.decks, theirs] }, libraryFilters(new URLSearchParams("all=1")));
          assert(main.querySelector(".space-person"));
        """)

    def test_a_member_with_only_their_own_decks_is_told_nothing_else_is_public(self):
        # E10-S30: /api/decks holds only the viewer's own space's decks.
        self.run_js("""
          as("user2", MAY.user2);
          const theirs = deck("user2/commander/lathliss", "Lathliss", { kind: "commander", space: "user2", player: null });
          drawLibrary({ ...DATA, decks: [theirs] }, libraryFilters(new URLSearchParams()));
          assert.equal(main.querySelector(".lib-nothing-public").textContent, "Nothing else is public yet.");
          clear(main);
          drawLibrary({ ...DATA, decks: [] }, libraryFilters(new URLSearchParams("all=1")));
          assert(main.querySelector(".empty").textContent.includes("There are no decks yet."));
          assert.equal(main.querySelector(".lib-nothing-public").textContent, "Nothing else is public yet.");
          // Home's profiles get no such line, and neither does a member shown another space's decks.
          clear(main);
          as("user1", MAY.user1);
          drawLibrary(DATA, libraryFilters(new URLSearchParams()));
          assert.equal(main.querySelector(".lib-nothing-public"), null);
          clear(main);
          as("user2", MAY.user2);
          drawLibrary({ ...DATA, decks: [...DATA.decks, theirs] }, libraryFilters(new URLSearchParams()));
          assert.equal(main.querySelector(".lib-nothing-public"), null);
        """)

    def test_more_sits_in_the_filter_row_without_new_deck(self):
        self.run_js("""
          as("matt", MAY.admin);
          drawLibrary(DATA, libraryFilters(new URLSearchParams()));
          assert.equal(main.querySelector(".page-head").querySelector(".btn-primary").textContent, "New deck");
          assert.equal(main.querySelector(".lib-more"), null);
          // A phone still makes decks (in the editor's Quick edit), so New deck stays.
          window.matchMedia("(min-width: 600px)").matches = false;
          clear(main);
          drawLibrary(DATA, libraryFilters(new URLSearchParams()));
          assert.equal(main.querySelector(".page-head").querySelector(".btn-primary").textContent, "New deck");
          // Someone who may make no deck: no New deck, so More moves into the filter row.
          state.may = { ...state.may, create: [] };
          clear(main);
          drawLibrary(DATA, libraryFilters(new URLSearchParams()));
          assert.equal(main.querySelector(".page-head").querySelector(".btn-primary"), null);
          assert.equal(main.querySelector(".page-head").querySelector(".menu-button"), null);
          assert(main.querySelector(".lib-filters").querySelector(".lib-more").querySelector(".menu-button"));
        """)

    def test_choosing_deck_pictures(self):
        self.run_js("""
          as("user1", MAY.user1);
          let opened = null;
          openCoverPicker = (id, done) => { opened = { id, done }; };
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1")));
          // The More menu offers it when there's a deck the visitor may change.
          const item = main.querySelectorAll("button").find((b) => b.textContent === "Choose deck pictures");
          item.click();
          assert.equal(main.querySelector(".lib-picking").hidden, false);
          // User1 may change the decks Played by her: none of Matt's, none of the products.
          const pick = main.querySelectorAll(".lib-pick");
          same(pick.map((b) => b.querySelector(".deck-title").textContent).sort(),
               DECKS.filter((d) => libCoverEditable(d)).map((d) => d.title).sort());
          assert(main.querySelectorAll(".is-unpickable").length > 0);      // products and others' decks
          // Each deck that can change says so on its banner; the others don't.
          assert(pick.every((b) => b.querySelector(".deck-pick-badge").textContent === "Change picture"));
          assert(main.querySelectorAll(".is-unpickable").every((n) => !n.querySelector(".deck-pick-badge")));
          pick[0].click();
          assert(opened && !opened.id.startsWith("product/"));
          opened.done({ name: "New Card", art: "/img/abc/9/art_crop", auto: false }, 4);
          assert(main.querySelectorAll("img").some((i) => i.getAttribute("src") === "/img/abc/9/art_crop"));
          // The shelf was drawn again; the focus is on the same deck's new tile, not lost.
          assert.equal(document.activeElement.getAttribute("data-id"), opened.id);
          assert(main.contains(document.activeElement));
          // An Undo pressed after leaving the library changes nothing of the page now shown, nor its address.
          let replaced = 0;
          history.replaceState = () => { replaced += 1; };
          const done = opened.done;
          clear(main);
          main.append(el("p", { id: "other-page", text: "A deck page" }));
          done({ name: "Old Card", art: "/img/abc/1/art_crop", auto: false }, 5);
          assert.equal(replaced, 0);
          assert.equal(main.querySelector("#other-page").textContent, "A deck page");
          as("user1", MAY.user1);
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1")));
          main.querySelectorAll("button").find((b) => b.textContent === "Choose deck pictures").click();
          button(main, "Done").click();
          assert.equal(main.querySelectorAll(".lib-pick").length, 0);
          assert.equal(main.querySelector(".lib-picking").hidden, true);
          // User2 may change none of these: no menu item at all.
          as("user2", MAY.user2);
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1")));
          assert(!main.querySelectorAll("button").some((b) => b.textContent === "Choose deck pictures"));
        """)


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CoverPickerTests(_Shelf):
    """cover.js: the automatic rule, the art addresses, the picker's tiles (a viewer group) and its save."""

    def test_art_addresses_and_names(self):
        self.run_js("""
          assert.equal(coverArt("/img/fdn/227/normal"), "/img/fdn/227/art_crop");
          assert.equal(coverArt("https://example.com/x/normal"), null);
          assert.equal(coverArtOf("pdmu", "1★"), "/img/pdmu/1%E2%98%85/art_crop");
          assert(coverSame({ name: "Llanowar Elves" }, { name: "llanowar elves", set: null }));
          assert(!coverSame({ name: "Llanowar Elves" }, { name: "Llanowar Elves", set: "fdn", number: "227" }));
          assert(coverSame(null, null) && !coverSame(null, { name: "Opt" }));
        """)

    PICKER = """
          as("matt", MAY.admin);
          const sent = [], asked = [];
          const card = (name, type, s = "fdn", n = "1") => ({ name, type_line: type, img: `/img/${s}/${n}/normal`,
            img_small: `/img/${s}/${n}/small` });
          const view = (cover) => ({ summary: { id: "casual/gruul", title: "Gruul", revision: 3, cover },
            auto: { name: "Llanowar Elves", set: "fdn", number: "227", auto: true, art: "/img/fdn/227/art_crop" },
            cards: [{ name: "Llanowar Elves", set: "fdn", number: "227", card: card("Llanowar Elves", "Creature — Elf Druid", "fdn", "227") },
              { name: "Shock", set: "m19", number: "156", card: card("Shock", "Instant", "m19", "156") },
              { name: "Forest", set: "fdn", number: "276", card: card("Forest", "Basic Land — Forest", "fdn", "276") }] });
          let answer = view({ name: "Llanowar Elves", set: "fdn", number: "227", auto: true, art: "/img/fdn/227/art_crop" });
          api = async (path, options) => {
            asked.push(path);
            if (path.startsWith("/api/deck/cards?")) return answer;
            if (path === "/api/deck/cover") {
              const body = JSON.parse(options.body); sent.push(body);
              return { saved: true, id: body.id, title: "Gruul", revision: body.expect + 1,
                cover: body.cover ? { ...body.cover, auto: false } : { name: "Llanowar Elves", auto: true } };
            }
            throw new Error("unexpected " + path);
          };
          const viewed = [];
          openCardViewer = (items, start, opts) => { viewed.push({ items, start, opts }); };
"""

    def test_the_picker_chooses_and_saves_with_undo(self):
        self.run_js(self.PICKER + """
          let done = [];
          openCoverPicker("casual/gruul", (cover, revision) => done.push([cover.name, revision]));
          await flush();
          same(asked, ["/api/deck/cards?id=casual%2Fgruul"]);          // the light read, not the whole deck page
          const sheet = openDialog();
          // Automatic first, then each card once; the cards (not Automatic) are the viewer group "cover".
          const picks = sheet.querySelectorAll(".cover-tile-pick");
          same(picks.map((p) => p.getAttribute("aria-label")), ["Automatic: Llanowar Elves", "Llanowar Elves", "Shock", "Forest"]);
          assert.equal(picks[0].getAttribute("data-viewer"), null);
          assert(picks.slice(1).every((p) => p.getAttribute("data-viewer") === "cover"));
          assert.equal(picks[0].getAttribute("aria-pressed"), "true");
          // Each tile shows the printing the deck page shows.
          assert.equal(picks[2].querySelector("img").getAttribute("src"), "/img/m19/156/art_crop");
          // The magnifier opens the viewer over the group, at that card.
          sheet.querySelectorAll(".cover-tile-zoom")[2].click();
          assert.equal(inspections.at(-1).card.name, "Shock");
          assert.equal(inspections.at(-1).trigger, picks[2]);
          // Automatic's opens it at its card's own tile: three cards, none twice.
          const autoZoom = sheet.querySelectorAll(".cover-tile-zoom")[0];
          autoZoom.click();
          same(viewed[0].items.map((i) => i.card.name), ["Llanowar Elves", "Shock", "Forest"]);
          assert.equal(viewed[0].start, 0);
          assert.equal(viewed[0].opts.trigger, autoZoom);
          // Nothing chosen yet: the button only closes.
          assert(button(sheet, "Keep this picture"));
          picks[2].click();
          assert.equal(picks[2].getAttribute("aria-pressed"), "true");
          button(sheet, "Use this picture").click();
          await flush();
          same(sent, [{ profile: "matt", id: "casual/gruul", expect: 3, cover: { name: "Shock", set: "m19", number: "156" } }]);
          same(done, [["Shock", 4]]);
          // Undo puts back the automatic picture, at the new revision.
          button(document.querySelector("#toast-undo"), "Undo").click();
          await flush();
          same(sent[1], { profile: "matt", id: "casual/gruul", expect: 4, cover: null });
          same(done[1], ["Llanowar Elves", 5]);
        """)

    def test_undo_writes_back_the_line_as_it_was(self):
        self.run_js(self.PICKER + """
          // The line names a card but no printing: the picture shown is some printing of it, yet Undo writes
          // back the bare name, and that card's tile is the one marked (whatever the case of the name).
          answer = view({ name: "Shock", set: null, number: null, shown_set: "m21", shown_number: "159", auto: false,
            art: "/img/m21/159/art_crop" });
          openCoverPicker("casual/gruul", () => {});
          await flush();
          const sheet = openDialog();
          const picks = sheet.querySelectorAll(".cover-tile-pick");
          assert.equal(picks[2].getAttribute("aria-pressed"), "true");
          assert.equal(picks[2].querySelector("img").getAttribute("src"), "/img/m21/159/art_crop");
          assert(button(sheet, "Keep this picture"));                  // the card already chosen
          picks[1].click();
          button(sheet, "Use this picture").click();
          await flush();
          button(document.querySelector("#toast-undo"), "Undo").click();
          await flush();
          same(sent[1], { profile: "matt", id: "casual/gruul", expect: 4, cover: { name: "Shock" } });
        """)

    def test_an_unusable_line_gets_no_undo_and_automatic_removes_it(self):
        self.run_js(self.PICKER + """
          // The line names no Scryfall card, so the picture fell back to automatic. The cover API can't write
          // the line back as it was, so a new choice gets no Undo (which would remove the line instead).
          const bad = { name: "Llanowar Elves", set: "fdn", number: "227", auto: true, art: "/img/fdn/227/art_crop",
            written: "Llanowr Elves", problem: "Llanowr Elves isn't a Scryfall card name" };
          answer = view(bad);
          let toasts = []; toast = (words) => toasts.push(words);
          openCoverPicker("casual/gruul", () => {});
          await flush();
          let sheet = openDialog();
          assert(sheet.textContent.includes("so the picture is automatic"));
          sheet.querySelectorAll(".cover-tile-pick")[2].click();
          button(sheet, "Use this picture").click();
          await flush();
          same(sent[0].cover, { name: "Shock", set: "m19", number: "156" });
          assert.equal(document.querySelector("#toast-undo .btn"), null);
          assert(toasts.at(-1).includes(`The line it replaced ("Llanowr Elves") is in the deck's history.`));
          // Automatic is already marked, yet saving it is a change: it takes the unusable line away.
          openCoverPicker("casual/gruul", () => {});
          await flush();
          sheet = openDialog();
          assert.equal(sheet.querySelectorAll(".cover-tile-pick")[0].getAttribute("aria-pressed"), "true");
          button(sheet, "Use this picture").click();
          await flush();
          same(sent[1].cover, null);
        """)

    def test_the_card_viewer_offers_the_large_picture(self):
        self.run_js("""
          assert.equal(viewerLargeUrl("/img/fdn/227/normal"), "/img/fdn/227/large");
          assert.equal(viewerLargeUrl("/img/isd/51/normal-back"), "/img/isd/51/large-back");
          assert.equal(viewerLargeUrl("/img/fdn/227/small"), null);
          assert.equal(viewerLargeUrl("https://cards.scryfall.io/normal/front/x.jpg"), null);
          const slide = el("div");
          fillSlide(slide, { card: { name: "Shock", type_line: "Instant", img: "/img/fdn/1/normal", img_small: "/img/fdn/1/small" } }, 0, true);
          const img = slide.querySelector("img");
          assert.equal(img.srcset, "/img/fdn/1/normal 488w, /img/fdn/1/large 672w");
          assert.equal(img.src, "/img/fdn/1/normal");
          assert(img.sizes);
        """)

    def test_a_stale_deck_says_so_in_the_sheet(self):
        self.run_js("""
          as("matt", MAY.admin);
          api = async (path) => {
            if (path.startsWith("/api/deck/cards?")) return { summary: { id: "casual/gruul", title: "Gruul", revision: 3, cover: null },
              auto: null, cards: [{ name: "Shock", set: "fdn", number: "1",
                card: { name: "Shock", type_line: "Instant", img: "/img/fdn/1/normal" } }] };
            throw new ApiError(409, "Gruul changed after you opened it.");
          };
          openCoverPicker("casual/gruul", () => { throw new Error("not saved"); });
          await flush();
          const sheet = openDialog();
          sheet.querySelectorAll(".cover-tile-pick")[1].click();
          button(sheet, "Use this picture").click();
          await flush();
          assert(sheet.querySelector(".form-error").textContent.includes("changed after you opened it"));
        """)


TABLES = r"""
  const sha = (c) => c.repeat(64);
  const entry = (id, title, count, may) => ({ id, title, sha256: sha(id[7]), count, changes: [], may_update: may });
  const STALE = { warnings: [],
    stale: [entry("casual/gruul", "Gruul", 2, true), entry("commander/giada", "Giada", 1, false),
            entry("casual/otters", "Otters", 1, true)],
    blocked: [{ id: "casual/otters", title: "Otters", space: "home", reason: "unknown_cards", version: "owned",
                cards: ["Bogus Card", "Other Bogus"], why: "..." },
              { id: "casual/otters", title: "Otters", space: "home", reason: "no_table", version: null, cards: [], why: "..." }],
    held: [{ space: "user2", warnings: [], unknown: [{ name: "Bogus Card", where: ["user2/casual/elves"] }], why: "Cannot refresh" }] };
  const posted = [];
  let decksAsked = 0;
  function serve(stale = STALE) {
    api = async (path) => {
      if (path === "/api/tables/stale") return stale;
      if (path === "/api/decks") { decksAsked += 1; return DATA; }
      throw new ApiError(404, "unexpected " + path);
    };
  }
  const panel = () => main.querySelector("#stale-tables");
  const items = (list) => list.querySelectorAll("li").map((li) => li.textContent);
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class LibraryTablesTests(_Shelf):
    """The Decks page's Tables out of date list (library-tables.js, E7-S09), and the notes linking to it."""

    def run_js(self, scenario):
        super().run_js(TABLES + scenario)

    def test_the_list_names_stale_and_blocked_decks_and_updates_all_in_one_change(self):
        self.run_js("""
          as("matt", MAY.admin);
          serve();
          apiWrite = async (path, body) => { posted.push([path, body]);
            return { updated: [{ id: "casual/gruul", title: "Gruul", sha256: sha("d"), repriced: true, note: null }],
              unchanged: [], skipped_not_allowed: [], warnings: [], stale_tables: [STALE.stale[1], STALE.stale[2]] }; };
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1")));
          // Drawn with the shelf but hidden until its own request answers: it never holds the shelf up.
          assert(panel().hidden);
          assert(tiles().length > 0);
          await flush();
          assert(!panel().hidden);
          // Under the warnings, before the filters.
          assert(main.children.indexOf(panel()) < main.children.indexOf(main.querySelector(".lib-filters")));
          // A blocked deck is listed only under "Can't be updated", once, with every reason in plain words.
          assert.equal(panel().querySelector("h2").textContent, "2 decks' owned-vs-needed tables are out of date");
          const [stale, blocked] = panel().querySelectorAll(".sources-list");
          same(items(stale), ["Gruul (2 cards changed)", "Giada (1 card changed)"]);
          assert.equal(stale.querySelector("a").getAttribute("href"), deckHref("casual/gruul"));
          assert.equal(panel().querySelector("h3").textContent, "Can't be updated");
          same(items(blocked), [`Otters: card names Deck Lab doesn't know in its ${listName("owned", true)}: Bogus Card, Other Bogus; it has no owned-vs-needed table.`]);
          assert(panel().querySelector(".note").textContent.includes(
            `Update all, receipts and orders leave ${spaceName("user2")}'s decks' tables as they are until this is fixed: card names Deck Lab doesn't know: Bogus Card (in user2/casual/elves).`));
          assert(panel().textContent.includes("Update all updates the 1 deck you may change; the others wait for whoever plays them."));
          // Update all is a plain button: New deck is the page's one primary action.
          const all = button(panel(), "Update all");
          assert(!all.getAttribute("class").includes("btn-primary"));
          all.click();
          await flush();
          // One change, only the decks this visitor may update.
          same(posted, [["/api/tables/update", { decks: [{ id: "casual/gruul", sha256: sha("g") }] }]]);
          assert(panel().textContent.includes("Updated 1 table. Saved in Deck Lab."));
          // What's left: Giada (someone else's), and not Otters (blocked, so still under Can't be updated).
          assert.equal(panel().querySelector("h2").textContent, "A deck's owned-vs-needed table is out of date");
          same(items(panel().querySelector(".sources-list")), ["Giada (1 card changed)"]);
          assert.equal(button(panel(), "Update all"), null);
          assert(panel().textContent.includes("You can't change these decks, so their tables wait for whoever plays them."));
          // The shelf's counts follow the tables: its decks are fetched again.
          assert.equal(decksAsked, 1);
          assert(!/git|commit/i.test(panel().textContent));
        """)

    def test_an_incomplete_collection_holds_its_space_s_tables(self):
        self.run_js("""
          as("matt", MAY.admin);
          serve({ stale: [STALE.stale[0]], blocked: [], warnings: [],
                  held: [{ space: "home", warnings: [], unknown: [{ name: "Bogus Card", where: ["casual/otters"] }], why: "x" }] });
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1")));
          await flush();
          // Gruul is listed, but Update all would work it out from a collection the refresh refuses.
          same(items(panel().querySelector(".sources-list")), ["Gruul (2 cards changed)"]);
          assert.equal(button(panel(), "Update all"), null);
          assert(panel().textContent.includes("These tables wait until the problem below is fixed."));
          assert(panel().querySelector(".note").textContent.startsWith("Update all, receipts and orders leave the home decks' tables as they are"));
        """)

    def test_nothing_out_of_date_or_a_failure_leaves_it_hidden(self):
        self.run_js("""
          as("user1", MAY.user1);
          serve({ stale: [], blocked: [], held: [], warnings: [] });
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1")));
          await flush();
          assert(panel().hidden);
          assert.equal(panel().children.length, 0);
          clear(main);
          api = async () => { throw new ApiError(503, "The database can't be reached."); };
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1")));
          await flush();
          assert(panel().hidden);
          assert(tiles().length > 0);
          // Only blocked decks: the panel's heading says so.
          clear(main);
          serve({ stale: [], held: [], warnings: [], blocked: [STALE.blocked[1]] });
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1")));
          await flush();
          assert.equal(panel().querySelector("h2").textContent, "A deck's owned-vs-needed table can't be updated");
          same(items(panel().querySelector(".sources-list")), ["Otters: it has no owned-vs-needed table."]);
          assert.equal(button(panel(), "Update all"), null);
        """)

    def test_the_address_scrolls_to_it_once(self):
        self.run_js("""
          as("matt", MAY.admin);
          serve();
          const urls = [];
          history.replaceState = (s, t, url) => urls.push(url);
          location.hash = "#/library?all=1&tables=1";
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1&tables=1")));
          assert.equal(panel().scrolled, undefined);
          await flush();
          assert.equal(panel().scrolled, 1);
          assert.equal(panel().scrollOptions.block, "start");
          // The address drops the ask (the filters stay), so coming back doesn't scroll again.
          same(urls, ["#/library?all=1"]);
          // Without it, nothing scrolls and the address stays.
          clear(main);
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1")));
          await flush();
          assert.equal(panel().scrolled, undefined);
          same(urls, ["#/library?all=1"]);
          assert.equal(filtersHash(libraryFilters(new URLSearchParams("tables=1"))), "#/library");
        """)

    def test_a_changed_deck_lists_them_again(self):
        self.run_js("""
          as("matt", MAY.admin);
          serve();
          apiWrite = async () => { throw new ApiError(409, "Changed.", { conflict: { decks: [
            { title: "Gruul", by: "User1", deck_lab: true, when: null }] } }); };
          drawLibrary(DATA, libraryFilters(new URLSearchParams("all=1")));
          await flush();
          serve({ ...STALE, blocked: [], held: [] });
          button(panel(), "Update all").click();
          await flush();
          assert(panel().querySelector(".form-error").textContent.includes(
            "Since this list was worked out, User1 saved Gruul in Deck Lab. No tables were updated."));
          // The list as it is now: Otters isn't blocked any more, so it's back in it.
          same(items(panel().querySelector(".sources-list")),
               ["Gruul (2 cards changed)", "Giada (1 card changed)", "Otters (1 card changed)"]);
          assert.equal(panel().querySelector("h3"), null);
        """)

    def test_after_a_save_only_the_decks_the_visitor_may_update(self):
        self.run_js("""
          as("user1", MAY.user1);
          const part = staleTablesPart([entry("commander/giada", "Giada", 1, true), entry("casual/gruul", "Gruul", 2, false)]);
          assert.equal(part.querySelector("h3").textContent, "Another deck's owned-vs-needed table is out of date");
          same(items(part), ["Giada (1 card changed)"]);
          assert(button(part, "Update its table").getAttribute("class").includes("btn-primary"));
          // Nothing they may update: nothing at all.
          assert.equal(staleTablesPart([entry("casual/gruul", "Gruul", 2, false)]).children.length, 0);
        """)

    def test_the_collection_and_receipt_notes_link_to_the_list(self):
        self.run_js("""
          as("matt", MAY.admin);
          assert.equal(staleTablesNote([]), null);
          assert.equal(staleTablesNote(undefined), null);
          const two = staleTablesNote(STALE.stale.slice(0, 2));
          assert.equal(two.textContent, "2 decks' owned-vs-needed tables are now out of date. See them on Decks");
          assert.equal(two.querySelector("a").getAttribute("href"), "#/library?tables=1");
          assert(staleTablesNote(STALE.stale.slice(0, 1)).textContent.startsWith("1 deck's owned-vs-needed table is now out of date."));
          // The Collection page's message carries it under what the save did.
          const cv = { message: el("div") };
          colSay(cv, "Shock (FDN 1) added.", STALE.stale.slice(0, 2));
          assert.equal(cv.message.querySelectorAll("p").length, 2);
          assert.equal(cv.message.querySelector("a").getAttribute("href"), TABLES_HREF);
          colSay(cv, "Shock (FDN 1) added.");
          assert.equal(cv.message.querySelectorAll("p").length, 1);
          // After an import the page is drawn again (colReload): the note survives the redraw.
          const realRoute = route;
          route = () => {};
          colReload({ space: "home" }, "Imported 5 cards.", STALE.stale.slice(0, 2));
          route = realRoute;
          const redrawn = { space: "home", message: el("div") };
          colTakeNotice(redrawn);
          assert.equal(redrawn.message.querySelector("a").getAttribute("href"), TABLES_HREF);
          assert(redrawn.message.textContent.includes("2 decks' owned-vs-needed tables are now out of date."));
          assert.equal(state.colNotice, null);
          // Receive delivery's note: one sentence (a .note is a flex row), with the link in it.
          const note = tablesLaterNote("Not updated: Beta Deck.");
          assert.equal(note.children.length, 1);
          assert.equal(note.textContent, "Not updated: Beta Deck. They're on the Decks page's Tables out of date list, where Update all refreshes them.");
        """)


@unittest.skipUnless(NODE, "Node.js isn't installed")
class LibraryGlanceTests(_Shelf):
    """The lab's detail pane past its summary (library-glance.js): the guide's opening and the key cards."""

    def test_the_guide_opening_is_plain_text_with_stops(self):
        self.run_js(r"""
          assert.equal(libGlanceText("## Plan\nGo **wide** with [Otters](https://x.example) and `Opt`.\n\n- Mulligan seven lands\n- Hold Bolt"),
            "Plan. Go wide with Otters and Opt. Mulligan seven lands. Hold Bolt.");
          assert.equal(libGlanceText(""), "");
        """)

    def test_key_cards_follow_this_decks_guide_not_the_last_deck_page(self):
        self.run_js(r"""
          state.cards = new Map([["Elsewhere", {}]]);       // the last deck page's cards, not this deck's
          const card = (name) => ({ name, type_line: "Creature — Elf", cmc: 2 });
          const data = { summary: { kind: "commander" }, guide: { sections: [{ title: "Plan", markdown: "Beta wins. Beta again." }] },
            sections: { Commander: [{ qty: 1, name: "Boss", card: card("Boss") }],
              Deck: [{ qty: 1, name: "Alpha", card: card("Alpha") }, { qty: 1, name: "Beta", card: card("Beta") }] } };
          const { commanders, lines } = keyCardLines(data, cardNamesPattern(["Boss", "Alpha", "Beta"]));
          assert.deepEqual(lines.map((l) => l.name), ["Boss", "Beta", "Alpha"]);
          assert.equal(commanders.length, 1);
        """)


if __name__ == "__main__":
    unittest.main()
