"""Deck Lab on the user's own devices (decklab/UI-KIT.md, "Test devices"): the iPhone 15 Pro and 17 Pro, upright
and on their side, the iPad Air 11, the MacBook Air 13 and the QHD screen. The shell's top bar, the deck page's
tabs, the editor and its search, and the Stats and Practice panels, checked in the stylesheets' text and, for
the editor's choice of layout, by running editor.js under Node.js."""
import json
import re
import subprocess
import unittest

from decklab.tests.test_web import STYLES, _function, _scripts, _styles, _text
from decklab.tests.test_workspace_ui import NODE, RUNNER, WEB


def _block(css, query):
    """The rules inside every @media block with exactly this query, joined."""
    return "\n".join(re.findall(rf"@media {re.escape(query)} \{{\n(.*?)\n\}}", css.replace("\r\n", "\n"), re.S))


class DeviceLayoutFileTests(unittest.TestCase):
    def test_avatar_at_the_top_bars_right(self):
        # The avatar's own auto margin keeps it at the bar's right edge (the status pill is hidden most of the
        # time); a shown pill pushes itself and the avatar right instead.
        shell = _text("shell.css")
        self.assertRegex(shell, r"\.topbar-actions \{[^}]*margin-left: auto")
        self.assertIn(".shell-status:not([hidden]) + .topbar-actions { margin-left: 0; }", shell)

    def test_short_landscape_lets_the_top_bar_scroll_away(self):
        # A phone on its side (852 x 330): the top bar isn't sticky, and --shell-top (where the deck's tabs and
        # a table's head stick) is the safe-area inset alone.
        query = "(orientation: landscape) and (max-height: 500px)"
        self.assertIn(".topbar { position: static; }", _block(_text("shell.css"), query))
        self.assertIn("--shell-top: env(safe-area-inset-top, 0px);", _block(_text("tokens.css"), query))
        # deck.js's "is the strip stuck?" reads where the strip sticks rather than assuming the bar's height.
        self.assertIn("getComputedStyle(screen.strip).top", _function(_scripts(), "selectDeckTab"))

    def test_bars_keep_clear_of_the_notch(self):
        # viewport-fit=cover: on its side a phone draws under the notch, so the bars' sides take the larger of
        # the gutter and the safe-area inset (the same gutter where there's no inset).
        sides = "max(var(--gutter), env(safe-area-inset-right))"
        for name, rule in (("deck.css", ".deck-tabs"), ("components.css", ".action-bar"), ("editor.css", ".edit-bar")):
            body = re.search(rf"^{re.escape(rule)} \{{(.*?)\}}", _text(name), re.S | re.M).group(1)
            self.assertIn(sides, body, name)
            self.assertIn("max(var(--gutter), env(safe-area-inset-left))", body, name)

    def test_quick_edit_steppers_are_full_size(self):
        self.assertIn(".is-quick .edit-row .edit-stepper .step { width: var(--tap); }", _text("editor.css"))

    def test_more_links_look_like_links(self):
        deck = _text("deck.css")
        self.assertRegex(deck, r"\.deck-more-link \{[^}]*color: var\(--link\)")
        self.assertIn(".deck-more-link::after", deck)

    def test_card_peek_from_1400_px(self):
        # A MacBook Air still has the shared peek beside a deck. The full editor already has three panes.
        css = _styles()
        self.assertIn(".peek-layout { display: grid;",
                      _block(css, "(min-width: 1400px) and (hover: hover) and (pointer: fine)"))
        self.assertIn("--peek-w: 280px;", _block(_text("tokens.css"), "(min-width: 1400px)"))
        self.assertIn(".edit-page.has-editor-panes .peek-layout { display: block; }", _text("editor.css"))
        self.assertIn(".edit-page.has-editor-panes .card-peek { display: none; }", _text("editor.css"))

    def test_qhd_overview_in_two_columns(self):
        qhd = _block(_text("deck.css"), "(min-width: 2200px)")
        self.assertIn("#deck-panel-overview:not([hidden])", qhd)
        self.assertIn("#deck-panel-overview > .deck-guide { grid-column: 2; grid-row: 2 / -1; }", qhd)
        self.assertIn(".deck-guide > .empty { max-width: 72ch; }", _text("deck.css"))

    def test_verdict_tiles_share_the_row(self):
        strip = _block(_text("stats.css"), "(min-width: 600px)")
        self.assertIn("repeat(auto-fit, minmax(128px, 1fr))", strip)
        self.assertIn(".verdict-strip:has(> :last-child:nth-child(3)) { max-width: calc(3 * 280px + 2 * var(--s-2)); }", strip)

    def test_editor_search_on_a_tablet(self):
        editor = _text("editor.css")
        self.assertIn("max-height: calc(var(--vvh, 100dvh) - var(--shell-top) - 104px);", editor)
        tablet = _block(editor, "(min-width: 1000px) and (pointer: coarse)")
        self.assertIn("body.is-searching.keyboard-up .edit-side .ac-tip", tablet)
        self.assertIn("body.is-searching .edit-side { height:", tablet)
        keep = _function(_scripts(), "keepSearchInView")
        self.assertIn("raiseSidePanel(ac)", keep)
        self.assertIn("body.scrollTop += by", keep)

    def test_stats_panels_stack_from_two_columns(self):
        self.assertIn(".deck-panel .panels.is-stacked { grid-auto-flow: row dense; grid-auto-rows: 8px; row-gap: 0; }",
                      _block(_text("components.css"), "(min-width: 1000px)"))
        self.assertIn('matchMedia("(min-width: 1000px)")', _function(_scripts(), "stackPanels"))
        self.assertIn('grid.classList.add("is-stacked")', _function(_scripts(), "stackPanels"))

    def test_wide_search_boxes_capped(self):
        # On a 1,600 px+ window the Tokens and Collection search boxes stay at a reading width.
        self.assertIn(".tok-tools > .tok-search { flex: 0 1 720px; }", _block(_text("tokens-page.css"), "(min-width: 1600px)"))
        self.assertIn(".col-filters { grid-template-columns: minmax(0, 760px) minmax(0, 960px); }",
                      _block(_text("collection.css"), "(min-width: 1600px)"))


def _matches(query, device):
    """Whether a media query of ANDed features (min/max-width, max-height, pointer, hover, orientation) fits a
    device given as {"width", "height", "pointer", "hover"}. Any other shape fails loudly."""
    if "," in query or re.search(r"\b(not|only|screen|print|all)\b", query):
        raise AssertionError(f"_matches can't evaluate {query}")
    for name, value in re.findall(r"\(([\w-]+):\s*([^)]+)\)", query):
        value = value.strip()
        if name in ("min-width", "max-width", "max-height"):
            size = device["height" if name == "max-height" else "width"]
            limit = int(value.removesuffix("px"))
            if (size < limit) if name == "min-width" else (size > limit):
                return False
        elif name == "orientation":
            if value != ("landscape" if device["width"] > device["height"] else "portrait"):
                return False
        elif name in ("pointer", "hover"):
            if device[name] != value:
                return False
        else:
            raise AssertionError(f"_matches doesn't know {name}")
    return True


def _tokens_on(device):
    """tokens.css's light custom properties as a device with no theme override would compute them."""
    css = re.sub(r"/\*.*?\*/", "", _text("tokens.css").replace("\r\n", "\n"), flags=re.S)
    values = dict(re.findall(r"(--[\w-]+):\s*([^;]+);", re.search(r"^:root \{(.*?)^\}", css, re.S | re.M).group(1)))
    blocks = re.findall(r"^@media ([^{]+) \{\n(.*?)^\}", css, re.S | re.M)
    assert len(blocks) == css.count("@media"), "a @media block _tokens_on can't read"
    for query, body in blocks:
        if "prefers" not in query and _matches(query, device):
            values.update(re.findall(r"(--[\w-]+):\s*([^;]+);", body))
    return {name: value.strip() for name, value in values.items()}


