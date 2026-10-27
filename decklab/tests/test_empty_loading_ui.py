"""The shared empty, loading, nothing-selected and load-failure pieces (E11-S30 slice 15;
design/visual-design.md 4.10, UI-KIT.md "Empty, loading and failed"): core.js's loadingBox, emptyBox,
noneSelected, loadFailed and errorBox, and their styles in components.css.

Loads every page script in its real order into the event/DOM double (fixtures/workspace_ui_runner.js):
no browser, server or write.
"""
import json
import re
import subprocess
import unittest

from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB

SETUP = r"""
  function check(ok, what) { if (!ok) throw new Error(what); }
  function cls(node, name) { return (node.getAttribute("class") || "").split(/\s+/).includes(name); }
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class EmptyLoadingUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), SETUP + scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_loading_box_is_a_status_with_an_ellipsis(self):
        self.run_js(r"""
          const big = loadingBox();
          check(big.getAttribute("role") === "status", "announced");
          check(big.textContent === "Loading…", "default words end in an ellipsis: " + big.textContent);
          check(big.children[0].getAttribute("aria-hidden") === "true", "spinner hidden");
          const small = loadingBox("Working out the plan…", { small: true });
          check(cls(small, "loading-small"), "small size");
          check(cls(small.children[0], "spinner-small"), "small spinner");
        """)

    def test_empty_box_is_one_line_and_one_action(self):
        self.run_js(r"""
          const quiet = emptyBox("There are no decks yet.");
          check(cls(quiet, "empty"), "class");
          check(quiet.getAttribute("role") === null, "not announced unless live");
          check(quiet.children.length === 1 && quiet.children[0].tag === "p", "just the line");
          const act = el("button", { class: "btn", text: "Clear the search" });
          const live = emptyBox("No cards match.", act, { live: true });
          check(live.getAttribute("role") === "status", "a filter result is announced");
          check(live.children.length === 2 && live.children[1] === act, "the one action after the line");
        """)

    def test_none_selected_is_one_quiet_line(self):
        self.run_js(r"""
          const line = noneSelected("Pick a card to see its copies.");
          check(line.tag === "p" && cls(line, "none-selected"), "a quiet line");
          check(line.textContent === "Pick a card to see its copies.", "words");
        """)

    def test_load_failed_says_what_and_offers_try_again(self):
        self.run_js(r"""
          let tries = 0;
          const err = new ApiError(503, "The database can't be reached", {});
          const box = loadFailed("Its key cards", err, () => tries++);
          check(box.getAttribute("role") === "alert", "announced");
          check(box.textContent.includes("Its key cards couldn't be loaded. The database can't be reached (error 503)"),
                 "words: " + box.textContent);
          const again = box.querySelector("button");
          again.click();
          check(tries === 1, "Try again retries");
          check(!loadFailed("The plan", null).querySelector("button"), "no retry, no button");
        """)

    def test_error_box_in_a_sheet_has_no_way_back_to_the_library(self):
        self.run_js(r"""
          const err = new ApiError(500, "Not found", {});
          const sheet = errorBox("The preview couldn't be loaded", err, null);
          check(sheet.getAttribute("role") === "alert", "announced");
          check(!sheet.querySelector("a"), "no Back to the library inside a sheet");
          check(!sheet.querySelectorAll("div").length, "no empty actions row");
          let tries = 0;
          const part = errorBox("The list couldn't be loaded", err, () => tries++);
          check(part.querySelector("button").textContent === "Try again", "retry is the primary");
          check(part.querySelector("a").getAttribute("href") === "#/library", "the page keeps its way back");
          const gone = errorBox("No such deck", new ApiError(404, "Not found", {}));
          check(!gone.querySelector("button"), "a 404 page can't be retried");
          check(cls(gone.querySelector("a"), "btn-primary"), "so the way back is the primary");
        """)


class EmptyLoadingCssTests(unittest.TestCase):
    def test_styles_use_the_p1_tokens(self):
        css = (WEB / "components.css").read_text(encoding="utf-8")
        empty = re.search(r"\.empty, \.shopping-empty, \.activity-empty \{(.*?)\}", css, re.S).group(1)
        self.assertIn("border-radius: var(--r-panel)", empty)       # 14 casual, 8 in the lab
        none = re.search(r"\.none-selected \{(.*?)\}", css, re.S).group(1)
        self.assertIn("color: var(--ink-3)", none)
        self.assertIn(".loading-small {", css)
        self.assertIn(".load-failed {", css)


if __name__ == "__main__":
    unittest.main()
