# Deck Lab: visual design (P1)

The look Deck Lab's pages are moving to, and how to get there from today's UI kit without a rewrite.

- **Decided:** 2026-10-24, by Matt: "P1, split lab + mana decks".
- **Written:** 2026-10-24, after a validation round that drew P1 on the hardest screens.
- **Covers:** colours, type, sizes, the phone/desktop switch, the shared components, what each hard page needs, what's still open, and the order to build it in.
- **Doesn't replace:** [UI-KIT.md](../UI-KIT.md) (how the CSS and JS are organised, and its rules, which still hold unless this page says otherwise) and [UI-REVIEW.md](../UI-REVIEW.md) (the reasons for the 2026-10-13 redesign). When a slice below ships, update UI-KIT.md in the same commit.
- **Drawings:** on a private design canvas, not in the repo. Every number on them (win rates, ranges, game counts, prices, copies) is mock data. Nothing here is a real Forge result.

## 1. What P1 is and why

P1 is one design system at two densities.

- **Casual, on the phone (and the iPad in portrait).** Decks are tiles tinted in their mana colours, with art on the left, a colour stripe across the top and pips on the art. Big type, 44 px targets, words for counts ("60 of 60 owned"). This is User1's Deck Lab: pick a deck, see it's ready, play.
- **Lab, on the desktop (and the iPad in landscape).** A pro tool: a top bar, dense rows, a list on the left and the selected thing's detail on the right, mono numerals, keyboard hints. This is where Matt builds, shops, receives and tests.
- **Simulations are the edge.** What Deck Lab has that a spreadsheet or Moxfield doesn't is Forge. Win rates, ranges, freshness and swap tests have their own components, look the same at both densities and are always set in mono.

The two densities share every token and every component name. Only sizes, layout and how much is shown change.

How it was chosen: three rounds of concepts on the canvas. Twelve first ideas (c01 to c12), then four variants each of the three Matt liked (v1, v5, v8), then three pairings of a phone look with a desktop look (P1 to P3), each drawn as library, deck page and Matchups at both sizes. P1 pairs v5d's phone (mana-tinted decks, teal actions, warm paper page) with v8d's desktop (master-detail lab). v8d's dark lab was dropped: the mana tints only read on light, and the lab reads as "pro" through density, not darkness. Light and dark both remain a user setting.

The validation round then drew P1 on Collection, Shopping, Receive delivery, the deck editor and the Packing plan (Build decks), at both sizes, plus the library and deck page in dark mode and on the iPad in both orientations. Reviewers checked each pair against the spec, fixed small problems in place and listed what didn't hold. Sections 4 to 6 are what came out of it.

### Rules that don't change

- **Teal means "you can do something" or "this is selected, yours, owned or done".** Nothing else is teal. Deck colour (stripes, tints, curve bars, swatches) belongs only to decks. Forge's strong and weak colours belong only to Forge results. Warn amber is for "look at this".
- **One primary per view region.** As UI-KIT.md says.
- **Nothing sums money.** Prices are dated estimates for one card or one row. No basket, shop, order or collection totals, no budgets, no free-postage progress bars.
- **Nothing is loaded from the internet.** The drawings use Google Fonts; the real page self-hosts (section 2.2).
- **Never colour alone.** Every state has a word or an icon too. Every pip group, stripe and badge has a spoken label or is `aria-hidden` beside words that say it.

## 2. Tokens

All values go in `tokens.css`. The light theme is in `:root`, the dark theme once in `:root[data-theme="dark"]` (never `prefers-color-scheme`, as now). Where a P1 role matches an existing token, the existing name is kept and its value changes. New tokens follow the same `--kebab` style.

### 2.1 Colours

| P1 role | Token | Light | Dark | Today's light value | Use |
|---|---|---|---|---|---|
| page | `--page` | `#f1f0ec` | `#121614` | `#f1f0ec` | body, the desktop detail pane, the phone page |
| surface | `--surface` | `#ffffff` | `#1a1f1d` | same | top bar, list pane, panels, tab bar, sheets |
| surface-sunken | `--surface-2` | `#f6f5f1` | `#161a19` | `#f7f6f3` | table headers, search fields, row hover (light) |
| hover (new) | `--hover` | `#f6f5f1` | `#222826` | | row hover; in dark it's raised, not sunken, so it doesn't read as pressed |
| surface-chip (new) | `--surface-chip` | `#efeee9` | `#252b29` | | desktop segmented track, neutral badges, kbd, finish pill, no-image frames |
| track (new) | `--track` | `#e6e4de` | `#2c3331` | | phone segmented track, disabled primary fill, colourless pip (see 4.3) |
| (kept) | `--surface-3` | `#e4e2dc` | `#36363b` → `#2c3331` | `#e4e2dc` | owned-bar track, the land chart band |
| border | `--border` | `#e2e0d9` | `#2c3331` | `rgb(0 0 0 / .12)` | panel and bar borders |
| border-strong | `--border-strong` | `#d8d6ce` | `#3a4240` | `rgb(0 0 0 / .24)` | buttons, inputs, kbd, steppers, chart baselines |
| divider (new) | `--divider` | `#ebe9e3` | `#252b29` | | lines between table rows and groups |
| rule (new) | `--rule` | `#dcdad2` | `#2c3331` | | phone section-heading hairline |
| ink | `--ink` | `#1c211f` | `#e9ecea` | `#161616` | text, win-rate figures, range-bar point |
| ink-2 | `--ink-2` | `#3d4542` | `#c3c9c6` | `#46453f` | secondary text, nav links, meta on tints |
| ink-3 | `--ink-3` | `#565e5a` | `#9aa29e` | `#6f6e68` | tertiary text, counts, axis labels. 5.9:1 on page, 6.6:1 on white. **Now usable for text** (today it's decoration only); never go lighter for text |
| ink-4 (new) | `--ink-4` | `#8a918d` | `#6b7470` | | non-text only: the 50% tick, neutral outlines, empty-image glyphs |
| accent | `--accent` | `#0f6e6a` | `#4fbdb5` | `#0f6e6a` (dark `#4cc2b8`) | primary fill, selected segment, current tab, badges, owned bars, ticks, focus ring |
| accent-strong (new) | `--accent-strong` | `#0b5552` | `#7fd4cd` | | text on accent-soft, secondary button text, avatar fallback |
| on-accent | `--accent-ink` | `#ffffff` | `#06201f` | same light | text on accent. In dark it's near-black (7.5:1), not white |
| accent-soft | `--accent-soft` | `#e1efec` | `rgb(79 189 181 / .14)` | `#e2f1ef` | current nav pill, selected row, run details |
| selected border (new) | `--accent-line` | `rgb(15 110 106 / .5)` | `rgb(79 189 181 / .55)` | | the 1 px border of a selected row or chip |
| accent-track (new) | `--accent-track` | `#d3e2df` | `rgb(79 189 181 / .24)` | | owned-bar track inside a selected row |
| ring-track (new) | `--ring-track` | `#bcd8d4` | `#2f5a56` | | run-progress ring track |
| link | `--link` | `#0a504d` | `#7fd4cd` | `#1c5cab` | links. P1 has no blue links; `--info-*` stays blue for the info pills only (info notices are amber, 4.5) |
| focus | `--focus` | accent | accent | same | 3 px halo `rgb(15 110 106 / .18)` around a focused field, 3 px solid outline for `:focus-visible` |
| warn-bg | `--warn-soft` | `#fbf3e2` | `rgb(240 180 76 / .10)` | `#fdf3dc` | notices, aging badges, "needs attention" pills |
| warn-border (new) | `--warn-line` | `#efdcb4` | `rgb(240 180 76 / .30)` | | their inset 1 px ring |
| warn-ink | `--warn-ink` | `#4d3500` (small text `#6b4500`) | `#f3d9a6` | `#8a5300` | text on warn-bg. Add `--warn-ink-sm: #6b4500` |
| warn-icon (new) | `--warn-icon` | `#8a5600` | `#e9b45a` | | icons on warn-bg, a dashed "check this" outline |
| warn-text (new, slice 2) | `--warn-text` | `#7a4c00` | `#e9b45a` | | amber warning words straight on a surface (7.3:1 on white, 8.9:1 on dark `--surface`) |
| building-ink (new) | `--building-ink` | `#7a4c00` | `#e9b45a` | | the Building group heading, Waiting rows, "keep with its cards" |
| missing (new) | `--missing` | `#a33a2e` | `#ff9a8a` | | "9 to buy" text only |
| strong (new) | `--strong-soft` / `--strong-ink` | `#e3f1e6` / `#1d6b3a` | `rgb(127 211 154 / .14)` / `#7fd39a` | | Forge "strong against", "+1" in a swap, verdict "better" |
| weak (new) | `--weak-soft` / `--weak-ink` | `#fbe9e6` / `#9b2f22` | `rgb(255 154 138 / .14)` / `#ff9a8a` | | Forge "weak against", "−1" in a swap, verdict "worse", destructive text buttons |
| range-band (new) | `--range-band` | `rgb(28 33 31 / .22)` | `rgb(233 236 234 / .30)` | | 95% band on a range bar |
| range-track (new) | `--range-track` | `#ebe9e3` | `#2c3331` | | range bar track |

The existing `--good-*` and `--crit-*` stay for statuses that aren't Forge (a tick's done state, a broken deck rule), so "red only for what stops a deck being played" still holds. `--win` and `--loss` are for the matchup matrix's diverging cells only; a win-rate figure is never coloured (section 4.7).

Dark notes: shadows don't read on near-black, so surfaces and borders do the lifting (as now). Card images get a 1 px `rgb(255 255 255 / .08)` ring plus `0 4px 14px rgb(0 0 0 / .55)`. Badge and dot rings on the tab bar use `--surface`, not white. White icon buttons over art become `rgb(26 31 29 / .86)` with a 1 px `rgb(255 255 255 / .14)` ring and `--accent-strong` glyphs. Set `color-scheme: dark` (already done) so native inputs and scrollbars follow.

### 2.2 Mana colours

The pip fills are today's `--mana-*` and don't change between themes. Stripes and tints are new, and the stripes are lighter in dark: the light B stripe is about 1.9:1 on the dark page and disappears. (This reverses the first spec's "stripes identical in both themes"; the dark drawings showed it doesn't work.)

| Colour | Pip fill (`--mana-x`) | Stripe light (`--stripe-x`) | Stripe dark | Tint light (`--tint-x`) | Art placeholder |
|---|---|---|---|---|---|
| W | `#fffbd5` | `#e2c472` | `#e2c472` | `#fcf6e6` | `#f3ead2` / dark `#332d1f` |
| U | `#aae0fa` | `#2f7fbf` | `#4a97d6` | `#e8f1f8` | `#d9e6f0` / dark `#1f2a33` |
| B | `#cbc2bf` | `#5a4f4b` | `#8c7f7a` | `#efecea` | `#e3dfdc` / dark `#232833` |
| R | `#f9aa8f` | `#d9473e` | `#e5594f` | `#fbeceb` | `#efe3d0` / dark `#33291f` |
| G | `#9bd3ae` | `#1f8a55` | `#2fa86a` | `#e7f3ec` | `#dbe9df` / dark `#1f2e25` |
| C (colourless) | `#ccc2c0` (`--mana-c`, kept) | `#8f8a85` | `#a39e99` | `#eeedea` | `#e6e4de` / dark `#252b29` |

The colourless stripe and tint were not drawn; they're proposed here so a colourless deck (or a land-only list) has something. Placeholders for colour pairs come from the first colour's row; the drawings also used U-R `#d9e6f0`, R-W `#efe3d0`, G-W `#dbe9df` and, in dark, U-R `#1f2a33`, R-W `#33291f`, G-W `#1f2e25`, U-B `#232833`, R-G `#2b2b1f`, B-G `#232a22`, three colours `#26272c`.