def _device(width, height, pointer):
    return {"width": width, "height": height, "pointer": pointer, "hover": "hover" if pointer == "fine" else "none"}


IPHONE = _device(393, 852, "coarse")
PHONE_LANDSCAPE = _device(852, 393, "coarse")
IPAD_PORTRAIT = _device(820, 1180, "coarse")
NARROW_WINDOW = _device(900, 900, "fine")
IPAD_LANDSCAPE = _device(1180, 820, "coarse")
MACBOOK = _device(1470, 956, "fine")
QHD = _device(2560, 1440, "fine")

# Every token slices 3, 4 and 6 added, and the older ones they leave alone, at each of the three levels
# (design/visual-design.md 2.3-2.5, 3 and 4.9; 1rem = 16 px). Slice 4 moved --r-sm to 4 px.
CASUAL = {
    "--fw-medium": "500", "--fw-heavy": "800",
    "--fs-h1": "2rem", "--fs-hero": "2rem", "--fs-eyebrow": ".8125rem", "--fs-group": ".8125rem",
    "--fs-body": "1rem", "--fs-row": "1.0625rem", "--fs-meta": ".875rem", "--fs-btn": ".9375rem",
    "--fs-input": "1rem", "--fs-th": ".65625rem", "--fs-kbd": ".65625rem", "--fs-cell-num": ".875rem",
    "--fs-fig-mid": "1.5rem", "--fs-fig": "2.5rem", "--fs-fig-unit": "1.5rem", "--fs-fig-sm": "1rem",
    "--fs-fig-range": ".875rem", "--fs-qty": "1rem", "--fs-qty-input": "1rem", "--fw-qty": "700", "--font-num": "var(--font)",
    "--ls-h1": "-.03em", "--ls-hero": "-.03em", "--ls-fig": "0em", "--ls-caps": ".08em", "--ls-th": ".07em",
    "--lh-copy": "1.5",
    "--r-panel": "14px", "--r-row": "8px", "--r-field": "12px",
    "--btn-h": "44px", "--seg-h": "44px", "--input-h": "44px", "--stepper-h": "46px", "--check-size": "24px",
    "--row-h": "44px", "--th-h": "30px", "--seg-track": "var(--track)", "--list-row-h": "54px", "--tile-min": "104px", "--tile-min-forge": "112px",
    "--flag-h": "30px", "--gutter-list": "var(--gutter)",
    "--ctl-h": "44px", "--field-h": "44px", "--tap": "44px",
    "--fs-md": "1rem", "--r-sm": "4px", "--r-md": "10px", "--r-lg": "14px",
    # Slice 6: Forge's result pieces (sim-ui.js).
    "--fs-flag": ".875rem", "--range-h": "12px", "--range-h-compact": "6px", "--fs-axis": ".875rem",
    "--fresh-h": "24px", "--fresh-h-row": "24px", "--fs-fresh": ".8125rem", "--fs-fresh-row": ".8125rem",
    "--fs-swap": "1rem", "--activity-size": "24px", "--ring-size": "24px", "--icon-xs": "12px",
}
CASUAL_MOUSE = {**CASUAL, "--btn-h": "36px", "--seg-h": "36px", "--input-h": "38px", "--stepper-h": "36px",
                "--check-size": "22px", "--row-h": "36px", "--ctl-h": "36px", "--field-h": "38px"}
TOUCH_LAB = {**CASUAL,
    "--fs-h1": "1.375rem", "--fs-hero": "1.875rem", "--fs-eyebrow": ".6875rem", "--fs-group": ".6875rem",
    "--fs-body": ".875rem", "--fs-row": ".875rem", "--fs-meta": ".75rem", "--fs-btn": ".9375rem",
    "--fs-input": "1rem", "--fs-cell-num": ".875rem", "--fs-fig-mid": "1.75rem", "--fs-fig": "2.25rem",
    "--fs-fig-unit": "1.375rem", "--fs-fig-sm": ".875rem", "--fs-fig-range": ".6875rem",
    "--fs-qty": ".875rem", "--fw-qty": "600", "--font-num": "var(--font-mono)",
    "--ls-h1": "-.025em", "--ls-fig": "-.04em", "--lh-copy": "1.4",
    "--r-panel": "8px", "--r-field": "8px", "--flag-h": "26px", "--gutter-list": "20px",
    "--fs-flag": ".8125rem", "--range-h": "10px", "--fs-axis": ".6875rem", "--fresh-h": "20px", "--fresh-h-row": "17px",
    "--fs-fresh": ".75rem", "--fs-fresh-row": ".6875rem", "--fs-swap": ".9375rem", "--activity-size": "20px",
    "--ring-size": "16px"}
LAB = {**TOUCH_LAB, **{k: CASUAL_MOUSE[k] for k in ("--row-h", "--ctl-h", "--field-h")},
    "--fs-body": ".8125rem", "--fs-btn": ".8125rem", "--fs-input": ".8125rem", "--fs-cell-num": ".78125rem",
    "--fs-fig-sm": ".8125rem", "--fs-fig-range": ".65625rem", "--fs-qty": ".78125rem", "--fs-qty-input": ".78125rem",
    "--btn-h": "32px", "--seg-h": "28px", "--input-h": "32px", "--stepper-h": "28px", "--check-size": "18px",
    "--flag-h": "22px", "--fs-flag": ".75rem"}


class DensityTokenTests(unittest.TestCase):
    # E11-S30 slice 3: one set of names at three levels, casual under 1000 px, the touch lab from 1000 px
    # without a fine pointer, the dense lab with one. Sizes only shrink under (pointer: fine).
    def check(self, device, expected):
        tokens = _tokens_on(device)
        self.assertEqual({name: tokens.get(name) for name in expected}, expected)

    def test_each_level_on_each_device(self):
        for device, expected in ((IPHONE, CASUAL), (PHONE_LANDSCAPE, CASUAL), (IPAD_PORTRAIT, CASUAL),
                                 (NARROW_WINDOW, CASUAL_MOUSE), (IPAD_LANDSCAPE, TOUCH_LAB),
                                 (MACBOOK, LAB), (QHD, LAB)):
            with self.subTest(device=device):
                self.check(device, expected)

    def test_the_switch_is_at_1000_px(self):
        self.check(_device(999, 800, "coarse"), CASUAL)
        self.check(_device(1000, 800, "coarse"), TOUCH_LAB)
        self.check(_device(999, 800, "fine"), CASUAL_MOUSE)
        self.check(_device(1000, 800, "fine"), LAB)

    def test_a_touch_screen_never_drops_below_44_px(self):
        for device in (IPHONE, IPAD_PORTRAIT, IPAD_LANDSCAPE, _device(2560, 1440, "coarse")):
            tokens = _tokens_on(device)
            for name in ("--btn-h", "--seg-h", "--input-h", "--stepper-h", "--row-h", "--ctl-h", "--field-h", "--tap"):
                with self.subTest(device=device, token=name):
                    self.assertGreaterEqual(int(tokens[name].removesuffix("px")), 44)
            self.assertEqual(tokens["--fs-input"], "1rem")     # no iOS zoom on focus


def _without_blocks(css, query):
    """The CSS with every @media block of exactly this query taken out (braces matched, any layout)."""
    out, at = [], 0
    for match in re.finditer(rf"@media {re.escape(query)} \{{", css):
        if match.start() < at:
            continue
        depth, end = 1, match.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(css[end], 0)
            end += 1
        out.append(css[at:match.start()])
        at = end
    return "".join(out) + css[at:]


