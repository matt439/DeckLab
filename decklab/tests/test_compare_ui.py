"""The Compare page (compare.js, E1-S13's first slice) under Node: the two decks' heads, the stats in brief, the
curves on one scale, colour sources and card types with a column per deck, the pickers and Compare, and the deck
page's "Compare with…".

Loads every page script into the event/DOM double (fixtures/workspace_ui_runner.js): no browser or server.
"""
import json
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = r"""
  const bucket = (mv, creatures, noncreatures, cards = []) => ({ mv, creatures, noncreatures,
    total: creatures + noncreatures, cards });
  const stats = (o) => ({
    curve: { average_mv: o.avg, creatures: o.creatures, noncreatures: o.other,
      buckets: o.buckets },
    lands: { lands: o.lands, effective: o.lands, recommended: o.rec, verdict: o.verdict, mana_creatures: o.makers || [],
      mana_rocks: [] },
    colours: { colours: o.colours },
    types: o.types, roles: o.roles, commander: o.commander || null,
  });
  const colour = (c, name, have, needed, ok) => ({ colours: c, name, ok, hardest: { have, needed, margin: have - needed } });
  const alpha = { summary: { id: "casual/alpha", title: "Alpha Aggro", kind: "casual", status: "built", card_count: 60,
      sideboard_count: 15, versions: ["target"], colors: ["R", "G"] }, version: "target", warnings: [],
    stats: stats({ avg: 2.1, creatures: 24, other: 12, lands: 24, rec: 23.4, verdict: "ok",
      buckets: [bucket("0", 0, 0), bucket("1", 8, 4, [{ name: "Llanowar Elves", qty: 4 }]), bucket("2", 10, 4), bucket("3", 6, 4)],
      colours: [colour("G", "green", 14, 13, true), colour("R", "red", 12, 14, false)],
      types: [{ type: "creature", count: 24 }, { type: "instant", count: 8 }, { type: "sorcery", count: 0 }],
      roles: [{ role: "removal", count: 6 }, { role: "ramp", count: 0 }] }) };
  const beta = { summary: { id: "commander/beta", title: "Beta Commander", kind: "commander", status: "building",
      card_count: 100, sideboard_count: 0, versions: ["target", "owned"], colors: ["U"] }, version: "owned", warnings: [],
    stats: stats({ avg: 3.4, creatures: 30, other: 32, lands: 36, rec: 37.0, verdict: "low",
      buckets: [bucket("0", 0, 1), bucket("1", 2, 4), bucket("2", 8, 10), bucket("3", 20, 17)],
      colours: [colour("U", "blue", 30, 20, true)],
      types: [{ type: "creature", count: 30 }, { type: "artifact", count: 9 }],
      roles: [{ role: "draw", count: 10 }],
      commander: { ok: true, bracket: { label: "Bracket 2" } } }) };
  const library = { decks: [
    { id: "casual/alpha", title: "Alpha Aggro", kind: "casual", versions: ["target"] },
    { id: "commander/beta", title: "Beta Commander", kind: "commander", versions: ["target", "owned"] },
  ], halves: [] };
  const text = (node) => node.textContent;
  const rowsOf = (table) => table.querySelectorAll("tr").map((tr) => tr.children.map(text));
  const main = $("#main");
"""