Pip letters are `--mana-ink` in both themes. Pip ring: light `inset 0 0 0 1px rgb(28 33 31 / .22)`, dark `rgb(0 0 0 / .28)`. Rules for tints and stripes with three or more colours are in 4.3.

### 2.3 Type

Two families:

- **Figtree** (400, 500, 600, 700, 800): all UI text, headings, buttons, pip letters.
- **JetBrains Mono** (400, 500, 600, 700): numbers that are data.

**Self-hosting (a build task).** Deck Lab loads nothing from the internet, so the fonts are files in the repo:

1. Put both families' variable `.woff2` files (and Figtree's italic) in `decklab/web/fonts/`, with their SIL Open Font Licence texts in `decklab/fonts-licences/` (the server serves only `.woff2` from `web/fonts/`) and the licence kept in each file's name table.
2. Subset to Latin and Latin-1 plus the punctuation Deck Lab prints: en dash, real minus `U+2212`, middle dot, `×`, `→`, `…`, curly quotes. That keeps each file to tens of kilobytes.
3. Declare them with `@font-face` in `base.css` (`font-display: swap`), and preload Figtree's upright face in `index.html`. JetBrains Mono gets its preload in the first slice that puts mono numbers in a page's first view (slice 3 or 6); until then it loads when first used.
4. The server sends `.woff2` as `font/woff2` with `Cache-Control: no-cache` and an ETag, like CSS and JS, but without the `?v=` stamp: `base.css`'s `url()` isn't rewritten, so a stamped preload wouldn't match it and the font would be fetched twice.
5. `--font: "Figtree", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif` and `--font-mono: "JetBrains Mono", ui-monospace, "Cascadia Mono", Consolas, monospace`. If a file fails, the page falls back to today's fonts and nothing breaks.

**Which numbers are mono.**

- **A Forge number is always mono**, at both densities: win rate, range, games, rank, points, "game 37 of 200".
- **Lab density** also uses mono for counts (`60 / 60`, filter counts, `13 decks`), quantities, deck ids (`casual/izzet-otters`), dates in meta lines, condition and language codes, table money (`Ref AUD` columns) and `kbd` hints.
- **Casual density** uses Figtree for counts, with `font-variant-numeric: tabular-nums` where they line up, and mono only for Forge numbers.
- **Words are never mono**, even in a mono line: deck names, "basic land", "Planned", "Done" are Figtree beside their mono numbers.
- **Printings stay in the body font** ("FDN 227"), with tabular numbers, at both densities. This keeps UI-KIT.md's existing rule; the collection and editor drawings set them in mono, and the receipt review moved them back. A printing is a name, not a measured number.
- Ranges use an en dash (`59–63%`), negatives the real minus (`−0.4`, `−1 Abrade`).

**Scale.** UI-KIT's "only tokens" rule stays, so the per-density sizes are semantic tokens set in `:root` and changed once at the switch (section 3). Today's `--fs-xs` to `--fs-2xl` keep working; the new names are what P1 pages use.