def _css(name):
    return re.sub(r"/\*.*?\*/", "", _text(name).replace("\r\n", "\n"), flags=re.S)


class ComponentTests(unittest.TestCase):
    # E11-S30 slice 4: the components read the density tokens, keep a 44 px floor on touch in one place, and
    # show hover only with a mouse (design/visual-design.md 3.3 and 4.5).
    FLOORED = (".btn", ".segmented > *", ".filter-chip", ".stepper .step", ".menu > button", "table.data .th-sort",
               ".card-link")

    def test_the_touch_floor_is_one_rule(self):
        coarse = _block(_css("components.css"), "(pointer: coarse)")
        floor = re.search(r"([^{}]+)\{ min-height: var\(--tap\); \}", coarse)
        self.assertIsNotNone(floor, coarse)
        selectors = {part.strip() for part in floor.group(1).split(",")}
        for selector in self.FLOORED:
            with self.subTest(selector=selector):
                self.assertIn(selector, selectors)
        self.assertRegex(coarse, r"\.btn, \.stepper \.step \{ min-width: var\(--tap\); \}")
        # Only that block: no component keeps a coarse-pointer rule of its own.
        self.assertEqual(_css("components.css").count("@media (pointer: coarse)"), 1)
        # A page doesn't give a button its own touch height: the floor does it at every width.
        for name in STYLES[3:]:
            with self.subTest(sheet=name):
                self.assertNotRegex(_css(name), r"\.btn[\w.-]*\s*(,[^{]*)?\{[^}]*min-height: (36|44)px")

    def test_components_read_the_density_tokens(self):
        css = _css("components.css")
        rule = lambda selector: re.search(rf"^{re.escape(selector)} \{{(.*?)^\}}", css, re.S | re.M).group(1)
        button = rule(".btn")
        for part in ("min-height: var(--btn-h)", "border: 1.5px solid var(--accent)", "border-radius: var(--r-pill)",
                     "color: var(--accent-strong)", "font-size: var(--fs-btn)", "font-weight: var(--fw-bold)"):
            self.assertIn(part, button)
        self.assertIn("box-shadow: var(--shadow-primary)", re.search(r"^\.btn-primary \{([^}]*)\}", css, re.M).group(1))
        self.assertIn("min-height: var(--seg-h)", rule(".segmented"))
        self.assertIn("background: var(--seg-track)", rule(".segmented"))
        self.assertIn("min-height: var(--stepper-h)", rule(".stepper"))
        self.assertIn("table.data tbody tr:not(.label-row) { height: var(--row-h); }", css)
        base = _css("base.css")
        for part in ("min-height: var(--input-h)", "border-radius: var(--r-field)", "font-size: var(--fs-input)",
                     "width: var(--check-size); height: var(--check-size)", "box-shadow: 0 0 0 3px var(--focus-halo)"):
            self.assertIn(part, base)
        # The focus ring follows an element's corners; it never squares a round button.
        self.assertNotIn("border-radius", re.search(r"^:focus-visible \{([^}]*)\}", base, re.M).group(1))

    def test_the_selected_and_changed_states_are_the_accent_and_delivery_states_are_not(self):
        css = _css("components.css")
        self.assertRegex(css, r'\.segmented > \[aria-pressed="true"\], \.segmented > \[aria-current="page"\] \{[^}]*background: var\(--accent\)')
        self.assertRegex(css, r'\.stepper:is\(\.is-changed, \[data-changed="true"\]\) \{ border-color: var\(--accent\); \}')
        # "Part received" is a neutral outline (Matt, 2026-10-24: section 6 question 2), never the accent.
        outline = re.search(r"\.chip-outline, \.status-outline \{([^}]*)\}", css).group(1)
        self.assertNotIn("accent", outline)
        self.assertIn('status("outline", "Part received")', _function(_scripts(), "shopOrderChip"))
        # The can't-act-yet primary is drawn, not faded, and stays focusable (aria-disabled, not disabled).
        self.assertRegex(css, r'\.btn-primary\[aria-disabled="true"\] \{[^}]*background: var\(--track\); color: var\(--ink-3\)')

    def test_hover_only_with_a_mouse(self):
        # 3.3: a touch screen keeps a hover look stuck after a tap, so the components' hovers are only under
        # (hover: hover) and (pointer: fine).
        for name, selectors in (("components.css", (r"\.btn[\w.-]*:hover", r"\.segmented > :hover", r"\.filter-chip:hover",
                                                     r"\.stepper \.step:hover", r"\.menu > [\w ]*(a|button):hover",
                                                     r"tr:hover", r"\.card-link:hover")),
                                ("cards-ui.css", (r"button\.card-row:hover", r"\.tile-tick:hover", r"button\.card-tile-open:hover",
                                                   r"\.viewer-btn:hover", r"\.viewer-text \.btn:not\(\.btn-primary\):hover"))):
            rest = _without_blocks(_css(name), "(hover: hover) and (pointer: fine)")
            for selector in selectors:
                with self.subTest(sheet=name, selector=selector):
                    self.assertNotRegex(rest, r"(^|[,}\s])" + selector)

    def test_every_notice_is_amber_with_an_icon_for_its_kind(self):
        # 4.5: info, out of date and check notices are all --warn-soft with an inset --warn-line; only the icon
        # says which. --info-* is left to the info pills.
        css = _css("components.css")
        self.assertRegex(css, r"\.box-warn, \.box-stale, \.box-info \{[^}]*background: var\(--warn-soft\); [^}]*inset 0 0 0 1px var\(--warn-line\)")
        self.assertRegex(re.search(r"^\.note \{([^}]*)\}", css, re.M).group(1), r"background: var\(--warn-soft\)")
        self.assertEqual([sel.strip() for sel in re.findall(r"([^\n{}]*)\{[^}]*var\(--info-soft\)", css)],
                         [".chip-info, .status-info"])
        # The out-of-date panels are the refresh kind.
        for name, cls in (("library-tables.js", "box box-stale lib-tables"), ("editor-screen.js", "box box-stale banner saved-stale"),
                          ("editor-deckpage.js", "box box-stale stale-own")):
            with self.subTest(script=name):
                self.assertIn(f'class: "{cls}"', _text(name))

    def test_sizes_on_touch(self):
        css = _css("components.css")
        # A segmented track stays 44 on touch: its segments fill it (no inset), rather than growing it to 50.
        self.assertIn(".segmented { --seg-pad: 0px; }", _block(css, "(pointer: coarse)"))
        self.assertIn("border-radius: var(--r-seg)", re.search(r"^\.segmented \{([^}]*)\}", css, re.M).group(1))
        # A stepper's typed number keeps --fs-input's 16 px wherever iOS might zoom on focus (the touch lab's
        # --fs-qty is 14 px): --fs-qty-input, never smaller than --fs-input on a device without a fine pointer.
        self.assertIn(".stepper :is(.qty-input, input) { font-size: var(--fs-qty-input); }", css)
        for device in (IPHONE, IPAD_PORTRAIT, IPAD_LANDSCAPE, NARROW_WINDOW):
            with self.subTest(device=device):
                tokens = _tokens_on(device)
                self.assertEqual(tokens["--fs-qty-input"], tokens["--fs-input"])
        self.assertIn(".stepper output:not(.qty-input) { background: transparent; }", css)

    def test_rows_and_buttons_keep_the_pages_states(self):
        css = _css("components.css")
        # A card's label row isn't a row of its own (no row height; it and its row stay top-aligned).
        self.assertIn("table.data tbody tr:not(.label-row):not(:has(+ .label-row)) > :is(td, th) { vertical-align: middle; }", css)
        # The shared hover and lab number size weigh nothing, so a page's row state or column size wins.
        self.assertIn(":where(table.data tbody tr:hover, table.data tbody tr:has(+ .label-row:hover), "
                      "table.data tbody tr:hover + .label-row) > * { background: var(--hover); }",
                      _block(css, "(hover: hover) and (pointer: fine)"))
        self.assertIn(":where(table.data) td.num { font-family: var(--font-num); font-size: var(--fs-cell-num); }", css)
        # Words in a chosen segment take its ink; a secondary has no fill in dark.
        self.assertIn('.segmented.segmented > :is([aria-pressed="true"], [aria-current="page"]) * { color: inherit; }', css)
        self.assertIn("background: var(--btn-bg)", re.search(r"^\.btn \{([^}]*)\}", css, re.M).group(1))
        tokens = _css("tokens.css")
        self.assertRegex(re.search(r':root\[data-theme="dark"\] \{(.*?)\n\}', tokens, re.S).group(1), r"--btn-bg: transparent;")