def run(scenario):
    result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    return result


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CompareUiTests(unittest.TestCase):

    def check(self, scenario):
        result = run(scenario)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_two_decks_side_by_side(self):
        self.check(r"""
          const want = { a: "casual/alpha", av: "target", b: "commander/beta", bv: "owned" };
          compareDraw(library, { decks: [alpha, beta] }, want, routeToken);
          assert.equal(main.querySelector("h1").textContent, "Compare decks");
          // The crumb goes back to the first deck.
          assert(main.querySelector(".crumbs").textContent.includes("Alpha Aggro"));
          const heads = main.querySelectorAll(".cmp-head");
          assert.equal(heads.length, 2);
          assert.equal(heads[0].querySelector("a").getAttribute("href"), deckHref("casual/alpha", "target"));
          assert.equal(heads[1].querySelector("a").getAttribute("href"), deckHref("commander/beta", "owned"));
          assert(text(heads[1]).includes("Play-now list"));     // a deck with two lists names the one compared
          assert(!text(heads[0]).includes("Planned list"));
          // In brief: one row per figure, a column per deck.
          const brief = rowsOf(main.querySelector(".cmp-brief").querySelector("table"));
          same(brief[0].slice(1), ["Alpha Aggro", "Beta Commander"]);
          const row = (rows, label) => rows.find((r) => r[0] === label);
          same(row(brief, "Cards").slice(1), ["60 + 15 sideboard", "100"]);
          same(row(brief, "Average mana value").slice(1), ["2.1", "3.4"]);
          assert.equal(row(brief, "Lands")[1], "24 (formula 23.4)");
          assert(row(brief, "Lands")[2].includes("Low"));
          assert(row(brief, "Colour sources")[1].includes("Red") && row(brief, "Colour sources")[1].includes("Short"));
          assert.equal(row(brief, "Colour sources")[2], "Enough");
          same(row(brief, "Bracket").slice(1), ["–", "Bracket 2"]);
          // The curves: two charts, queued to draw on one scale.
          const curve = main.querySelector('[aria-labelledby="cmp-h-curve"]');
          assert.equal(curve.querySelectorAll(".cmp-figure").length, 2);
          const curveRows = rowsOf(curve.querySelector("table"));
          same(row(curveRows, "Mana value 3").slice(1), ["10", "37"]);
          // Colours: every colour either deck needs, in WUBRG order.
          const colours = rowsOf(main.querySelector('[aria-labelledby="cmp-h-colours"]').querySelector("table"));
          same(colours.slice(1).map((r) => r[0]), ["Blue", "Red", "Green"]);
          assert.equal(row(colours, "Blue")[1], "Not needed");
          assert(row(colours, "Red")[1].startsWith("12 of 14") && row(colours, "Red")[1].includes("Short by 2"));
          // Types and roles: only those either deck has, a 0 where the other has none.
          const types = main.querySelector('[aria-labelledby="cmp-h-types"]').querySelectorAll("table");
          same(rowsOf(types[0]).slice(1), [["Creature", "24", "30"], ["Instant", "8", "0"], ["Artifact", "0", "9"]]);
          same(rowsOf(types[1]).slice(1), [["Removal", "6", "0"], ["Card draw", "0", "10"]]);
        """)

    def test_curves_share_the_taller_deck_s_scale(self):
        self.check(r"""
          const host = el("div");
          drawCurve(host, alpha.stats.curve, 320, () => {}, 37);
          const ticks = host.querySelectorAll("text").filter((t) => t.getAttribute("class") === "axis-text").map(text);
          assert(ticks.includes("40"), ticks.join(","));      // 37 at most: a scale to 40, not to alpha's own 14
          const own = el("div");
          drawCurve(own, alpha.stats.curve, 320, () => {});
          const mine = own.querySelectorAll("text").filter((t) => t.getAttribute("class") === "axis-text").map(text);
          assert(!mine.includes("40") && mine.includes("15"), mine.join(","));
        """)

    def test_the_pickers_put_the_decks_in_the_address(self):
        self.check(r"""
          // From a deck page's "Compare with…": the first deck chosen, the second the first other one.
          compareDraw(library, null, { a: "commander/beta", av: "owned", b: null, bv: "target" }, routeToken);
          assert.equal(main.querySelectorAll(".cmp-head").length, 0);
          const form = main.querySelector(".cmp-pick");
          const event = form.fire("submit");
          assert(event.defaultPrevented);
          assert.equal(location.hash, "#/compare?a=commander%2Fbeta&av=owned&b=casual%2Falpha&bv=target");
          assert.equal(compareHref("pairing/cats+elves", "target"), "#/compare?a=pairing%2Fcats%2Belves&av=target");
        """)

    def test_a_side_without_stats(self):
        self.check(r"""
          const broken = { ...beta, stats: null, warnings: ["The deck stats couldn't be worked out"] };
          compareDraw(library, { decks: [alpha, broken] }, { a: "casual/alpha", av: "target", b: "commander/beta", bv: "owned" }, routeToken);
          assert(text(main).includes("The stats of Beta Commander couldn't be worked out"));
          assert(text(main).includes("Beta Commander: The deck stats couldn't be worked out"));
          assert.equal(main.querySelectorAll(".panels").length, 0);
          const brief = rowsOf(main.querySelector(".cmp-brief").querySelector("table"));
          same(brief.find((r) => r[0] === "Average mana value").slice(1), ["2.1", "–"]);
        """)

    def test_the_deck_page_offers_compare_with(self):
        self.check(r"""
          const items = deckMoreItems({ summary: { id: "casual/alpha", read_only: false }, version: "owned" })
            .filter((i) => i && i !== "sep");
          const item = items.find((i) => i.label === "Compare with…");
          assert(item, items.map((i) => i.label).join(", "));
          assert.equal(item.href, "#/compare?a=casual%2Falpha&av=owned");
          assert.equal(routeSection("compare").path, "library");
        """)


if __name__ == "__main__":
    unittest.main()