| Role | Token | Casual (< 1000 px) | Lab (≥ 1000 px, fine pointer) |
|---|---|---|---|
| Page title | `--fs-h1` | 32 / 800 / −0.03em | 22 / 800 / −0.025em |
| Hero deck name | `--fs-hero` | 32 / 800 | 30 / 800 / −0.03em, white on art |
| Panel eyebrow | `--fs-eyebrow` | 13 / 800 / .08em uppercase | 11 / 800 / .08em uppercase, `--accent-strong` |
| Group heading | `--fs-group` | 13 / 800 uppercase | 11 / 800 uppercase, mono count 11 |
| Body | `--fs-body` | 16 | 13, line-height 1.4 |
| Row or tile title | `--fs-row` | 17 / 700 | 14 / 700 |
| Meta | `--fs-meta` | 14, `--ink-2` | 12, `--ink-3` |
| Button | `--fs-btn` | 15–16 / 700 | 12.5–13 / 700 |
| Table header | `--fs-th` | (no tables) | mono 10.5 / 600 / .07em uppercase, `--ink-3` |
| Progress figure | `--fs-fig-mid` | 24 / 600 | mono 28 / 600 (Packing plan's `19 / 39`) |
| Big win rate | `--fs-fig` | mono 40 / 600, "%" 24 | mono 36 / 600 / −0.04em, "%" 22 |
| Inline win rate | `--fs-fig-sm` | mono 16 / 600 | mono 13 / 600, range 10.5 / 500 `--ink-2` |

10.5 px is only for uppercase table headers and `kbd`. Nothing else people read goes below 11 px at lab density or 14 px at casual density.

### 2.4 Spacing

The 4 px grid (`--s-1` to `--s-8`) stays. P1 adds:

- `--gutter`: 16 under 600 px, 24 from 600 px (as now). The iPad gets 24 in both orientations. Lab panes: list pane `--gutter-list: 20px`, detail pane 24.
- Common gaps: lab 8 / 12 / 16 / 20, casual 8 / 12 / 16. The drawings' 14 px phone gaps snap to 12.
- Lab list rows: 54 px, 2 px apart, pane padding 4 / 8. Lab table rows: 36 px (44 on a coarse pointer). Packing rows: 46 px. Receipt rows: 44 px.
- Casual tiles: at least 104 px, 112 with a Forge line, 12 apart.

### 2.5 Radii

| Token | Casual | Lab | Use |
|---|---|---|---|
| `--r-pill` | 999 | 999 | buttons, segmented controls, chips, pills, search fields, steppers |
| `--r-panel` (new) | 14 | 8 | panels, cards, notices, sheets' top corners on a phone |
| `--r-row` (new) | 8 | 8 | selected rows, menus |
| `--r-field` (new) | 12 | 8 | selects and plain text inputs |
| `--r-sm` | 6 → 4 | 4 | art thumbnails |
| `--r-card` | 4.75% / 3.4% | same | a card's picture |

Buttons become fully round. Today they use `--r-md` (10 px); `--r-md` stays for anything not yet moved over.

### 2.6 Elevation

| Token | Light | Dark |
|---|---|---|
| `--shadow-1` (tiles) | `0 1px 2px rgb(20 40 38 / .08), 0 0 0 1px rgb(20 40 38 / .09)` | `0 0 0 1px rgb(255 255 255 / .06)` (the ring is left out until tiles lose their borders, slice 2's note in section 7) |
| `--shadow-2` (menus, the activity popover, sheets) | `0 6px 18px rgb(20 40 38 / .18)` | `0 8px 24px rgb(0 0 0 / .6)` |
| `--shadow-up` (bars stuck to the bottom) | `0 -4px 14px rgb(20 40 38 / .07)` | `0 0 transparent` (border only) |
| `--shadow-img` (card pictures) | `0 2px 8px rgb(20 40 38 / .22)` | ring + `0 4px 14px rgb(0 0 0 / .55)` |
| `--shadow-img-sm` (new, thumbnails in rows) | `0 1px 3px rgb(20 40 38 / .25)` | ring + `0 2px 6px rgb(0 0 0 / .5)` |
| `--shadow-primary` (new) | `0 1px 2px rgb(15 110 106 / .35)` | none |

Lab panels use a 1 px `--border`, not a shadow, in both themes.

## 3. The density switch

### 3.1 What changes at 1000 px

The switch is the existing 1000 px step of UI-KIT's breakpoint ladder. No new breakpoints.

| | Casual (< 1000 px) | Lab (≥ 1000 px) |
|---|---|---|
| Navigation | 60 px header + 78 px bottom tab bar (Decks, Collection, Shopping, Matchups, More) | 56 px top bar: brand, round nav pills, activity icon, search, avatar |
| Layout | one column, page scroll | master-detail: list pane + detail pane (4.6) |
| Lists | tiles or rows inside one white panel | dense rows or a real table |
| Selection | tap opens the thing's page | click selects and fills the detail pane; Enter or "Full page" opens it |
| Numbers | words, mono only for Forge | mono for counts, ids, dates, codes |
| Charts | tall bars, generous labels | compact bars, mono labels, axis ticks |

Before slice 7 the tab bar was only under 600 px and 600–999 px got the top bar. P1 moved the tab bar up to 999 px (decided by Matt, 2026-10-24: a tablet in portrait looks like the phone; in landscape it gets the full top bar). That was a shell change (slice 7, built 2026-10-25) and changed the tablet's chrome; `--shell-bottom` follows it, and a phone on its side keeps the top bar.

The drawings also had a 760 px step inside the lab layout (hide columns, `kbd` and the Forge column). In the real page, anything under 1000 px is casual, so those rules only matter for a lab pane that's narrow inside a wide window; treat them as container widths, not page breakpoints.

### 3.2 The iPad

- **Portrait (820 × 1106): casual.** Tiles 2 across (`repeat(2, minmax(0, 1fr))`, gap 12, about 380 px each); tile insides stay exactly as on the phone. Rows of tiles stretch to the taller tile, so a tile with a Forge line and one without line up. The header's search icon becomes a real 300 × 44 px search field (16 px text, so iOS doesn't zoom). The tab bar is capped at 640 px wide, centred, with 12 px labels. The floating run pill is capped at about 560 px, centred. Filter rows get a fixed-width segmented control (400 px) instead of `flex: 1`.
- **Landscape (1180 × 746): lab layout, touch-sized.** Lab layout because the width is there; touch sizes because there's no mouse. This is a third level, not a new layout: every control 44 px, button labels 15 / 700, body 14, mono table numbers 14, flags 26 px, rows 44 px and whole-row links, no `kbd`, no hover, `:active` in `--accent-soft`. Panels keep the lab's 8 px radius and 1 px borders.
- The full editor stays available from 600 px (`canBuildDecks()`), so the iPad in portrait gets the editor's stacked panes inside the casual shell.

### 3.3 Pointer, hover and keyboard hints

- Control sizes follow the pointer, as `tokens.css` already does with `--ctl-h`: 44 px on a coarse pointer at any width. With a fine pointer: 36–38 px under 1000 px (today's step), 28–34 px at lab density (`--ctl-h: 32px`, segmented 28, `--field-h: 32px`).
- Every control and row on a lab page also has `@media (pointer: coarse) { min-height: 44px; min-width: 44px }`. The receipt drawing added this by hand; it belongs in `components.css` once, for every page.
- Hover states and `kbd` hints show only under `@media (hover: hover) and (pointer: fine)`. A touch screen never shows `kbd`, even at lab width.
- One `/` target per page: the global search owns `/`. A page's own list search uses `F`.

## 4. Components

Same name and same look at both densities; only size changes. Each lives in `components.css` or `cards-ui.css` and is styled once, as UI-KIT says.

### 4.1 Deck tile (casual)

- White tile, `--r-panel` 14, `--shadow-1`. A 5 px colour stripe across the top. Art on the left, 112 px wide and the tile's full height, on its art placeholder colour while loading, with the pips overlaid at its bottom-left.
- The rest of the tile is the deck's tint gradient (135deg). Name 17 / 700; meta 14 `--ink-2`; status pill; the owned bar with words ("87 owned · 4 on the way · 9 to buy"); if tested, a Forge line (win rate mono 16 / 600, "Forge field", freshness badge 24 px).
- The whole tile is one link to the deck page. No "not tested" line when there's no result.
- At least 104 px tall, 112 with a Forge line.

### 4.2 Deck row (lab)

- 54 px, `--r-row` 8, 2 px apart. A 56 × 38 art thumbnail with a 3 px stripe on its bottom edge; name 14 / 700 and meta 12 `--ink-3`; 16 px pips; the owned bar with mono text (`87 +4 … 9 to buy`: `+4` in `--accent-strong`, "to buy" in `--missing`); the Forge field column (inline win rate, range, freshness).
- Hover `--hover`. Selected: `--accent-soft` with a 1 px `--accent-line` border, owned-bar track `--accent-track`.
- Rows grouped under Built, Building and Ideas headings (11 / 800 uppercase, mono count). Built heading `--accent-strong`, Building `--building-ink`, Ideas `--ink-2`. Rows omit the status pill; the heading says it.
- A casual deck with no field result shows `—` in `--ink-3`; a Commander deck leaves the cell blank.

### 4.3 Mana pips, identity stripe, tint and deck swatch

- **Pip:** a circle in `--mana-x`, letter `--mana-ink` Figtree 800, ring as in 2.2. Sizes 16 (lab row, letter 9), 20 (lab hero band, casual tile, the collection preview; letter 10), 22 (casual deck hero, letter 11), 24 (filter toggle buttons). Over art: `0 0 0 2px #fff, 0 2px 4px rgb(0 0 0 / .3)` instead of the inset ring. The group is `role="img"` with `aria-label="Colours: blue, red"`. WUBRG order.
- **Colourless:** a `C` pip in `--mana-c` with the same ring. Used for a colourless card's identity and a colourless deck.
- **Pips are for colour identity only.** A card's cost is drawn with `manaCost()` symbols, as now.
- **Stripe:** equal segments in `--stripe-x`, no gaps, WUBRG order, always `aria-hidden` (the pips carry the meaning). 5 px over a tile or hero, 3 px under a thumbnail. Any number of colours, including five; colourless is one `C` segment.
- **Tint:** one colour, a two-stop gradient of the tint and a slightly deeper version (W `#fcf6e6` to `#f8efd8`). Two colours, the two tints. Three colours, three stops (0%, 55%, 100%). Four or five colours: the stripe shows them all, but the tint is a neutral `#f3f1ea` (dark: `--surface`), because four pastel stops turn to mud. Angle 135deg on tiles, 90deg on bands.
- **Dark tints** are built from the dark stripes, not the light tints: `linear-gradient(90deg, rgb(74 151 214 / .16), rgb(229 89 79 / .14))` over `--surface`. Chips on a dark band use `--surface-chip` with a 1 px `rgb(255 255 255 / .10)` ring.
- **Deck swatch** (new): a deck named away from its own page (Collection's "In decks", Shopping's "for", the receipt's "goes to", the packing plan) gets a small rounded swatch of its stripe before its name: 10–14 px wide, 4–10 px tall (12 px on a phone), hard-stop 90deg segments, `aria-hidden`. This is the only way deck colour appears on a page that isn't about decks.
- **Mana colours stay off cards and off the UI.** A card's own row isn't tinted or striped; its identity is pips.
- The stripe and pips must come from the deck's real colour identity (worked out from its cards, or its commander). Several drawings gave a deck the wrong colours; see section 6.

### 4.4 Status pills

- **Built:** `--accent` fill, `--accent-ink` text, optional check icon.
- **Building:** 1 px accent outline, `--accent-strong` text, on `rgb(255 255 255 / .8)` over a tint.
- **Idea:** 1 px dashed `#5c6460` (dark `--ink-4`), `--ink-2` text.
- Both hero bands show the pill; casual tiles show it only for Building and Idea (Matt, 2026-10-25: a Built tile has none, as chips are for exceptions); lab rows don't.
- Pills that aren't deck status reuse the warn family: "Out of stock", "mixed" condition, "Check printing", "Shared" (Packing), aging dates. 22 px in lab, 24–30 px casual, with an icon.
- Delivery states ("Part received") should use a neutral outline, not the Building teal outline (see 6).

### 4.5 Buttons and small controls

- **Primary:** `--accent` fill, `--accent-ink` text, round, `--shadow-primary`. Lab 30–34 px, casual 44–48 px. A lab primary may carry a `kbd` hint (mono 10, 1 px `rgb(255 255 255 / .45)` box; dark `rgb(6 32 31 / .4)`).
- **Secondary:** transparent (light: white) fill, 1.5 px `--accent` border, `--accent-strong` text. Always 1.5 px; several drawings had 1 px.
- **Tertiary:** a text button in `--accent-strong`, 700.
- **Destructive:** a tertiary text button in `--weak-ink` (700), "Remove…". The red-filled primary stays only for the last step of a confirm sheet (UI-KIT's `.btn-danger.btn-primary`). "Discard changes" is a tertiary in `--ink-2`, not teal.
- **A primary that can't act yet** (Mark as built before every card is ticked, Record arrival with blockers): drawn in `--track` with `--ink-3` text (about 5:1), no shadow, `aria-disabled="true"` but still focusable, with the reason beside it ("20 cards still to tick"). Pressing it moves focus to the first thing in the way. It turns teal when it can act. This one rule replaces the two the round drew (a disabled look on Packing, an enabled button on Receive delivery).
- **Segmented control:** the only way to pick 2–6 options. Track `--surface-chip` (lab, 28 px) or `--track` (casual, 44 px). Selected segment filled `--accent` with `--accent-ink` text. On touch the segments fill the 44 px track with no inset; with a mouse they sit 3 px inside it. A track that wraps to two rows is a rounded rectangle (corners half the one-row height), not a stadium. (Slice 4 keeps the lab track at `--track` until slice 8 puts lab content on `--surface`: `--surface-chip` on `--page` has no visible edge.)
- **Toggle chip** (new): a filter that's on or off ("Owned only", "Deck's colours", "In storage only"). Off: white, 1 px `--border-strong`. On: `--accent-soft`, 1 px `--accent-line`, `--accent-strong` text and a check. A row of chips is never a row of teal fills. The desktop collection drawing put a 26 × 16 switch inside the chip and the phone didn't; drop the switch and use the check at both sizes.
- **Stepper** (new to P1, `.stepper` exists): round group with a 1 px `--border-strong` outline, − and + in `--accent-strong`. Lab 28 px with 28 px buttons and a mono 12.5 / 600 number; casual 46 px with 44 × 44 buttons and a Figtree 16 / 700 number. Changed: border `--accent`, number bold `--accent-strong`.
- **Checkbox:** native `<input type="checkbox">` with `accent-color: var(--accent)`. Lab 18 px in a 40 × 44 label cell; casual 24–28 px in a 52 px label. A ticked box is "done or now yours", so teal fits.
- **Select and text input:** `--r-field`, 1 px `--border-strong`, lab 30–32 px, casual 44 px. Focus: 1–1.5 px accent border plus the 3 px halo.
- **Menu** (`openMenu()`): `--surface`, 1 px `--border`, `--r-row`, `--shadow-2`. Items 32 px (44 on touch), 13 / 600 with a 13 px stroke icon, highlighted item `--hover`. A divider, then destructive items last in `--weak-ink`. The button that opened it gets a 1 px accent ring.
- **Notice** (`.box`/`.note`): `--warn-soft`, inset `--warn-line`, `--r-panel`, an icon in `--warn-icon`, a bold lead-in, and one secondary button on the right. The icon says what kind: refresh (something is out of date: "Update all"), info circle (something worth a look: "Show only these"), triangle (a check or conflict). On a phone the button word can shorten ("Show").
- **Freshness badge:** see 4.7; the same badge is used for any dated check (a price pulled, a shop checked).
- **Avatars and presence:** the avatar keeps today's per-person `--avatar-*` colours, because presence ("User1 ticked 3 cards 2 min ago") must tell two people apart without leaning on teal. 24 px overlapped (20 on a phone), with a `role="status"` line beside them.
- **Badge:** the Shopping count on a nav link or tab. Write its count as words in the link's name (`aria-label="Shopping, 3 to buy"` on the link, the badge `aria-hidden`). Every drawing put `aria-label` on a plain `<span>`, which screen readers skip.

### 4.6 The split view (lab)

- A list pane and a detail pane, side by side, each scrolling on its own under the top bar. List pane `--surface` with `--gutter-list`; detail pane `--page` with a 24 px gutter.
- Widths by page:

| Page | List | Detail | Stacks at |
|---|---|---|---|
| Library | `minmax(0, 720px)` (880 px from 2200) | `1fr` (46% / 54% from 1000 to 1280); its art 5:2 but at most `min(240px, 30vh)` high | < 1000 |
| Collection | `1fr` (the table) | 400 px (340 from 1000 to 1280) | < 1000 |
| Shopping | 560 px (orders, follow-ups, by shop) | `1fr` (queue and missing tables) | ≤ 1280 |
| Receive delivery | `minmax(0, 1fr)` (the parts) | 452 px, sticky | < 1000 |
| Editor | list `1fr`, search 272–320, stats 272–320 | three panes | < 1000 (list, search, stats) |
| Packing plan | 300 px chooser rail | `1fr` (the plan) | < 1000 (the rail folds to its heading) |

- J and K move the selection, Enter opens. The detail pane's own primary is the region's one primary (Edit deck, Edit copies).
- When the panes stack below the switch, the casual layout takes over; the drawings' stacked lab is only for a narrow window with a fine pointer.

### 4.7 Tables

Today's `table.data` (sticky header, `.th-sort`, `.num`) is the base. P1 adds:

- **Rows:** 36 px (44 on a coarse pointer), 1 px `--divider` lines, hover `--hover`. Header 30 px, `--surface-2`, `--fs-th`, sticky at `--shell-top`.
- **Selected row:** a table row can't have a radius or border, so: `--accent-soft` on every cell, inset 1 px `--accent-line` top and bottom, a 2 px `--accent` inset bar on the first cell, the name in `--accent-strong`. Mark it with `data-selected` on the `<tr>` and `aria-current="true"` on the row's name button (`aria-selected` isn't valid on a plain table row).
- **Matching row** (new): rows a choice elsewhere points to (By shop's chosen shop): `--accent-soft`, no border, a 7 px teal dot and `--accent-strong` 700 in the matching cell, and a removable chip above the table ("Marking MTGMate's rows").
- **Group rows:** the group heading style (30 px, 11 / 800 uppercase, mono count) as a `role="row"` with one `role="rowheader"` spanning the columns.
- **Unknown data:** a mono em dash in `--ink-3`, `aria-hidden`, with visually hidden words ("Condition not recorded"). Not an `aria-label` on a span.
- **Thumbnails in rows:** 30 px wide card pictures (casual rows 52–56 px), `--r-card`, `--shadow-img-sm`, empty `alt` when the name is beside them. No picture: a `--surface-chip` card frame with a 1 px `--border-strong` inset ring and a card glyph in `--ink-4` (a target glyph for a token card).
- **Sorting and labels:** a sort button's accessible name starts with its visible words ("Sort: Name A–Z"; "~AUD row: estimated AUD for the row, sort").
- **Paging:** a footer row: "Rows 851–875 of 1,104", 30 px round previous and next, mono "35 / 45", `kbd` hints. Casual lists end with a secondary "Show more".
- **ARIA:** use a real `<table>` wherever the content is tabular. If a grid of divs is needed for layout, every `columnheader` and `cell` goes inside a `role="row"` (with `display: contents` if needed). A row that's a link isn't a table row: make it a list of links with a spoken label (the iPad Matchups rows).
- **Casual has no tables.** It has rows inside one white `--r-panel` panel: thumbnail, name 17 / 700, the main number top right, a meta line 14 `--ink-2`, and an optional deck line with a swatch. The whole row is one 44 px+ button. Keep its accessible name to the name and the one or two facts that matter, not every line joined.

### 4.8 Sheets and bars

- **Sheets** (`openSheet()`): a bottom sheet on a phone (14 px top corners, `--shadow-2`, a 40 × 5 grabber), a centred dialog in lab, a side panel from 1280 px with `side`. As now.
- **Docked sheet** (new, editor only so far): a non-modal bottom sheet that sits above the action bar, so the count and Save stay visible while searching. 48 px search field, 44 px chips, 76 px result rows.
- **Sticky bottom bars** (`actionBar()`): white at 97%, 1 px top `--border`, `--shadow-up`. Lab 60 px; casual 78–84 px, always sitting just above the tab bar (`--shell-bottom`). No page hides the tab bar, the editor included (Matt, 2026-10-24: the chrome must be the same throughout).
- **Unsaved state** (editor): a 7–8 px accent dot before a changed line's name (the same dot as Save's), "was 3" in `--ink-2`. A removed line stays in place, struck through, with a 1 px dashed `--border-strong` outline (lab) or `--surface-2` fill (casual), and an Undo. The bar says "2 unsaved changes" with the swap in `--strong-ink` / `--weak-ink` mono, then Undo, Discard changes and the split Save (the only primary).
- **Bars stack in one order** from the bottom: tab bar, then the page's bar (Record, Finish, Save). Nothing floats above them: a Forge run shows as the activity icon in the header (4.9), not as a floating pill.

### 4.9 Simulation components

All Forge numbers are mono. None of these is teal except the controls that start or stop a run.

- **Win-rate figure.** The number in `--ink`, never coloured good or bad (flags do that). Inline (lab row): mono 13 / 600, then the range in mono 10.5 / 500 `--ink-2` without "%" (`61% 59–63`). Tile (casual): mono 16 / 600 plus "Forge field" Figtree 13 `--ink-2`. Hero: mono 36 (casual 40) beside two lines, `59–63%  95% range` and `3,400 games · rank 3 of 11` (mono 12–12.5, `--ink-3`). Its spoken label spells it out ("Forge field win rate 61 percent, range 59 to 63, tested 3 days ago"), on an element with `role="img"` or `role="group"`. (Numbers here are the canvas's mock data.)
- **Range bar.** A fixed domain of **20% to 80%** everywhere, so bars compare across pages: `left = (value − 20) / 60`. Track `--range-track`, fully round; 10 px (lab panel), 12 px (casual), 6 px (compact, in Matchups rows). A dashed 1 px `--ink-4` tick at 50%, 3 px past the track each way. The band from low to high in `--range-band`. The point a 3 px `--ink` bar, 3 px past the track. Optional mono 10.5 axis "20 / 50 / 80". `role="img"` with a spoken label. Values outside 20–80 clamp to the ends and the label says the real value.
- **Freshness badge.** A 12 px clock icon and words, round.
  - Fresh (0–7 days): `--surface-chip`, `--ink-2` ("tested 3 days ago"; compact "3 days ago"; in a lab row plain text without a pill). On a tint: `rgb(255 255 255 / .8)` with a 1 px inset `rgb(20 40 38 / .14)`.
  - Aging (8–30 days): `--warn-soft`, inset `--warn-line`, `--warn-ink-sm` text, `--warn-icon` clock.
  - Stale (over 30 days, or the list changed since the test): aging colours, a refresh icon, "retest: changed since".
  - **Unsaved** (new, the editor): aging colours, "for the saved list", and a line saying the unsaved changes aren't tested. It's not about age; it's that the result describes a different list.
  - Heights 17 (lab row), 20 (lab panel), 24 (casual).
  - The same badge, with different words, for any dated check: "pulled 24 Oct" (prices), "checked 3 days ago" (a shop), "check again" when stale. The real date goes in the spoken name, on an element that has a role.
  - Shown only when a date exists.
- **Strong and weak flags.** Round pill, 22 px (lab), 26 px (touch lab), 30 px (casual); 12 / 13 / 14 px 600 text; a chevron, the opponent's name, then the mono win rate. Strong: `--strong-soft` / `--strong-ink`, up chevron. Weak: `--weak-soft` / `--weak-ink`, down chevron. In a Matchups table the flag after the opponent's name says just "strong against" or "weak against". When a cell is narrow, the opponent's name truncates and the flag stays (the iPad); on touch the flag may shorten to the chevron and "weak".
- **Swap-test result.** The swap in mono: `−1 Abrade` in `--weak-ink`, `+1 Burst Lightning` in `--strong-ink`. The result `+3.1 points` (mono 15 / 600, "points" Figtree 12). Below it a verdict pill and the mono range and games (`−0.4 to +6.6 · 600 paired games`). Verdicts: "better" (strong colours, the whole range above 0), "probably better, not proven" (1 px inset `--ink-4` outline, `--ink` text), "no clear difference", "probably worse, not proven", "worse" (weak colours). Curve or count changes from a swap are neutral (`+1` / `−1` in `--ink-3`), because green and red mean better and worse, not up and down.
- **Run activity** (`runs-pill.js`, in `#shell-status`). The details (below) use `--accent-soft` with a 1 px `rgb(15 110 106 / .28)` border. A progress ring (16 px lab, 24 px casual): track `--ring-track`, arc `--accent`, `role="progressbar"` with `aria-valuenow`. Text `--accent-strong`: **Forge playing:** A vs B · `game 37 of 200` (mono) · about 6 min left. Then a secondary Stop with a square glyph, its name "Stop the Forge run". `role="status"` on the details' summary line.
  - **Decided (Matt, 2026-10-24): no progress shown at all times.** While anything runs, the header (casual) or top bar (lab) shows one **activity icon**: a small animated mark (a slowly turning ring in `--accent`, 24 px casual, 20 px lab) in a 44 px button, its spoken name "Forge is playing: show progress". It doesn't move under `prefers-reduced-motion` (a static ring with a dot instead). Nothing shows when nothing runs.
  - Tapping or clicking it opens the details: a popover under the icon in lab, a bottom sheet on a phone. It holds the pill's contents above (A vs B, the progress ring with `game 37 of 200`, about 6 min left, Stop), any queued runs, and a link to Matchups. The same sheet serves any other long job later.
  - The icon is the same at both densities and in both orientations, so it never stacks with the tab bar or a page's bar. The Matchups tab may keep an 8 px accent dot while a run is going.
  - The simulations setting isn't part of the pill. On Matchups it's a neutral chip near the title ("Simulations: Admins only", `--surface-chip`, lock icon). No page-wide banner, as UI-KIT says.

### 4.10 Other pieces the round needed

- **Finish pill:** foil and etched get a neutral `--surface-chip` pill with a small four-point star in `--ink-3`. Non-foil is plain text. Not teal, not a mana colour. (The card picture keeps `--foil-sheen`.)
- **Condition and language:** codes (NM, LP, MP, HP, DMG; `en`, `ja`…) in lab, mono; words on a phone. Unknown is the em dash of 4.7. Copies merged with different conditions get a "mixed" warn pill. One option set for language everywhere: the codes Scryfall uses, shown as names in selects ("English (en)"), plus "Not known". The receipt drawings had three different sets.
- **Exact printing tag:** a 16 px mono outline tag ("EXACT DSK", 1 px inset `--ink-4`, `--ink` text). "any printing" stays plain text.
- **Stock:** "In stock" neutral (`--ink-2` check and words); "Out of stock" a warn pill; not recorded a dash. Teal isn't used: in stock isn't owned.
- **Money:** lab tables mono 12.5, right-aligned, under a header that names the currency ("Ref AUD"), no "A$" per cell; casual Figtree 600 tabular "A$0.90"; estimates "~A$". The rate is stated once per page in the deck tables' exact wording (`1 USD = 1.4237 AUD (ECB rate of …), pulled …`), shortened only where space forces it. Never a total.
- **Owned bar:** 4 px, radius 2, fill `--accent`, track `--surface-3` (`--accent-track` in a selected row, `rgb(20 40 38 / .14)` on a tint). On the way: `repeating-linear-gradient(45deg, var(--accent) 0 2px, transparent 2px 4px)` after the owned fill. The same bar shows tick progress (Packing, Receive delivery: teal for ticked, hatched for split-off copies).
- **Availability marks in a list** (editor): owned (teal check, "4 owned" in `--accent-strong`), to buy ("1 to buy", `--missing` 600), on the way (a 12 × 8 hatched swatch, "1 on the way" `--accent-strong`), in another built deck ("1 in Gandalf and the Valley", `--warn-ink-sm`), basic land ("basic land", `--ink-3`).
- **Step badges** (Packing plan): 20 px (lab) or 28 px (casual) circles, `--surface-chip` with an `--ink-2` number; done: `--accent` with a white check. On a phone a finished step folds to one 56 px `<details>` row.
- **Done rows:** a ticked checklist row keeps its layout; its text drops to `--ink-3` at 500. No strikethrough (it's hard to read at the storage box). A ticked casual card tile dims its picture to .42 opacity with a 40 px teal check disc. A done follow-up turns `--surface-2`, strikes its text in `--ink-4` and offers Undo (`role="status"`). Strikethrough is for removed or finished-with records, not for checklist ticks.
- **Placeholders without pictures:** sleeves as a 28 × 38 swatch of the sleeve's own colour (a product colour, not a mana colour); deck boxes and parcels as stroke icons on a `--surface-chip` tile; tokens without art as a white disc with an `--ink-3` ring and the P/T inside; a card with no image as a card-shaped `--track` frame.
- **Empty and loading states.** The round didn't draw any. Until it does: `.empty` (one line plus the one action that fills it) and `.loading` restyled with P1 tokens; a picture loading sits on its art placeholder colour; a pane with nothing selected shows one `--ink-3` line ("Pick a card to see its copies").

## 5. Per-page notes

### Library (drawn in the earlier round)

Casual: tiles in groups, a filter segmented control and a filter icon button; on the iPad 2 across. Lab: deck rows in the list pane, the selected deck's overview in the detail pane (Forge field summary with figure, range bar, flags and first-player edge; Availability; latest swap). Built (2026-10-25): the summary and Forge field, then At a glance (the verdict strip and a small mana curve), the play guide's first topic (four lines) and up to six key cards, each linking to its deck-page tab; side by side in a pane 1,000 px or wider. New deck is the list's primary, Edit deck the detail's.

### Deck page (drawn in the earlier round, and on the iPad)

Lab: the detail pane promoted to full width, optionally with a 280 px deck rail from 1280 px. Toolbar (previous/next, deck id, Full page, Packing plan, Edit deck), 5 px stripe, 184 px art hero with the white title, the tint band with chips (format, pips, status, Played by, "Last changed"), tabs (Overview, Cards, Matchups, Notes; current tab a 3 px accent underline). Overview: Forge field, Availability, Mana curve (bars in the deck's stripe colours as a top-to-bottom gradient), Latest swap test, Key cards. Casual: today's deck page with P1 tokens, plus a Forge card between Availability and Mana curve.

iPad landscape: about 380 px of chrome on an 820 px screen is too much. Drop the toolbar row: previous/next become 44 px white circles over the art's top-left with "1 of 13", the actions sit over the art's bottom-right (Edit deck with a 2 px white ring so it reads on art), the hero is 148 px, the deck id moves into the tint band. Play matchups moves into the Forge panel's header as a 44 px secondary. Keep the Latest swap test panel (the iPad drawing left it out). On the first deck, "previous" is either disabled or names the deck it goes to.

### Matchups (drawn in the earlier round)

Lab: a table (opponent, win rate, 95% range, a 6 px range bar, games, flag) sorted by win rate, with the overall figure, the first-player edge, the swap-test panel, the run pill and the simulations chip. Casual: one card per opponent, same order. iPad: rows are links (4.7).

### Collection

- Lab: a real `<table>` with 36 px rows (Name, Colour, Type, Set and number, Finish, Qty, Condition, Language, In decks, ~AUD row), the table at `1fr` and a 400 px preview (340 at 1000–1280, where the price note in the toolbar hides). Colour, Type and Language are the first columns to go when the table is narrow.
- Colour identity as 16 px pips (20 in the preview), colour filter as 24 px pip toggles, `C` for colourless.
- "In decks": a deck swatch then "1 in The Free Peoples +1 deck · 1 free"; no deck: "In storage" in `--ink-3`.
- "Condition or language not recorded: 37 rows" is an info notice with "Show only these". The bulk action stays in the table toolbar and says how many rows it acts on, visibly and in its name ("Set condition & language… 1,104 rows").
- "In storage only" is a toggle chip.
- The dated price uses the freshness badge ("pulled 24 Oct") and states the rate once.
- Add card is the primary; Import cards… and Add a precon… are secondary. Edit copies is the preview's primary. Remove… is a destructive tertiary.
- Casual: rows inside one panel (56 px picture, name, price top right, meta, deck line), a sticky search band (48 px search, 50 px filter button, a sideways-scrolling row of 44 px chips), "Show more" at the end, the rate once in the list footer.

### Shopping

- Lab: the list pane (560 px) holds Orders on the way, Follow-ups and By shop as 54 px rows under group headings. The detail pane holds the purchase queue table and Missing cards across decks. Stacks at 1280 px or narrower, because the queue table needs about 840 px.
- Queue states are group rows, not pills: Ready (`--accent-strong`), Waiting (`--building-ink`, with "for stock" or "for a reprint" in the meta), Long-term (`--ink-2`).
- By shop is a single choice (`role="radio"`) that marks that shop's rows (the matching row state). Only row and card counts, never money.
- Stock, checked dates, exact-printing tags and deck swatches as in 4.10.
- A delivery opens in place: a card strip (44 px cards and a "+45 more" tile with a spoken name), notes, a "Check when it arrives" box, and Receive delivery as a secondary with `kbd` R. New order is the page's one primary.
- Follow-ups: Done is a small secondary; the done row offers Undo (4.10).
- Missing cards across decks: the shortfall in `--missing`; filter "Still short 17 | All 23"; rows partly queued get "Queue 1 more" (tertiary), others "Add to queue" (secondary), each named with its card.
- Casual: "By state | By shop" at the top of To buy beside a round add button; long-term rows under "Show all 12, long-term too"; a row of jump chips ("Parts of this page"). Prices Figtree "A$0.90".
- "Part received" should not use the Building pill's teal outline (section 6).

### Receive delivery

- Lab: a sub-page head (a teal back link "Shopping", h1, mono date and order id, a progress block on the right), the parts as 44 px rows with an 18 px checkbox in a 40 × 44 label cell, and a 452 px sticky aside (the selected row, To check, Where these go, Record arrival).
- A ticked row has no extra fill. A row that needs attention gets a warn pill ("Check printing", "Back not said yet"). The copies that stay on the way after a split get a dashed `--accent-line` border and the hatched swatch. Keep the attention state visible when columns hide: put the pill under the name, not in a column that goes first.
- Where these go updates as rows are ticked, from data the page already has; there's no separate Preview button. Record arrival follows 4.5's "can't act yet" rule and opens the existing confirmation with the server's exact changes. Building decks get "Building: keep them with its cards" in `--building-ink`; built decks a sleeve line in `--ink-3`; storage a box icon.
- Condition is a segmented control (NM, LP, MP, HP, DMG), language one select (4.10), quantities the stepper.
- Casual: the whole tile is the checkbox's label (28 px box in a 52 px target); an order's arrival check sits inside its card's tile as a warn strip you tick; a To do / Ticked / All filter; bulk tools behind a Tools button; a Record bar 78 px from the bottom ("2 first: …", a "Today" date button, Record arrival). Where these go is one line per destination.
- Counts must use the same unit everywhere on the page: say "cards" or "rows" and keep to it. The drawings' header and filter counted different things.

### Deck editor

- Lab: three panes (the list, search, stats) over a 60 px sticky bar. Rows reuse the selected-row style; each has a stepper, the availability mark, the printing (body font) and a ⋯ menu (Stand-ins…, Change printing…, Move to the sideboard, then Remove).
- Search results in a plain labelled list (not a listbox with buttons inside), the highlighted one `aria-current`. A result already in the deck shows its stepper on `--accent-soft` instead of Add.
- Show the cost with `manaCost()` in each row as now; MV is a sortable column. (The drawing dropped costs for MV only; that loses information the editor has today.)
- The curve keeps the deck's gradient; a grown bar gets a dashed white line at its old height, a shrunk one a dashed `--ink-4` cap; deltas neutral.
- The Forge panel uses the unsaved badge (4.9), "Test this change" (secondary) and a "re-test against the field after saving" checkbox. No primary there.
- Sideboard group: `--surface-2` band, `--ink-2` heading, "not counted in the 60".
- Deck details: selects and segmented controls (Played by, Status), with fit facts under them in mono 11 `--ink-3` ("64 cards to sleeve · 100 sleeves").
- Casual: header "Editing" (13 / 600) over the deck name (20 / 800) with the 5 px stripe above; 44 × 44 stepper buttons; the docked search sheet; an 84 px action bar above the tab bar, which stays (decided, section 6); Deck details folded into a 60 px row.

### Packing plan (Build decks)

- Lab: a 300 px chooser rail (deck rows with a checkbox; "9 to buy" with the number mono and the colour `--missing`; presence at the rail's foot), and the plan: numbered steps, 46 px rows (28 px thumbnail, name, printing, mono quantity), a Storage order / By name segmented control, an overall progress bar with mono `19 / 39`.
- "Cards both decks would use" is a warn notice holding a small table and one secondary ("Give to Finneas instead"). The card's row carries a "Finneas wants it too" warn pill.
- Mark as built follows 4.5's "can't act yet" rule.
- Casual: two tinted deck tiles as pressed-state buttons switch between decks (the selected one with a 2 px teal ring), finished steps fold, the finish bar sits above the tab bar, `main` has room under it for the bars.
- Below 1000 px the rail needs a "Decks" sheet; it wasn't drawn.
- A card moved from an intact product needs the product's break-up step or a warning, not a plain move row (section 6). Sleeve counts include the sideboard: if the plan says "60 of 100 sleeves, sideboard too", the card count must add up to the same list.

### Dark mode

Drawn on the library (lab) and deck page (casual). It holds with the dark tokens of section 2 (lighter stripes, tints from the dark stripes, near-black text on teal, raised hover, opaque floating pill, image rings). The other pages haven't been drawn dark; slice 13 checks each.

### iPad

See 3.2 and the deck page notes. The editor, Shopping and Receive delivery weren't drawn on the iPad; the touch-sized lab rule is meant to cover them.

## 6. Open questions and risks

What the round didn't settle, and where P1 didn't hold up as written.

**Needs Matt's decision**

1. **Decided (Matt, 2026-10-24): the tab bar stays in the editor.** The chrome must be the same on every page, so the editor's action bar sits above the tab bar like every other page's bar. The list loses about 78 px on a phone; the docked search sheet and folded Deck details have to make room for it.
2. **Decided (Matt, 2026-10-24): teal stays for changed lines only.** "Changed by you" (the unsaved dot, a changed stepper), "Part received" and the packing presence avatars all pushed teal past "action, selected, owned, done". Changed lines keep teal (they're yours and unsaved), "Part received" takes a neutral outline, and the presence avatars keep their per-person colours.
3. **Decided (Matt, 2026-10-24): no run pill.** An animated activity icon in the header says something is running; tapping it shows the progress and Stop (4.9). Nothing floats, so nothing stacks with page bars.
4. **Decided (Matt, 2026-10-25): only Building and Idea tiles show a status pill.** A pill on every casual tile (Built on most of them) sat uneasily with UI-KIT's "chips only for exceptions", so a Built tile has none. The hero bands keep theirs.
5. **Decided (Matt, 2026-10-24): portrait is the phone's chrome, landscape the full top bar.** The tab bar goes up to 999 px; the iPad in portrait looks like the phone, and in landscape (1000 px and up) gets the lab top bar.

6. **Collection filter semantics remain open (raised 2026-10-25).** Existing Find cards matches card colour, while 4.3's pips describe colour identity. Keep the current Card colour selector as a compatibility default and keep identity pips distinct; this is not a new preference from Matt. A switch to identity and its pip filter needs the user's choice. Independent coding can continue.

**Didn't hold up as specified**

6. **Stripes identical in both themes** failed (B nearly vanishes on dark); section 2.2 now has dark stripes.
7. **White on accent in dark** fails; dark uses `--accent-ink: #06201f`.
8. **"Phone has no tables"** holds, but **the lab had no dense table** at all: Collection, Shopping and Receive delivery each invented one. Section 4.7 is the merged version; build it once.
9. **Mono for every desktop number** collided with the existing "printings in the body font" rule and set words in mono in several places. Section 2.3 narrows it.
10. **The 760 px step** is mostly moot once the casual layout takes over below 1000 px.
11. **Lab text is small.** 10.5–12 px on a QHD screen at 100% is fine for Matt; on a laptop at default scaling it may not be. Check on the real devices before signing off slice 2. **Revisited (Matt, 2026-10-25):** on a maximized QHD window it was too small after all, and the library's 5:2 art filled a 1,750 px detail pane (700 px high) and pushed the deck's details below the fold. From 2200 px with a mouse every rem size is 112.5% (13 px lab body becomes 14.6), the library's list is 880 px with 64 px thumbnails, and its detail art is capped at `min(240px, 30vh)`. The detail pane also showed too little for its width, so it now loads the deck (GET /api/deck without matchups) and adds the stats in brief, a small mana curve, the play guide's opening and the key cards (Matt's choice); in a pane 1,000 px or wider those sit beside the summary, with the key cards across the bottom, and the whole pane fits a 1080 or 1440 px high window.

**Accessibility patterns to fix system-wide**

12. `aria-label` on plain `<span>`s and `<div>`s (badges, figures, freshness dates) is ignored by many screen readers. Every drawing copied it from the reference files. Fix it in the components: give the element a role (`img`, `group`, `status`) or put the words in visually hidden text.
13. `role="listitem"` on `<img>`s in delivery strips overrides the image role; wrap each picture.
14. Whole-row buttons on a phone get very long spoken names. Name the row by its card and the one or two facts that matter.
15. The phone hero's white "Last changed" sits where the gradient is only 60–78% opaque; on bright art it may drop near 4.5:1. Deepen the gradient behind text.

**Mock data and drawings**

16. Several drawings gave decks the wrong colours (a green-blue deck drawn blue-red). Mock data only, but it shows the risk: the stripe, tint and pips must be computed from the deck's colour identity, never typed.
17. Drawings were cut at fixed heights, so some show bars over content. They don't show scrolled states; check sticky and fixed parts on the real devices.
18. Some drawing fixes were made with shell edits, and some counts were wrong before review (kit totals, receipt counts). Treat every number on the canvas as illustrative.
19. Not drawn at all: empty and loading states, dark mode beyond two screens, the iPad editor, the Packing plan's Decks sheet, the deck hero collapsing to a sticky title row on scroll, swiping between decks on the iPad, a 4- or 5-colour or colourless deck.

**Behaviour the drawings raised (not visual, but noted)**

20. Packing plan: taking a card out of an intact product (Lightning Aggro) needs the break-up flow or a warning.
21. Receive delivery: the drawing dropped the separate Preview step. The page's preview fingerprint (UI-KIT, `receipt-workflow.js`) still has to bind what's saved; a live Where these go doesn't replace that check.

## 7. Rollout

Each slice ships on its own on top of today's UI kit: no page is rewritten, and after each one Deck Lab works and looks consistent (if part old, part new). Each slice runs the web tests (`test_web.test_page_files_use_the_scales` and the page UI tests), is checked at the sizes in UI-KIT's Test devices table in both themes, updates UI-KIT.md, and is committed before the server is restarted. Turn each into a story in [stories.md](stories.md) and a row in TODO.md when it's scheduled.

1. **Fonts.** Self-host Figtree and JetBrains Mono (2.3), with licences, subsets, `@font-face`, preload and the MIME check. Set `--font` and `--font-mono`. The only visible change is the typeface. **Built 2026-10-24.**
2. **Colour tokens.** Re-value the existing tokens to P1 in both themes and add the new ones (2.1, 2.2, 2.6). `--link` turns teal-dark, `--ink-3` darkens and becomes text-safe, borders become solid. **Built 2026-10-24**, with these differences from the plan, found by its review: `--shadow-1` leaves out its 1 px ring until slices 4 and 8 take the borders off tiles and panels (with both, they'd draw a double edge); a new `--warn-text` (`#7a4c00`, dark `#e9b45a`) for amber warning words straight on a surface, since the new `--warn-ink` is only for text on `--warn-soft` and is nearly `--ink` elsewhere; and a few page rules were repointed to the token that now means what they meant (hovers to `--hover`, so dark hovers rise rather than sink; the meter and colour-bar tracks to `--surface-3`; the avatar's menu-open gap to `--surface`; the even matchup cell's and the runs pill's edges to `--ink-4`; the library's pip ring to `--mana-ring`).
3. **Density tokens.** Add the semantic type, radius and size tokens (2.3–2.5) with their casual and lab values, switched at 1000 px and by pointer (3.3), including the `pointer: coarse` 44 px floor. Pages that don't use them yet are unaffected. **Built 2026-10-24.** Three levels: casual in `:root`, the touch lab in `(min-width: 1000px)` and the dense lab in `(min-width: 1000px) and (pointer: fine)`. The floor is in the tokens: sizes shrink only under a fine pointer, so without one every size token stays 44 px; the per-component `min-height` rule of 3.3 comes with slice 4, when components start reading these tokens. `--r-sm` keeps 6 px until slice 4 (4 px now would square today's chips before they turn into pills). Where the spec is silent: the touch lab's inline win rate is 14 px (`--fs-fig-sm`, level with its 14 px body and numbers), its range 11 px; casual `--fs-fig-range` 14 px, `--ls-hero` −0.03em, and with a mouse under 1000 px a 22 px checkbox and a 36 px stepper.
4. **Components.** Restyle in `components.css` and `cards-ui.css` only: round buttons and the 1.5 px secondary, the "can't act yet" primary, segmented, toggle chips, stepper, checkbox, select, menu, notice, badge (with the ARIA fix), `table.data` row states and group rows, sheets and the docked sheet, action bar. Every page picks these up at once. **Built 2026-10-24** ([HISTORY.md, P1 components](../HISTORY.md#p1-components-2026-10-24-e11-s30-slice-4)), with section 6 question 2 as Matt decided it (a changed stepper teal, "Part received" a neutral outline pill, avatars untouched). Differences from the plan:
   - **Fields are in `base.css`**, where they already lived: `--input-h`, `--r-field`, `--fs-input`, a teal edge and a 3 px `--focus-halo` on focus, round search fields, `--check-size` ticks. The global `:focus-visible` no longer sets a radius (it squared round buttons).
   - **Every notice is amber**, the info kind included (4.5 over the old "info boxes stay blue"): `.box-info` and a plain `.note` have the info circle, the new `.box-stale`/`.note-stale` the refresh icon (the library's and the editor's "Tables out of date" panels use it), `-warn` the triangle. A box with a spinner (a run in progress) shows the spinner instead of an icon. `--info-*` is left to the info pills.
   - **New, beyond the list:** `.btn-discard` ("Discard my changes" in `--ink-2`), `.kbd`, `.chip-outline` (Part received), `--btn-bg` (the secondary's fill: white in light, none in dark), `--seg-track`, `--r-seg`, `--font-num`, `--fs-qty`/`--fs-qty-input`/`--fw-qty`, `--th-h`, `--bar-bg`, `--on-crit`, `--icon-tick-on-accent`, `--kbd-on-accent`, `--focus-halo`. `--r-sm` is 4 px.
   - **The 44 px floor** of 3.3 is one `@media (pointer: coarse)` block at the end of `components.css`; six page rules that set a control's touch height were removed. A segmented track drops its 3 px inset on touch, so it stays 44.
   - **A stepper's typed number** is never under 16 px without a fine pointer (`--fs-qty-input`), as the touch lab's 14 px `--fs-qty` would make iOS zoom on focus.
   - **Tables:** a card's `.label-row` takes no row height and stays top-aligned with its row; the shared hover and the lab's `td.num` size are `:where()`-weighted so a page's row states and column sizes win; a words column after a number column gets a 16 px gutter (mono uppercase headers ran together).
   - **The lab segmented track stays `--track`** until slice 8 (see 4.5). Switch `--seg-track` to `--surface-chip` in `tokens.css`'s 1000 px block then.
   - **A `menuButton` menu stays inside the window** (core.js `keepInWindow`), and a page head's More opens under its button, right-aligned. The library's own ⋯ menu still opens over its button: slice 8.
   - **Left for later slices:** the docked sheet (slice 14, it needs a non-modal `openSheet`); the action bar's height and the toast offsets (slice 7); `--shadow-1`'s ring and the panels' and tiles' radii (slice 8); the producers of the new row states (`data-selected`, `data-match`, group rows, `.cell-unknown`), toggle-chip labels, `.is-changed` and the can't-act-yet primaries' focus-to-blocker click (slices 11 to 14); page rules that still clash (Receipts' 36 px phone fields, `stats.css`'s 52 px setup segments, the editor's amber Save dot, `deck.css`'s row states, `variant.css`'s sheet radius); the tabs' ungated hover.
5. **Deck colour pieces.** One helper for a deck's pips, stripe, tint and swatch from its colour identity (4.3), with the dark values and the 3+ colour and colourless rules. Used first by the library and the deck page's head. **Built 2026-10-25** ([HISTORY.md, P1 deck colours](../HISTORY.md#p1-deck-colours-2026-10-25-e11-s30-slice-5)): `ui.js` `deckColourPieces(identity)` and `components.css`'s `.id-pips`, `.deck-stripe`, `.deck-swatch` and `.deck-tint`. Differences from the plan:
   - **Pip classes are `.id-pip`**, since `.pip` is `deck.js`'s lettered stand-in for cost symbols. Pips are CSS circles with their letter, no longer Scryfall's symbol pictures, in the library and the deck head; stats' colour-source pips stay cost symbols (they're mana, not identity).
   - **Where it shows now, without a layout change:** the library's tiles get 20 px pips by the title, a 5 px stripe across the top, the art placeholder behind the loading art and the tint (135deg) when there's no art or it fails to load (the old `--mana-*` wash is gone); the deck head gets 22 px pips. A colourless deck shows its C; a deck with no readable card shows no colours (`/api/decks` sends `colors: null`), and a commander that can't be read gives way to the Deck cards, on both pages.
   - **Values the spec left open:** the deep stops other than white's take the same lightness step (U `#ddebf5`, B `#e9e5e3`, R `#f9e4e3`, G `#dcede4`, C `#e8e6e3`), and in dark they're the dark stripe at 24% (the tints are 16%); three or more colours share `--art-multi` (light `#e6e4de`, dark `#26272c`); the swatch is 14 × 8 px with 2 px corners, 12 px tall on a phone; a 24 px pip's letter is 12 px.
   - **Left for later slices:** pips over the art, the tinted tile body and 16 px lab rows (slice 8); the hero's stripe and tint band (slice 9); swatches beside deck names away from the deck pages (slices 11 to 13).
   - **Re-checked 2026-10-25** in headless Chrome after the review fixes (desktop, phone, iPad portrait and landscape; light and dark; one to five colours, colourless, unreadable): two fixes in `library.css`. Five 20 px pips ran 4 px past a tile's 112 px of art, so they now close up 4 px in; and in the iPad's landscape lab list four or five 16 px pips squeezed the name to nothing and ran over the owned column, so they now wrap under the name. In dark a four- or five-colour deck with no art has a cover the colour of the tile (`--tint-multi` is `--surface` there, as specified).
6. **Simulation components.** Win-rate figure, range bar (20–80 domain), freshness badge (with dated-check words), flags, swap-test result, the run activity icon and its details popover or sheet. Matchups and the deck page's Forge panel use them. **Built 2026-10-25** ([HISTORY.md, P1 simulation components](../HISTORY.md#p1-simulation-components-2026-10-25-e11-s30-slice-6)): `sim-ui.js` (`winRateFigure`, `rangeBar`, `rangeKey`, `freshnessBadge`, `forgeFlag`, `swapResult`) and `components.css`'s `.wr`, `.range-bar`, `.fresh`, `.flag`, `.swap-result` and `.swap-verdict` (`.verdict` is the stats tiles'); the run activity in `runs-pill.js`. Differences from the plan:
   - **The diverging bars are gone.** Every win-rate bar on Matchups (rows, the pair page's verdict, a live run) and in the field part became the range bar with the mono figure; only the matrix's cells still shade around 50% (`--win`, `--loss`), and the test page's difference bars and axis words moved to Forge's strong and weak colours. A bar beside a figure is `aria-hidden`, so a row's link says the win rate once. The pair page's "X wins more" ends gave way to the 20 / 50 / 80 axis.
   - **Words stay out of mono:** a swap's card names are in the body font, its quantities mono. The range axis is 11 px in the lab (14 casual), not 10.5, under the "nothing below 11 px" rule.
   - **Verdict pills come from the range** (better or worse only when the whole range is past 0), so the server's "slightly better" without a clear range reads "probably better, not proven".
   - **The details:** a popover from 1000 px and a sheet below (centred from 600 px, as every sheet). Stop is there for any run the server lets the viewer stop (`may_stop`), through the existing confirmation. The running list now carries forge's `eta_s` for "about 6 min left", and `/api/variants` each test's `low` and `high`. JetBrains Mono is preloaded.
   - **Where it shows without a layout change:** rows' dates became freshness badges ("retest: changed since" replaces the Matchups list's "Older list" tag); the field's average is a hero with the last field run's age; its better-or-worse links and flagged rows carry flags; the deck page's Tests of changes list shows swap-test results.
   - **Left for later slices:** the icon in the new top bar and casual header, the Matchups tab's dot (slice 7); Forge lines on tiles and rows (slice 8); the Overview's Forge panel and latest swap test (slice 9); the Matchups table, phone cards, Rankings figures and the simulations chip (slice 10); dated prices (slices 11 and 12); the editor's unsaved badge (slice 14).
7. **Shell.** The lab top bar (nav pills, `kbd`, the activity icon, search), the casual header (with the activity icon) and tab bar extended to 999 px (`--shell-bottom` with it), the iPad portrait caps, the bar stacking order (decisions 1, 3 and 5 of section 6). **Built 2026-10-25** ([HISTORY.md, P1 shell](../HISTORY.md#p1-shell-2026-10-25-e11-s30-slice-7)), without the search (Matt, 2026-10-25: global search gets its own story, E11-S31). Differences from the plan:
   - **No search and no `kbd` in the top bar:** Deck Lab had no global search to restyle, so the lab top bar is the brand, round nav pills (the page's section on `--accent-soft` in `--accent-strong`, hover only with a mouse), the activity icon and the avatar, and the casual header has no search icon or the iPad's 300 px field. The `/` key stays the editor's until E11-S31.
   - **A phone on its side keeps the lab's top bar** (static, as before) and no tab bar: "under 1000 px" is `(max-width: 599px), (max-width: 999px) and (min-height: 501px), (max-width: 999px) and (orientation: portrait)`, so a 852 × 330 phone isn't left with 210 px of page. This is decision 5's "landscape is the full top bar" for phones.
   - **Heights:** the casual header is 56 px, the lab top bar's height, not 60 (the phone's was 48), so `--shell-top` has one value but the phone on its side's. The tab bar stays 56 px plus the safe area (the drawing's 78 px reads as about that on an iPhone). A page's bar is at least `--bar-h`: 72 px casual, 60 in the lab, sitting on the tab bar without the safe area (the tab bar has it).
   - **The tab bar never hides** for the editor's bar or Receive delivery's Record bar (decision 1). It gives way only while the on-screen keyboard is up over the editor's search (`keyboard-up`), and the editor's bar sits on whichever is higher, the tab bar or the keyboard (`max()`).
   - **Matchups is the fourth tab** (3.1's list; it was in More), so the tabs are Decks, Collection, Shopping, Matchups and More for home and Decks, Collection, Matchups and More for a member. Its 8 px dot shows while a run plays or waits; the nav pill has none (the icon is beside it).
   - **The iPad in portrait:** the tabs sit in the middle 640 px of a full-width bar; labels stay 12 px (`--fs-xs`, the phone's).
8. **Library.** Casual tiles (2 across on the iPad); the lab split view with the deck overview in the detail pane, J/K and Enter. **Built 2026-10-25** ([HISTORY.md, P1 library](../HISTORY.md#p1-library-2026-10-25-e11-s30-slice-8)), with section 6 question 4 as Matt decided it (only Building and Idea tiles have a status pill) and the Forge number he chose (the field average, worked out on the PC and cached). Differences from the plan:
   - **The Forge numbers come separately:** `GET /api/library/forge` (each casual list's field average and when it was last tested, from `forge.field.averages`) after `/api/decks`, cached per space on the PC until a saved result, a field run's note or a field list changes (or ten minutes pass), and drawn in when they arrive. Until then, or when they can't be worked out, tiles and rows show no Forge line at all rather than `—`. The field is the one the field view uses for the viewer's space; the list is the field's (a built deck's Built version, else its Planned list).
   - **"to get", not "to buy"**, in the owned bar's words, as the library's chips already said (a missing card may be in another deck, not only bought).
   - **The owned bar's words count the Planned list:** a built deck holding its Play-now list shows no bar (its size isn't in `/api/decks`); its readiness chip says it, as before. "Play-now list ready" (or "once N arrive") stays as a chip beside the bar.
   - **Narrow lab rows:** up to 1,280 px (the iPad in landscape, a 46% list pane) the owned and Forge columns are 120 and 112 px and the row's range bar is left out, so a title keeps some room; from 1,281 px they're 150 and 132 px with the bar.
   - **The detail pane** has the Forge summary as a hero figure, its freshness, the range bar with its axis, "Against 3 of the 4 decks in the field so far" while partial, and "Field view" (the deck page's field part); the flags and the first-player edge wait for slice 9's Overview panel, which works out the whole field view.
   - **Still `--track` and the token ringless:** the lab's segmented track stays `--track` (the filter row is still on `--page`; the list pane alone is on `--surface`), and `--shadow-1` still has no ring: the tiles and the detail card draw their 1 px ring themselves (`0 0 0 1px var(--border)`), as other pages' panels keep their borders until their slices.
   - **The library's More menu** opens under its button, right-aligned, as a page head's does.
9. **Deck page.** Hero, tint band, tabs, Overview panels, the casual Forge card, the iPad landscape folded toolbar. **First part built 2026-10-25:** the 184 px lab hero (148 px and folded actions at 1000-1280), identity stripe and tint band, Overview's read-only Forge field, newest swap test and identity-coloured mana curve. The result panels are two columns in the lab and cards in casual widths. Field view reaches the existing run controls; opening Overview starts no games and performs no background polling. The five existing tabs stay, including Stats and Practice. **Navigation and metadata built 2026-10-25:** the fresh visible library supplies previous/next and its count, in the remembered filters/sort when the current deck is in them, otherwise all visible ordinary decks. Links retain the tab/filter and available list, with disabled ends; 44 px opaque circles sit over the narrow lab's art. The hero reserves their space and grows for long titles. Last changed is the actual recorded deck edit (`summary.edited`), with no label for an unknown date. **Still to do in this slice:** true touch/Safari acceptance. The optional deck rail is not built.
   - **Verification:** 214 targeted Python/Node and HTTP-fixture tests; source-scale and duplicate-name checks included. The existing source-length audit still fails on untouched `web/tokens.js` (1,516 lines at the starting commit too); changed source files stay below 1,200. Chromium fixture screenshots and overflow checks covered the nine viewport sizes in UI-KIT, light and dark. The in-app browser used mouse input and its default DPR; a few phone viewport widths rounded up one CSS pixel. No real-device, Safari, touch-pointer, live-data or Forge-game acceptance is claimed.
   - **Navigation/date verification:** 251 targeted tests, including the API's missing/hidden-deck and metadata-failure paths. Chromium's synthetic fixture covered all nine documented viewport sizes plus the 1000/1280 boundaries in both themes, including a 100-character title and actual tab-preserving navigation. No page overflow or title/navigation overlap remained. Input/DPR and real-device limits are unchanged.
10. **Matchups.** The table and phone cards with the new components; iPad rows as links. **First part built 2026-10-25:** one selected deck's saved opponents, a real six-column table with a mouse from 1000 px, casual cards below 1000, whole-row links with coarse input from 1000, the neutral simulations-mode chip, and Rankings' shared figures/mono numerals. The matrix is replaced. Pair selection, reversed perspective, saved-result links, old-list/engine exceptions, uninformative results and blocked-start behavior remain. The pair data has no field average, first-player edge or residual strong/weak flag: these are not inferred from its percentages. **Summary built 2026-10-25:** the selected deck's current Planned or built Play-now list has its own server field summary, including flags and first-player edge, and newest recorded swap. Both panels name their exact list; historical tests retain their original tested cards. Reads are bounded, cached and guarded against stale selections, with explicit retry. All tests focuses the existing section and late-loading field content preserves that destination until the reader scrolls. **Still to do:** touch/Safari acceptance.
   - **Verification:** 164 targeted UI/source checks passed, with no network or simulations. Chromium fixture checks covered Matchups and Rankings at the nine documented viewport sizes in both themes (36 combinations), using mouse input/default DPR; all had no page overflow and all ranking figures stayed within their rows. A phone percentage-wrapping issue found in QA was fixed by reserving the hero value's width and stacking casual ranking rows. Actual coarse-input/Safari/device acceptance is still open.
   - **Summary verification:** 371 targeted Python/Node/HTTP checks passed; synthetic Chromium screenshots and panel/page overflow checks at the nine documented sizes in both themes. A narrow swap freshness badge found in QA now wraps within its panel. Mouse/default DPR only; no actual touch, Safari or physical-device acceptance. The pre-existing source audit failure in `tokens.js` remains.
11. **Collection.** The lab table and preview, casual rows and sticky search (5, Collection). **Metadata built 2026-10-25:** unknown and recorded condition/language treatment, neutral special-finish pills, missing-details info notice, storage toggle, visible all-filtered-row bulk scope, and dated per-copy price estimates. Supported language choices match the backend. The canonical row/hash, write guards and storage guesses are unchanged. **Layout built 2026-10-25:** the keyed lab preview, 400px/340px beside the table; casual rows with 24-row Show more, sticky search/filter sheet, notes and alternate-printing warnings. Current row identity, editing guards, full filtered bulk scope and uncertain/basic-land storage wording are preserved, without new reads. **Lab columns built 2026-10-25:** separate identity/type/printing/finish/copies/condition/language/usage/price/notes, with real table semantics, honest anonymous counts and container-based column hiding. The independently scrollable table has a named keyboard focus target and a local sticky header; 36px mouse rows include the divider and coarse targets retain their 44px floor. **Keyboard navigation built 2026-10-25:** J/K follows the filtered rows across pages, Enter opens the current card from a fresh visible trigger, and Close returns focus to it. Existing edit/read-only fallbacks and lifecycle guards remain; hints show only in the fine-pointer hover lab. **Find cards built 2026-10-25:** casual name-level rows and identity markers, the existing lab grid, sticky closed search/filter band and an active filter count. Expanded filters flow with the page in short windows. Query/paging/space guards and owned/free/incoming/held/basic facts remain; no per-printing price is inferred. Card colour matching is preserved as a compatibility default, not a new semantic choice. **Saved-hint source built 2026-10-25:** storage answers include privacy-gated, uncontested saved packing-list hints and an anonymous remainder, with explicit source list kind. Stand-ins, overcommit, guessed remainder and unavailable visibility never gain names. Canonical rows/hashes and legacy held/guess counts stay unchanged; the existing pool read supplies provenance. These hints do not certify physical copies or a current/historical list revision. **Saved-hint UI built 2026-10-25:** a static lab marker and complete validated hints in the preview and both viewer captions, with source-kind links and a plain saved-list/box/current-list caveat. Stale/unsupported/malformed/older responses stay anonymous; saves/conflicts without fresh storage remove retained names while preserving legacy counts. Viewer links now meet text contrast in either page theme. **Saved-hint colours built 2026-10-25:** optional canonical Planned/library swatches use already-read target sections and the existing identity algorithm. They are independent of the hint source kind and can differ from an owned-view hero. Unknown/unavailable colours remain absent, known colourless is explicit, and visibility/anonymous rollback covers colours with names. **Still to do:** resolve question 6 before changing the filter semantics/pip control. Touch/Safari acceptance remains open; independent slice 12 coding can continue.
   - **Metadata verification:** 161 targeted Python/Node checks passed; synthetic Chromium checks cover the nine documented viewport sizes in both themes with mouse input/default DPR only. No live records, network downloads or Forge games. The source audit still reports the pre-existing 1,516-line `tokens.js`; changed sources stay below 1,200.
   - **Layout verification:** 170 targeted Python/Node checks passed; synthetic Chromium checked the nine documented sizes plus 1000/1280 in both themes (22 combinations), lab selection, sticky search, filter scope and Show more focus. No page/panel overflow remained; the narrow lab table scrolls locally. Mouse/default DPR only; no actual touch/Safari/device acceptance.
   - **Column verification:** 178 targeted checks passed, with an 83-check affected-module rerun after browser geometry fixes. Synthetic Chromium checked the nine documented sizes plus 1000/1280 in both themes (22 combinations): no page overflow/header overlap, 36px fine-pointer rows, and keyboard Page Down kept the header in place. Wide panes fit; the 1000px edge scrolls horizontally inside the table. Actual coarse/Safari/device acceptance remains open.
   - **Keyboard verification:** 184 targeted Python/Node checks passed, including six new lifecycle/paging/viewer regressions. Browser J/K, Enter, viewer Close/focus return and 22 viewport/theme layout checks passed with synthetic data and mouse/default DPR. Actual touch/Safari/device acceptance remains open.
   - **Find cards verification:** 201 distinct targeted checks passed (200 broad checks plus the added held-wording regression); an 82-check CSS/source rerun and 17-case Find cards rerun passed. Synthetic Chromium checked closed/expanded filters at nine documented sizes plus 1000/1280 in both themes (44 combinations), with no page/row overflow and a 50px casual filter button. Sticky search, short-landscape result access, active filter count, distinct card-colour/identity behavior and the 23-item viewer group were checked. Mouse/default DPR only; no actual touch/Safari/device acceptance.
   - **Saved-hint source verification:** 100 targeted sandbox tests passed with live database probes disabled: exact printing/finish, source kind, public/private/product gates, no admin override, stand-ins, overcommit, visibility failure rollback, rows/save/409 consistency, unchanged allocation/hash and pinned read counts. No UI, actual database, live records or Forge acceptance is claimed by this backend prerequisite.
   - **Saved-hint UI verification:** 218 distinct targeted checks passed (217 broad UI checks plus the new two-theme contrast regression); the affected 83-check contrast/source rerun passed. Synthetic Chromium checked nine documented sizes plus 1000/1280 in both themes (22 combinations), preserving 36px mouse rows and wrapping long hint links without page/panel overflow. Preview and casual-viewer Play-now links loaded the actual synthetic owned view; lab Enter exposed the same hints. Viewer links measured 7.17:1 in both themes after fixing light-theme 2.67:1. Actual touch/Safari/device acceptance remains open.
   - **Saved-hint colour verification:** 113 backend sandbox tests passed with live database probes disabled, plus 223 UI/source checks. Synthetic Chromium verified visible preview/expanded-viewer swatches in 22 viewport/theme combinations without page/caption/link overflow. Viewer-local dark stripes preserve a minimum 4.20:1 decorative cue contrast in either theme; preview colours retain the page palette. Mouse/default DPR only; actual touch/Safari/device acceptance remains open.
12. **Shopping, then Receive delivery.** The two-list split, the queue groups and matching rows; then the receipt rows, aside and Record bar. Shopping first, since Receive delivery opens from it. **Frame built 2026-10-25:** 560px list pane for existing deliveries/follow-ups/shop research, buying and missing-card views right, stacked through 1280px. Buying updates retain delivery, Undo and history nodes; jump links also move keyboard focus. Queue/receipt contracts and permissions are unchanged. **Deliveries built 2026-10-25:** one-column native expanders with a 54px collapsed floor, wrapping names/date/pending-copy/status metadata, 44px pictures and unchanged full contents/checks/guarded actions. Open bodies and nested state survive buying redraws; Enter/Space and sheet focus return are retained. **Queue common layer built 2026-10-25:** Ready/Waiting/Deferred headings preserve all states and waiting reasons; Long-term retains deck grouping. Native shop radio/count rows mark canonical queue rows without duplicate viewers/controls, with a clearing chip and focus return. Matching Long-term groups reveal append-only through Show all. Stock/date/reference facts now stay on canonical rows even without a price/image. **Receive shortcut built 2026-10-25:** R from a focused summary opens that current pending delivery, with live context/permission guards and an accessible description; Enter/Space expansion is unchanged. **Receive frame built 2026-10-25:** order/date and explicit copy progress, whole products separate, with a 452px lab loaded-data guidance aside and stacked casual view. Selected/ticked rows alone supply capped destination hints; unavailable/basic destinations stay uncertain. The existing preview/confirmation/apply workflow and Record controls stay unchanged. The aside measures the actual Record bar and reserves focus-scroll clearance when warnings/wrapping grow it. **Dense queue built 2026-10-25:** one attached real-table/card representation, with 36px mouse rows, 30px headers/groups, contained 32px notes controls, exact printing/quantity/reference/shop/stock/date columns and full research detail rows. Original viewer and write controls move at 1000px, retaining identity and close focus. The bounded table keeps scrolling local; fixed Move menus fit the window and reset on return to cards. **Saved metadata built 2026-10-25:** casual dated-check freshness uses only valid non-future saved days, while the lab retains exact semantic ISO dates. Casual exact/any printing and neutral finish pills remain factual; concise viewer names retain full saved evidence in captions. **Planned swatches built 2026-10-25:** optional permitted home target identity decorates linked queue rows and Long-term headings, with unknown/colourless distinction and no cache or Play-now fallback. A typed malformed card-index identity fault removes only optional decoration in Shopping and the shared pool; physical counts and provenance remain intact. **Casual controls built 2026-10-25:** By state/By shop reparents original immediate rows and preserves all categories/research/actions, independently of matching and Long-term reveal. The lab keeps state groups and restores the casual preference. One original Add node moves between header and 44px round casual slot, with current permissions, busy state, sheet and focus retained. **Record bar built 2026-10-25:** one focusable Record arrival action with described client blockers and first-actionable focus. Ready preserves the exact server preview/confirmation/apply, while blank details and partial remainder remain non-blocking. Native date semantics, real-day/type validation and measured guidance clearance are retained. **Dense finish built 2026-10-25:** neutral finish pills share a 16px line with requested printing, held collector numbers and full spoken/title facts; long exact-set tags can clip. The preferred printing column grows to 156px while rows remain 36px and scrolling stays local. **Receive swatches built 2026-10-25:** canonical Planned identity reuses existing permitted target reads and decorates guidance, frozen success, inspection and plain row-name chips. Unknown/colourless and optional-fault boundaries preserve all receipt facts/reads; no viewer/control duplication or card-colour/cache fallback. **Selected row built 2026-10-25:** retained loaded facts and one guarded inspector action use exact component/runtime row keys, with visible-row initial uncertainty, live edit/split/merge/draft updates and explicit hidden-part recovery. Existing forms, viewers, request/preview/draft scope and fresh close focus stay intact. Independent presentation work is built; inline arrival-check strips still need authoritative row association, so component checks remain separate. **Native Pictures built 2026-10-25:** opt-in whole-tile native labels, sibling Inspect/viewer triggers, unique metadata/attention/split descriptions, accepted-state rollback and fresh focus. Casual targets are 28/52px, lab 18/44px, Inspect 44px; casual checked art uses .42 opacity with a decorative 40px disc and readable missing-art fallback. Extracted rendering keeps source sizes bounded. **Ticked filter built 2026-10-25:** the fourth view predicate has explicit empty recovery and optional v1 draft persistence, with older/malformed values falling back to All. Active/done guards, preview/selection/bulk scope and both layouts' hidden-row focus remain intact. **Compact List built 2026-10-25:** native sibling checks and opt-in 44px ordinary lab rows, with zero inherited gap and wrapping metadata/attention/split cues. Precise descriptions, refused-change rollback and fresh inspection/filtered focus are retained. Pictures, read-only/products, remembered layout and request scope stay unchanged. **Row-count units built 2026-10-25:** fill/Attention controls say rows explicitly, while progress stays in card copies; predicates and hidden-row bulk/request scope are unchanged. **Destination confidence corrected 2026-10-25:** pre-record advice and recorded results share one loaded-data classifier. Unavailable metadata/basic lands stay separate from storage; success uses frozen recorded copies, with split/partial/product/token scope preserved. The producer retains per-row unknown logical names separately from known-empty deck needs, independent of printing/picture availability. Deferred remains a real existing state; aggregate Planned-deck shortfalls remain separate from purchase intent.
   - **Frame verification:** 180 distinct targeted Python/Node checks passed, including existing receipt UI checks. Synthetic Chromium checks covered nine documented viewport sizes plus requested 1280/1281 in both themes (22 combinations), with no page overflow; the requested 1281 width rounded to 1282. Keyboard jump focus/route was checked in the browser. Mouse/default DPR only; no touch/Safari/device acceptance or live writes.
   - **Delivery verification:** 231 targeted Python/Node checks passed; synthetic Chromium covered closed/expanded rows in 22 viewport/theme combinations without page/summary/body overflow, including 54px minimum rows, wrapping long names, 44px strips, hidden-copy counts, native Enter/Space and full-contents focus return. Mouse/default DPR only; actual touch/Safari/device acceptance remains open.
   - **Queue common-layer verification:** 253 targeted Python/Node checks passed. Synthetic Chromium checked 22 viewport/theme combinations without page/radio/chip overflow, retaining all fixture rows while marking exact matches. Native arrow selection and Clear focus were verified; Long-term reveal and write/redraw guards have fixture-test coverage. Mouse/default DPR only; actual touch/Safari/device acceptance remains open.
   - **Receive-shortcut verification:** 257 targeted Python/Node checks passed, including four new keyboard guard cases. Chromium opened the actual disposable receipt from closed and expanded summaries at phone/desktop widths in both themes, retaining Enter expansion and resolving the description link. API writes were disabled. No actual touch/Safari/device or assistive-speech acceptance.
   - **Receive-frame verification:** 234 targeted UI/source checks passed, including 11 new frame/observer cases. Chromium checked 24 viewport/theme combinations with resumed copy progress and no page/aside overflow, plus short-lab keyboard scrolling above the measured bar and actual warning-height changes. API writes were disabled; only disposable drafts changed. Mouse/default DPR and keyboard only; actual touch/Safari/device acceptance remains open.
   - **Destination-confidence verification:** 242 targeted UI/source checks passed, including eight new uncertainty/frozen-partial cases. Post-record outcomes are fixture-test evidence; Chromium confirmed pre-record guidance remains intact. No actual receipt/database write or new device acceptance.
   - **Dense-queue verification:** 283 targeted UI/source checks passed. Chromium checked 24 viewport/theme combinations without page overflow, preserving row/matching counts, 36px rows and 30px headers/groups. Actual viewer/reprint close at 999/1000, last-row menu hit testing, Escape/Tab and sticky local scrolling passed. Writes were disabled; save/move/remove behavior is fixture-test evidence. Mouse/default DPR and keyboard only; actual coarse/touch/Safari/device acceptance remains open.
   - **Row-unit verification:** 59 focused receipt/frame/destination checks passed, including unequal row/copy quantities and hidden-row bulk/request scope. Desktop/phone Chromium labels fit; no actual write or new device acceptance.
   - **Compact-List verification:** 283 targeted UI/source checks passed plus the 68-check affected rerun after spacing correction. Chromium checked 24 viewport/theme combinations using an unequal split draft, with 44px clean lab rows, wrapping attention, resolved descriptions and no page/row overflow. Actual native Space/label, split and inspection/Not-checked focus passed. API writes were disabled; coarse/touch/Safari/device acceptance remains open.
13. **Packing plan (Build decks).** Rail, steps, done states, the deck switcher and finish bar, the Decks sheet (draw it first). **Partial 2026-10-25:** the [Decks drawing](packing-chooser.svg) and [scope](packing-chooser.md) preceded the single-tree sheet/300px rail. Existing selection/preview/recipe and twelve-participant contracts remain. 236 integrated checks and 24 Chromium viewport/theme cases passed; native focus, dismissal, capacity and errors were checked with data writes disabled. Fractional widths share the CSS minimum query and focus reveal uses actual viewport bounds. Casual switching and its whole-plan viewer are also built: all participants and task nodes remain, strict Planned colours decorate the buttons, and 252 integrated checks plus 24 Chromium viewport/theme cases passed with data writes disabled. The retained global copy meter and focusable finish guidance are built: 265 integrated checks, 48 final Chromium viewport/theme cases and four zero-task cases passed with data writes disabled. Blocked guidance activation is fixture-only because the browser tool refused the aria-disabled primary; ready review/Cancel and cleanup passed natively. Lab card rows and done card/checklist styles are built: 274 integrated checks and 48 final Chromium viewport/theme cases passed with data writes disabled. Original task/viewer scope remains, with wrapping context and no ghost fallback beneath dimmed art. Completed-step disclosures and done badges are built: 290 integrated checks and 48 final Chromium viewport/theme cases passed, with native keyboard, remote-completion focus and exact 999/1000 reveal checks and data writes disabled. Selected playable-card competition notice/pills are built: 299 integrated checks and 24 final Chromium viewport/theme cases passed with data writes disabled, preserving copy units, original controls/captions and compact full-context labels. Remaining owner details are chooser presence, exact printing and per-card reallocation contracts, plus an intact-product take-apart/transfer workflow. Pool provenance is available, but valid current whole-product/pairing plans release no surplus; do not infer a donor from an id prefix. These remaining details keep the slice partial while independent Editor work proceeds. Exact physical printing cannot be inferred from representative artwork or name-count allocations; device acceptance stays open.
14. **Editor.** Last, because it has the most state. Decision 1 is settled: the tab bar stays. Three panes, row states, the docked search sheet, the unsaved bar. **Partial 2026-10-26:** saved header/stripe, 60px casual details, native current-owner search and casual row/Sideboard presentation are built. The full Editor now retains its Add/search, Stats and Checks roots through tabs, Notes intent and density changes; lab shows three areas with bounded side scrollers and no fourth peek. Narrow lab rows preserve names/cost/printing/availability, Checks headings flow, and owned focus/history repair preserves the original return node. Latest validation: 224 integrated checks and 52 final Chromium geometry/theme/mode cases, with actual writes disabled. Preferred-line result steppers now retain original Add matching, native quantity/Undo and exact action ownership; 245 guarded integrated checks and 24 quantity viewport/theme cases passed. Saved-list curve gradients, old-height marks and neutral deltas are built with actual saved-mode/hydration guards; 255 integrated checks and 28 final Chromium curve cases passed. Remaining row/Forge presentation, docking and bar work remain; device acceptance stays open.
15. **Dark and device pass.** Every page in dark at every test device; draw and build empty and loading states; close what's left in section 6.

Slices 1 to 6 change no page layout, so they can go out one at a time with little risk. Slices 7 onward each change one page (or the shell) and can wait between each other as long as needed.