SHELL_CASUAL = "(max-width: 599px), (max-width: 999px) and (min-height: 501px), (max-width: 999px) and (orientation: portrait)"


class ShellTests(unittest.TestCase):
    # E11-S30 slice 7 (design/visual-design.md 3.1, 3.2, 4.8 and section 6 decisions 1, 3 and 5): the casual header
    # and tab bar under 1000 px (a phone on its side keeps the lab's top bar), the lab's round nav pills, the iPad
    # in portrait's 640 px tabs, and one bar order: a page's bar on the tab bar, which no page hides.

    def test_the_tab_bar_is_under_1000_px_but_not_on_a_phone_on_its_side(self):
        casual = _block(_css("shell.css"), SHELL_CASUAL)
        self.assertIn("body.has-shell .tabbar:not([hidden]) {", casual)
        self.assertIn("--shell-bottom: calc(56px + env(safe-area-inset-bottom))", casual)
        self.assertIn(".main-nav, .main-nav[hidden] { display: none; }", casual)
        self.assertIn("#main .shell-crumb { display: none; }", casual)
        self.assertNotIn("max-width: 599px)", re.sub(r"@media \(max-width: 599px\), ", "", _css("shell.css")))
        # The same 56 px at both densities, so --shell-top has one value (but the phone on its side's).
        self.assertNotRegex(_css("tokens.css"), r"--shell-top: calc\(48px")
        self.assertIn("const TAB_COUNT = 4;", _text("shell.js"))

    def test_no_page_hides_the_tab_bar(self):
        shell = _css("shell.css")
        self.assertNotRegex(shell, r"has-edit-bar[^{]*\{[^}]*--shell-bottom: 0px")
        self.assertNotIn("rcpt-bar", shell)
        # Only an on-screen keyboard over the editor's search puts it away.
        casual = _block(shell, SHELL_CASUAL)
        self.assertIn("body.has-shell.keyboard-up { --shell-bottom: 0px; }", casual)
        self.assertIn("body.has-shell.keyboard-up .tabbar:not([hidden]) { display: none; }", casual)

    def test_a_pages_bar_sits_on_the_tab_bar(self):
        tokens = _css("tokens.css")
        self.assertIn("--bar-h: 72px;", tokens)
        self.assertIn("--bar-h: 60px;", _block(tokens, "(min-width: 1000px)"))
        self.assertIn("min-height: calc(var(--bar-h) + env(safe-area-inset-bottom))", _rule(_css("components.css"), ".action-bar"))
        edit = _rule(_css("editor.css"), ".edit-bar")
        self.assertIn("bottom: max(var(--shell-bottom, 0px), var(--editor-keyboard-bottom, 0px))", edit)
        casual = _block(_css("shell.css"), SHELL_CASUAL)
        self.assertIn("body.has-shell:not(.keyboard-up) :is(.action-bar, .edit-bar) { min-height: var(--bar-h); padding-bottom: var(--s-2); }", casual)
        # A toast goes above both bars, at either density.
        self.assertIn("bottom: calc(var(--shell-bottom) + var(--bar-h) + var(--s-2))", casual)
        self.assertIn("body:is(.has-edit-bar, :has(#main .action-bar)) .toast {", _css("components.css"))

    def test_the_lab_nav_is_round_pills(self):
        shell = _css("shell.css")
        self.assertIn("border-radius: var(--r-pill)", _rule(shell, ".nav-item"))
        self.assertIn('.nav-item[aria-current="page"], .nav-more.is-current { background: var(--accent-soft); color: var(--accent-strong); }', shell)
        self.assertNotIn("border-bottom-color: var(--accent)", shell)
        self.assertIn(".nav-item:hover { background: var(--hover); }", _block(shell, "(hover: hover) and (pointer: fine)"))

    def test_the_ipad_in_portrait_caps_the_tabs_at_640_px(self):
        query = ("(min-width: 600px) and (max-width: 999px) and (min-height: 501px), "
                 "(min-width: 600px) and (max-width: 999px) and (orientation: portrait)")
        self.assertIn("padding-left: max(env(safe-area-inset-left), (100% - 640px) / 2);", _block(_css("shell.css"), query))

    def test_the_matchups_tab_dot(self):
        self.assertIn(".tab.has-run::after {", _block(_css("shell.css"), SHELL_CASUAL))
        self.assertIn('link.classList.toggle("has-run", runs.length > 0)', _function(_scripts(), "drawRunsPill"))


class DeckColourTests(unittest.TestCase):
    # E11-S30 slice 5: a deck's pips, stripe, tint and swatch (design/visual-design.md 4.3 and 2.2) come from one
    # helper and the deck-colour tokens, in both themes.
    COLOURS = "wubrgc"

    def themes(self):
        css = _css("tokens.css")
        light = dict(re.findall(r"(--[\w-]+):\s*([^;]+);", re.search(r"^:root \{(.*?)^\}", css, re.S | re.M).group(1)))
        dark = dict(re.findall(r"(--[\w-]+):\s*([^;]+);", re.search(r':root\[data-theme="dark"\] \{(.*?)\n\}', css, re.S).group(1)))
        return light, dark

    def test_every_colour_has_its_tokens_in_both_themes(self):
        light, dark = self.themes()
        for c in self.COLOURS:
            for name in (f"--stripe-{c}", f"--tint-{c}", f"--tint-{c}-deep", f"--art-{c}"):
                with self.subTest(token=name):
                    self.assertIn(name, light)
                    # The white stripe is light enough on the dark page already; every other one changes there.
                    if name != "--stripe-w":
                        self.assertIn(name, dark)
                        self.assertNotEqual(light[name], dark[name])
            # Dark tints are the dark stripes, translucent over --surface; the deep stop a little stronger.
            with self.subTest(colour=c):
                self.assertRegex(dark[f"--tint-{c}"], r"^rgb\(\d+ \d+ \d+ / \.16\)$")
                self.assertEqual(dark[f"--tint-{c}-deep"], dark[f"--tint-{c}"].replace(".16)", ".24)"))
        self.assertEqual(light["--tint-w-deep"], "#f8efd8")         # the spec's W example
        self.assertEqual((light["--tint-multi"], dark["--tint-multi"]), ("#f3f1ea", "var(--surface)"))
        self.assertIn("--art-multi", light)
        self.assertIn("--art-multi", dark)
        sizes = {name: light[name] for name in ("--pip-sm", "--pip-md", "--pip-lg", "--pip-xl", "--stripe-h", "--stripe-h-thin")}
        self.assertEqual(sizes, {"--pip-sm": "16px", "--pip-md": "20px", "--pip-lg": "22px", "--pip-xl": "24px",
                                 "--stripe-h": "5px", "--stripe-h-thin": "3px"})
        self.assertEqual(_tokens_on(IPHONE)["--swatch-h"], "12px")
        self.assertEqual(_tokens_on(MACBOOK)["--swatch-h"], "8px")

    def test_the_pieces_are_components(self):
        css = _css("components.css")
        pip = re.search(r"^\.id-pip \{(.*?)^\}", css, re.S | re.M).group(1)
        for part in ("border-radius: 50%", "color: var(--mana-ink)", "font-weight: var(--fw-heavy)",
                     "box-shadow: inset 0 0 0 1px var(--mana-ring)", "width: var(--pip)"):
            self.assertIn(part, pip)
        for c in self.COLOURS:
            self.assertIn(f".id-pip-{c} {{ --pip-fill: var(--mana-{c}); }}", css)
        self.assertIn(".id-pips.is-over-art .id-pip { box-shadow: var(--shadow-pip-art); }", css)
        self.assertIn(".deck-stripe.is-thin { height: var(--stripe-h-thin); }", css)
        self.assertIn(".deck-tint { background: var(--deck-tint), var(--surface); }", css)
        self.assertIn(".id-pip, .deck-stripe, .deck-swatch { forced-color-adjust: none; }", _block(css, "(forced-colors: active)"))

    def test_the_library_and_the_deck_head_use_the_helper(self):
        scripts = _scripts()
        self.assertIn("deckColourPieces(", _function(scripts, "libColours"))
        card = _function(scripts, "deckCard")
        self.assertIn("colours.stripe()", card)
        # The pips over the art's bottom-left corner (slice 8), on the tile, the detail pane and a row (16 px).
        self.assertIn('colours.pips(20, { overArt: true, cls: "deck-pips" })', _function(scripts, "deckCover"))
        self.assertIn("deckCover(d, colours)", card)
        self.assertIn('colours.pips(16, { cls: "deck-pips" })', _function(scripts, "deckRow"))
        head = _function(scripts, "deckHeader")
        self.assertIn("deckColourPieces(deckPageColours(data))", head)
        self.assertIn('colours.pips(22, { cls: "deck-head-pips" })', head)
        # Their own pip and wash code is gone: no mana colours or cost symbols for a deck's identity.
        for name in ("deckCard", "deckCover", "deckRow", "libDetail", "libColours", "deckHeader"):
            with self.subTest(function=name):
                self.assertNotRegex(_function(scripts, name), r"--mana-|symbolImg|colourPips")
        lib = _css("library.css")
        self.assertNotIn("--mana-", lib)
        # The stripe lies across the tile's top without becoming a flex item beside the cover (no layout
        # change), and the cover shows the art placeholder colour until its art loads.
        self.assertIn(".deck-card > .deck-stripe { position: absolute; inset: 0 0 auto; z-index: 1; }", lib)
        self.assertIn("position: relative", re.search(r"^\.deck-card \{(.*?)^\}", lib, re.S | re.M).group(1))
        self.assertIn(".deck-cover:not(.deck-tint) { background: var(--deck-art, var(--surface-3)); }", lib)
        # Four or five colours stay inside their space (checked in headless Chrome, 2026-10-25): five pips over a
        # tile's 112 px of art close up 4 px in, and a lab row's pips wrap under a name that leaves them no room
        # (the iPad's landscape list) rather than running over the owned column.
        self.assertIn(".deck-cover > .deck-pips:has(> .id-pip:nth-child(5))", lib)
        self.assertIn("{ left: var(--s-1); gap: 0; }", lib)
        self.assertIn("flex-wrap: wrap", _block_rule(lib, ".deck-row-title"))
        self.assertIn(".deck-row-title > .deck-title { flex: 0 1 auto; min-width: 0; }", lib)


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeckColourUiTests(unittest.TestCase):
    """ui.js deckColourPieces under Node: the colours from an identity, and each piece's markup and CSS."""

    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), scenario]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_two_colours(self):
        self.run_js("""
          const d = deckColourPieces(["R", "u", "R", "X"]);         // any order and case; unknown letters dropped
          same(d.colours, ["U", "R"]);
          assert.equal(d.label, "Colours: blue, red");
          const pips = d.pips(16);
          assert.equal(pips.getAttribute("class"), "id-pips id-pips-sm");
          assert.equal(pips.getAttribute("role"), "img");
          assert.equal(pips.getAttribute("aria-label"), "Colours: blue, red");
          same(pips.children.map((p) => [p.getAttribute("class"), p.textContent]),
            [["id-pip id-pip-u", "U"], ["id-pip id-pip-r", "R"]]);
          assert.equal(d.pips().getAttribute("class"), "id-pips id-pips-md");
          assert.equal(d.pips(22).getAttribute("class"), "id-pips id-pips-lg");
          assert.equal(d.pips(24, { overArt: true, cls: "x" }).getAttribute("class"), "id-pips id-pips-xl is-over-art x");
          assert.equal(d.pips(18).getAttribute("class"), "id-pips id-pips-md");
          const stripe = d.stripe();
          assert.equal(stripe.getAttribute("class"), "deck-stripe");
          assert.equal(stripe.getAttribute("aria-hidden"), "true");
          assert.equal(stripe.getAttribute("style"),
            "--deck-stripe: linear-gradient(90deg, var(--stripe-u) 0% 50%, var(--stripe-r) 50% 100%)");
          assert.equal(d.stripe(true).getAttribute("class"), "deck-stripe is-thin");
          const swatch = d.swatch();
          assert.equal(swatch.getAttribute("class"), "deck-swatch");
          assert.equal(swatch.getAttribute("aria-hidden"), "true");
          assert.equal(swatch.getAttribute("style"), stripe.getAttribute("style"));
          assert.equal(d.tint(), "linear-gradient(135deg, var(--tint-u), var(--tint-r))");
          assert.equal(d.tint(90), "linear-gradient(90deg, var(--tint-u), var(--tint-r))");
          assert.equal(d.art, "var(--art-u)");
          assert.equal(d.vars(90), "--deck-stripe: linear-gradient(90deg, var(--stripe-u) 0% 50%, var(--stripe-r) 50% 100%); " +
            "--deck-tint: linear-gradient(90deg, var(--tint-u), var(--tint-r)); --deck-art: var(--art-u)");
        """)

    def test_one_three_and_five_colours(self):
        self.run_js(r"""
          const mono = deckColourPieces(["G"]);
          assert.equal(mono.label, "Colours: green");
          assert.equal(mono.tint(), "linear-gradient(135deg, var(--tint-g), var(--tint-g-deep))");
          assert.equal(mono.stripe().getAttribute("style"), "--deck-stripe: linear-gradient(90deg, var(--stripe-g) 0% 100%)");
          const three = deckColourPieces(["G", "W", "B"]);
          same(three.colours, ["W", "B", "G"]);
          assert.equal(three.tint(), "linear-gradient(135deg, var(--tint-w) 0%, var(--tint-b) 55%, var(--tint-g) 100%)");
          assert.equal(three.stripe().getAttribute("style"), "--deck-stripe: linear-gradient(90deg, " +
            "var(--stripe-w) 0% 33.33%, var(--stripe-b) 33.33% 66.67%, var(--stripe-g) 66.67% 100%)");
          assert.equal(three.art, "var(--art-multi)");
          // Four or five: every colour in the stripe and the pips, but a neutral tint.
          const five = deckColourPieces(["G", "R", "B", "U", "W"]);
          assert.equal(five.label, "Colours: white, blue, black, red, green");
          assert.equal(five.pips().children.length, 5);
          assert.equal(five.tint(), "linear-gradient(135deg, var(--tint-multi), var(--tint-multi))");
          assert.equal(five.stripe().getAttribute("style").match(/var\(--stripe-/g).length, 5);
          assert(five.stripe().getAttribute("style").includes("var(--stripe-b) 40% 60%"));
          assert.equal(deckColourPieces(["W", "U", "B", "R"]).tint(), five.tint());
        """)

    def test_colourless_and_unknown(self):
        self.run_js("""
          const none = deckColourPieces([]);
          same(none.colours, ["C"]);
          assert.equal(none.label, "Colourless");
          const pips = none.pips();
          assert.equal(pips.getAttribute("aria-label"), "Colourless");
          same(pips.children.map((p) => p.textContent), ["C"]);
          assert.equal(pips.children[0].getAttribute("class"), "id-pip id-pip-c");
          assert.equal(none.tint(), "linear-gradient(135deg, var(--tint-c), var(--tint-c-deep))");
          assert.equal(none.stripe().getAttribute("style"), "--deck-stripe: linear-gradient(90deg, var(--stripe-c) 0% 100%)");
          assert.equal(none.art, "var(--art-c)");
          // Not known (no card could be read): nothing to draw.
          assert.equal(deckColourPieces(null), null);
          assert.equal(deckColourPieces(undefined), null);
          assert.equal(deckPageColours({ sections: { Deck: [{ name: "Unknown", card: null }] } }), null);
          same(deckPageColours({ sections: { Deck: [{ card: { color_identity: [] } }] } }), []);
          same(deckPageColours({ sections: { Commander: [{ card: { color_identity: ["G", "U"] } }],
            Deck: [{ card: { color_identity: ["R"] } }] } }), ["U", "G"]);
        """)


def _block_rule(css, selector):
    """The declarations of selector's own rule (the first rule written for exactly it)."""
    return re.search(r"^" + re.escape(selector) + r" \{(.*?)\}", css, re.M).group(1)


def _rule(css, selector):
    """The declarations of the rule whose selector is exactly this, at the start of a line."""
    found = re.search(rf"^{re.escape(selector)} \{{(.*?)\}}", css, re.S | re.M)
    assert found, selector
    return found.group(1)


class SimComponentTests(unittest.TestCase):
    # E11-S30 slice 6: Forge's result pieces (design/visual-design.md 4.9) are components.css's, in mono and ink,
    # with Forge's strong and weak colours only on flags and verdicts, and the run activity in place of the pill.
    def test_numbers_are_mono_and_never_coloured(self):
        css = _css("components.css")
        for selector in (".sim-num", ".wr-value", ".wr-range", ".range-axis", ".flag-rate", ".swap-qty", ".swap-points"):
            with self.subTest(selector=selector):
                self.assertIn("font-family: var(--font-mono)", _rule(css, selector))
        self.assertIn("color: var(--ink)", _rule(css, ".wr"))
        # Nothing of the figure, the range bar or the badge is the accent, green or red.
        figure = "\n".join(line for line in css.splitlines() if re.match(r"\.(wr|range|fresh)", line))
        self.assertNotRegex(figure, r"--accent|--strong|--weak|--win|--loss|--good|--crit")
        self.assertIn("background: var(--range-band)", _rule(css, ".range-band"))
        self.assertIn("background: var(--ink)", _rule(css, ".range-point"))
        self.assertIn("border-left: 1px dashed var(--ink-4)", _rule(css, ".range-even"))
        self.assertIn("--range-thick: var(--range-h-compact)", _rule(css, ".range-bar-compact"))
        # A tile's "Forge field" caption is 13 px (4.9), its own token rather than a meta line's 14.
        self.assertIn("font-size: var(--fs-wr-caption)", _rule(css, ".wr-caption"))
        self.assertIn("--fs-wr-caption: .8125rem;", _css("tokens.css"))

    def test_flags_and_verdicts_wear_forges_colours(self):
        css = _css("components.css")
        self.assertIn("background: var(--strong-soft); color: var(--strong-ink)", _rule(css, ".flag-strong"))
        self.assertIn("background: var(--weak-soft); color: var(--weak-ink)", _rule(css, ".flag-weak"))
        self.assertIn("min-height: var(--flag-h)", _rule(css, ".flag"))
        self.assertIn(".flag-weak .flag-chevron { transform: rotate(180deg); }", css)
        self.assertIn("background: var(--strong-soft); color: var(--strong-ink)", _rule(css, ".swap-verdict-better"))
        self.assertIn("background: var(--weak-soft); color: var(--weak-ink)", _rule(css, ".swap-verdict-worse"))
        self.assertIn("box-shadow: inset 0 0 0 1px var(--ink-4)", _rule(css, ".swap-verdict-likely-better, .swap-verdict-likely-worse"))
        self.assertIn("color: var(--weak-ink)", _rule(css, ".swap-remove"))
        self.assertIn("color: var(--strong-ink)", _rule(css, ".swap-add"))
        self.assertIn("color: var(--ink-3)", _rule(css, ".swap-lines.is-neutral > li"))
        # The verdict pill isn't .verdict, which is the deck page's stats tiles' (stats.css): every stylesheet
        # loads on every page.
        self.assertNotRegex(css, r"(?m)^\.verdict\b")
        self.assertIn("swap-verdict swap-verdict-", _text("sim-ui.js"))
        # The test page's difference bars and their axis words are Forge results too: Forge's strong and weak
        # colours, not --good/--crit; --win and --loss are only the matchup matrix's cells (2.1).
        variant = _css("variant.css")
        self.assertIn("--vt-c: var(--strong-ink)", _rule(variant, ".vt-diff-good"))
        self.assertIn("--vt-c: var(--weak-ink)", _rule(variant, ".vt-diff-crit"))
        self.assertIn("color: var(--weak-ink)", _rule(variant, ".vt-axis-worse"))
        self.assertIn("color: var(--strong-ink)", _rule(variant, ".vt-axis-better"))
        for sheet in sorted(WEB.glob("*.css")):
            with self.subTest(sheet=sheet.name):
                shaded = [line for line in _css(sheet.name).splitlines() if re.search(r"var\(--(win|loss)\)", line)]
                self.assertEqual([line for line in shaded if not (sheet.name == "matchups.css" and line.startswith(".mu-h-"))], [])

    def test_the_freshness_badge(self):
        css = _css("components.css")
        self.assertIn("min-height: var(--fresh-h)", _rule(css, ".fresh"))
        self.assertIn("background: var(--surface-chip)", _rule(css, ".fresh"))
        self.assertIn("min-height: var(--fresh-h-row)", _rule(css, ".fresh-row"))
        aging = _rule(css, ".fresh.is-aging, .fresh.is-stale, .fresh.is-unsaved")
        self.assertIn("background: var(--warn-soft); color: var(--warn-ink-sm)", aging)
        self.assertIn("box-shadow: inset 0 0 0 1px var(--warn-line)", aging)
        # A fresh one in a lab row (from 1,000 px, as --fresh-h-row's 17 px) is plain words, a casual one keeps its
        # pill; a stale one swaps the clock for the refresh icon.
        self.assertNotRegex(css, r"(?m)^\.fresh-row\.is-fresh")
        self.assertRegex(_block(css, "(min-width: 1000px)"), r"\.fresh-row\.is-fresh \{[^}]*background: none")
        self.assertIn("M16.2 10.4", _rule(css, ".fresh.is-stale .fresh-icon"))
        self.assertIn("background: var(--chip-on-tint)", _rule(css, ".fresh.on-tint"))
        tokens = _css("tokens.css")
        self.assertIn("--chip-on-tint: rgb(255 255 255 / .8);", tokens)
        self.assertIn("--chip-on-tint-line: rgb(20 40 38 / .14);", tokens)

    def test_the_run_activity(self):
        css = _css("components.css")
        button = _rule(css, ".run-activity")
        self.assertIn("width: var(--tap); height: var(--tap)", button)
        ring = _rule(css, ".activity-ring")
        self.assertIn("border-top-color: var(--accent)", ring)
        self.assertIn("animation: spin", ring)
        # Still under reduced motion: a whole ring with a dot.
        still = _block(css, "(prefers-reduced-motion: reduce)")
        self.assertIn(".activity-ring { animation: none; border-color: var(--accent); }", still)
        self.assertIn(".activity-ring::after {", still)
        # Touch gets :active; a mouse its hover.
        self.assertIn(".run-activity:active { background: var(--accent-soft); }", css)
        # Forced colours: the ring's arc stays apart from its track (else it looks still), one even ring when still,
        # and the badge's amber icon and a muted point are forced too, as specific as their own colours.
        forced = _block(css, "(forced-colors: active)")
        self.assertIn(".activity-ring { forced-color-adjust: none; border-color: GrayText; border-top-color: Highlight; }", forced)
        self.assertIn(".activity-ring { border-color: Highlight; }", _block(css, "(forced-colors: active) and (prefers-reduced-motion: reduce)"))
        self.assertIn(".fresh:is(.is-aging, .is-stale, .is-unsaved) .fresh-icon, .range-bar.is-muted .range-point { background: CanvasText; }", forced)
        self.assertIn("box-shadow: var(--shadow-2)", _rule(css, ".run-popover"))
        self.assertIn("background: var(--accent-soft); box-shadow: inset 0 0 0 1px var(--run-line)", _rule(css, ".run-entry"))
        self.assertIn("stroke: var(--ring-track)", _rule(css, ".run-ring-track"))
        self.assertIn("stroke: var(--accent)", _rule(css, ".run-ring-arc"))
        self.assertIn("width: var(--ring-size)", _rule(css, ".run-ring"))
        # The pill is gone, its slot holds only the icon, and the popover hangs from the slot.
        self.assertNotRegex(_css("matchups.css") + _css("components.css") + _css("shell.css"), r"\.runs-pill")
        self.assertIn("position: relative", _rule(_css("shell.css"), ".shell-status"))
        self.assertIn(".shell-status > .run-activity { display: none; }", _css("matchups.css"))
        self.assertNotRegex(_text("runs-pill.js"), r'class: "runs-pill|checkBar\(')


@unittest.skipUnless(NODE, "Node.js isn't installed")
class SimComponentUiTests(unittest.TestCase):
    """sim-ui.js under Node, with every script the page loads: each piece's markup, words and positions."""

    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), scenario, True]),
                                capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_the_win_rate_figure(self):
        self.run_js("""
          const rate = {value: 0.613, low: 0.588, high: 0.634};
          const inline = winRateFigure(rate, {what: "Forge field win rate", tested: "tested 3 days ago"});
          assert.equal(inline.getAttribute("class"), "wr wr-inline");
          assert.equal(inline.getAttribute("role"), "img");
          assert.equal(inline.getAttribute("aria-label"), "Forge field win rate 61 percent, range 59 to 63, tested 3 days ago");
          same(inline.children.map((c) => [c.getAttribute("class"), c.textContent]), [["wr-value", "61%"], ["wr-range", "59–63"]]);
          const tile = winRateFigure(rate, {size: "tile"});
          same(tile.children.map((c) => c.textContent), ["61%", "Forge field"]);
          const hero = winRateFigure(rate, {size: "hero", games: 3400, rank: {rank: 3, of: 11}});
          assert.equal(hero.tag, "div");
          assert.equal(hero.getAttribute("aria-label"), "Win rate 61 percent, range 59 to 63, 3,400 games, rank 3 of 11");
          assert.equal(hero.textContent, "61%59–63% 95% range3,400 games · rank 3 of 11");
          // Numbers mono, words not: the hero's lines put each number in its own .sim-num.
          const nums = hero.querySelectorAll(".sim-num").map((n) => n.textContent);
          same(nums, ["59–63%", "3,400", "3", "11"]);
          // Not known yet.
          const none = winRateFigure(null, {what: "Win rate against Elves"});
          assert.equal(none.textContent, "?");
          assert.equal(none.getAttribute("aria-label"), "Win rate against Elves not known yet");
        """)

    def test_the_range_bar(self):
        self.run_js("""
          const bar = rangeBar({value: 0.61, low: 0.59, high: 0.63});
          assert.equal(bar.getAttribute("class"), "range-bar");
          assert.equal(bar.getAttribute("role"), "img");
          assert.equal(bar.getAttribute("aria-label"), "Win rate 61 percent, range 59 to 63");
          const track = bar.children[0];
          same(track.children.map((c) => c.getAttribute("class")), ["range-even", "range-band", "range-point"]);
          // The fixed 20-80% scale: left = (value - 20) / 60.
          assert.equal(track.querySelector(".range-band").getAttribute("style"), "left: 65%; width: 6.67%");
          assert.equal(track.querySelector(".range-point").getAttribute("style"), "left: 68.33%");
          // Outside the scale: clamped to the end, and the words give the real value.
          const high = rangeBar({value: 0.91, low: 0.85, high: 0.95}, {compact: true});
          assert.equal(high.getAttribute("class"), "range-bar range-bar-compact is-clamped");
          assert.equal(high.querySelector(".range-point").getAttribute("style"), "left: 100%");
          assert.equal(high.querySelector(".range-band").getAttribute("style"), "left: 100%; width: 0%");
          assert(high.getAttribute("aria-label").startsWith("Win rate 91 percent, range 85 to 95, beyond"));
          // Beside a figure that says it, the bar is decorative, and the figure says when the bar clamps it.
          const quiet = rangeBar({value: 0.91, low: 0.85, high: 0.95}, {decorative: true});
          assert.equal(quiet.getAttribute("aria-hidden"), "true");
          assert.equal(quiet.getAttribute("role"), null);
          assert.equal(quiet.getAttribute("aria-label"), null);
          assert.equal(winRateFigure({value: 0.91, low: 0.85, high: 0.95}, {barred: true}).getAttribute("aria-label"),
            "Win rate 91 percent, range 85 to 95, beyond the bar's 20 to 80 percent scale");
          assert.equal(winRateFigure({value: 0.61, low: 0.59, high: 0.63}, {barred: true}).getAttribute("aria-label"),
            "Win rate 61 percent, range 59 to 63");
          const low = rangeBar({value: 0.12, low: 0.05, high: 0.22});
          assert.equal(low.querySelector(".range-point").getAttribute("style"), "left: 0%");
          // The axis, a live run's band, a result that means nothing (no band), and no result.
          const axis = rangeBar({value: 0.5, low: 0.45, high: 0.55}, {axis: true, live: true});
          assert.equal(axis.getAttribute("class"), "range-bar is-live");
          assert.equal(axis.querySelector(".range-axis").textContent, "205080");
          assert.equal(axis.querySelector(".range-axis").getAttribute("aria-hidden"), "true");
          const muted = rangeBar({value: 0.5, low: 0.4, high: 0.6}, {muted: true});
          assert.equal(muted.querySelector(".range-band"), null);
          const empty = rangeBar(null, {what: "Gruul's win rate"});
          same(empty.children[0].children.map((c) => c.getAttribute("class")), ["range-even"]);
          assert.equal(empty.getAttribute("aria-label"), "Gruul's win rate not known yet");
          assert(rangeKey().textContent.includes("50% win rate"));
        """)

    def test_the_freshness_badge(self):
        self.run_js("""
          const now = new Date(2026, 9, 25, 9, 0).getTime();
          const badge = (days, opts = {}) => freshnessBadge(new Date(2026, 9, 25 - days, 23, 30), {now, ...opts});
          const fresh = badge(3);
          assert.equal(fresh.getAttribute("class"), "fresh fresh-panel is-fresh");
          assert.equal(fresh.getAttribute("role"), "img");
          assert.equal(fresh.textContent, "tested 3 days ago");
          assert.equal(fresh.getAttribute("aria-label"), "Tested 3 days ago, on 22 October 2026");
          assert.equal(fresh.children[0].getAttribute("aria-hidden"), "true");
          assert.equal(badge(0).textContent, "tested today");
          assert.equal(badge(1).textContent, "tested yesterday");
          assert.equal(badge(7).getAttribute("class"), "fresh fresh-panel is-fresh");
          const aging = badge(8, {size: "row", compact: true});
          assert.equal(aging.getAttribute("class"), "fresh fresh-row is-aging");
          assert.equal(aging.textContent, "8 days ago");
          assert.equal(badge(30).getAttribute("class"), "fresh fresh-panel is-aging");
          const stale = badge(41);
          assert.equal(stale.getAttribute("class"), "fresh fresh-panel is-stale");
          assert.equal(stale.textContent, "retest: 5 weeks ago");
          assert(stale.getAttribute("aria-label").endsWith(": worth testing again"));
          const changed = badge(2, {changed: true, size: "casual", onTint: true});
          assert.equal(changed.getAttribute("class"), "fresh fresh-casual is-stale on-tint");
          assert.equal(changed.textContent, "retest: changed since");
          assert.equal(changed.getAttribute("aria-label"), "Tested on 23 October 2026; the list has changed since, so test it again");
          // The editor's result for the saved list, with or without a date.
          const unsaved = freshnessBadge(null, {unsaved: true, now});
          assert.equal(unsaved.getAttribute("class"), "fresh fresh-panel is-unsaved");
          assert.equal(unsaved.textContent, "for the saved list");
          // Any other dated check: prices pulled on a day, a shop checked, "check again" once stale.
          assert.equal(badge(1, {verb: "pulled", byDate: true}).textContent, "pulled 24 Oct");
          assert.equal(badge(3, {verb: "checked"}).textContent, "checked 3 days ago");
          assert.equal(badge(60, {verb: "checked"}).textContent, "check again");
          assert.equal(freshnessBadge(new Date(2025, 11, 30), {verb: "pulled", byDate: true, now: new Date(2026, 0, 6).getTime()})
            .textContent, "pulled 30 Dec 2025");      // another year than now's: with its year
          // Shown only when there's a date, or the list has changed since (a result without a date still says so).
          assert.equal(freshnessBadge(null, {now}), null);
          const undated = freshnessBadge(null, {changed: true, size: "row", compact: true, now});
          assert.equal(undated.getAttribute("class"), "fresh fresh-row is-stale");
          assert.equal(undated.textContent, "retest: changed since");
          assert.equal(undated.getAttribute("aria-label"), "The list has changed since it was tested, so test it again");
          assert.equal(freshnessBadge("not a date", {now}), null);
          assert.equal(freshnessBadge("2026-10-22T13:05:12", {now}).textContent, "tested 3 days ago");
          same([0, 1, 13, 30, 31, 89, 90, 400, 800].map(ageWords),
            ["today", "yesterday", "13 days ago", "30 days ago", "4 weeks ago", "12 weeks ago", "3 months ago", "a year ago", "2 years ago"]);
        """)

    def test_flags(self):
        self.run_js("""
          const strong = forgeFlag("strong", {name: "Izzet Otters", rate: {value: 0.64}});
          assert.equal(strong.getAttribute("class"), "flag flag-strong");
          assert.equal(strong.textContent, "Strong against Izzet Otters64%");
          assert.equal(strong.querySelector(".sr-only").textContent, "Strong against ");
          assert.equal(strong.children[0].getAttribute("aria-hidden"), "true");
          const weak = forgeFlag("weak");
          assert.equal(weak.getAttribute("class"), "flag flag-weak");
          assert.equal(weak.textContent, "weak against");
          assert.equal(forgeFlag("weak", {short: true}).textContent, "weak");
        """)

    def test_a_swap_test_result(self):
        self.run_js("""
          const changes = {remove: [[1, "Abrade"]], add: [[1, "Burst Lightning"]]};
          const r = swapResult({changes, delta: 0.031, low: -0.004, high: 0.066, games: 600});
          same(r.querySelectorAll("li").map((li) => [li.getAttribute("class"), li.textContent]),
            [["swap-remove", "−1 Abrade"], ["swap-add", "+1 Burst Lightning"]]);
          assert.equal(r.querySelector(".swap-figure").textContent, "+3.1 points");
          assert.equal(r.querySelector(".swap-verdict").getAttribute("class"), "swap-verdict swap-verdict-likely-better");
          assert.equal(r.querySelector(".swap-verdict").textContent, "probably better, not proven");
          assert.equal(r.querySelector(".swap-range").textContent, "−0.4 to +6.6 · 600 paired games");
          same(r.querySelector(".swap-range").querySelectorAll(".sim-num").map((n) => n.textContent), ["−0.4", "+6.6", "600"]);
          const pill = (d, lo, hi, verdict) => swapResult({delta: d, low: lo, high: hi, verdict}).querySelector(".swap-verdict").textContent;
          assert.equal(pill(0.03, 0.01, 0.05), "better");
          assert.equal(pill(-0.03, -0.05, -0.01), "worse");
          assert.equal(pill(-0.01, -0.03, 0.01), "probably worse, not proven");
          assert.equal(pill(0.0002, -0.01, 0.01), "no clear difference");
          assert.equal(pill(0.01, 0.002, 0.02, "little_difference"), "no clear difference");
          assert.equal(swapResult({changes}).querySelector(".swap-verdict"), null);
          assert.equal(swapResult({changes, neutral: true}).querySelector(".swap-lines").getAttribute("class"), "swap-lines is-neutral");
          // The deck page's list of tests uses it, with how long ago each played.
          const item = vtTestItem({test: "t1", changes, against: "field", verdict: "better", delta: 0.031, low: 0.012,
            high: 0.05, games_per_opponent: 400, when: "2026-10-20T10:00:00", saved: false, running: false});
          assert(item.querySelector(".swap-result"));
          assert.equal(item.querySelector(".swap-verdict").textContent, "better");
          assert(item.querySelector(".swap-range").textContent.endsWith("against the field · 400 games a deck"));
          assert(item.querySelector(".fresh"));
        """)


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeviceLayoutUiTests(unittest.TestCase):
    def run_js(self, scenario):
        result = subprocess.run([NODE, str(RUNNER)], input=json.dumps([str(WEB), scenario]),
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "ok")

    def test_which_editor(self):
        # A phone on its side (a touch screen 500 px tall or less) gets the Quick edit like an upright one; a
        # tablet either way round, and any screen with a mouse from 600 px, gets the full editor.
        self.run_js("""
          const wide = window.matchMedia("(min-width: 600px)");
          const shortTouch = window.matchMedia("(pointer: coarse) and (max-height: 500px)");
          wide.matches = false; shortTouch.matches = false;
          assert.equal(canBuildDecks(), false);
          assert.equal(quickEditing(), true);
          wide.matches = true; shortTouch.matches = true;        // iPhone on its side, 852 x 330
          assert.equal(canBuildDecks(), false);
          wide.matches = true; shortTouch.matches = false;       // iPad, MacBook, QHD; or a short window with a mouse
          assert.equal(canBuildDecks(), true);
          assert.equal(quickEditing(), false);
        """)


if __name__ == "__main__":
    unittest.main()
