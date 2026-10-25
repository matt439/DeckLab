# Deck Lab UI/UX and design review

> **Implemented 2026-10-13.** The owner chose "fix all", and every work package below was built on branch `ui-found`, with the owner's four decisions (an editor on the iPad and a Quick edit on phones; "Planned list" and "Play-now list"; a teal accent; an automatic library picture with an optional `Cover card` header line) and a swipe card viewer for every card list. What was built, what was decided differently and what's still open are in [HISTORY.md](HISTORY.md) ("UI redesign") and [PLAN.md](PLAN.md) ("Still to do", item 10); the shared pieces are in [UI-KIT.md](UI-KIT.md). This file is the dated review the work started from: its screenshots and line numbers describe the page before it.

**Screenshots:** paths are relative to `scratchpad/shots/` (`C:/Users/player/AppData/Local/Temp/claude/C--VSProjects-TradingCardCollection/3499b0a9-223a-4695-aa9a-26cdbd3d9f71/scratchpad/shots/`). Code paths are relative to `decklab/web/` unless they say otherwise.

**The `m-*.png` phone shots are not real 390 px layouts.** Headless Chrome on Windows won't make a window narrower than 500 px. With `--window-size=390` it reports `innerWidth=500` (`extra/probe390.png`), so every `m-*.png` is a 500 px layout cropped to 390. The cut-off theme button, button rows and tabs in those shots are a capture artefact. I re-shot the pages with real device emulation (`extra/resp/p390-*.png`, `c390-*.png`, `t768/1024/1366-*.png`). At a true 390 px there is no horizontal overflow on any of the 15 pages checked. The phone findings below come from those re-shots and from the CSS. For future phone screenshots, use `scratchpad/probe/run.sh` (CDP `Emulation.setDeviceMetricsOverride`), not `--window-size`.

## 1. Verdict

The foundations are good. The data rules are careful, the colour tokens have dark pairs, status chips use an icon plus a word, touch targets are 44 px, the editor's drafts and conflict handling are solid, and the QHD decklist picture grid (`q-deck-gruul.png`) looks good. It feels clunky and ugly for five reasons:

1. **There's no app shell.** The only navigation is a row of nine identical buttons in the Decks page head. Every other page makes up its own head buttons, back link and page names. Admin plumbing (build hashes, Forge settings, a "simulations are admin-only" banner) sits on every page, for everyone.
2. **There's no shared component layer and no scale.** Basic controls only look right on pages that restyle them, so elsewhere you get buttons touching each other and raw native date and search boxes. The CSS has 37 font sizes, 24 radii, 27 spacing values and about 29 one-off shadows. In the light theme, cards and page are the same colour (about 1.01:1), and one blue does links, buttons, info and selection.
3. **Text where pictures belong.** It's an app about physical cards, but card art is shown properly only on the QHD decklist, the Collection grid and Accessories. Receipts, Library, Shopping, Assembly, the Card list and Tokens are text, and the decklist picture grid needs a screen at least 1,600 px wide and a mouse. User1's iPad never gets it.
4. **Pages dump data and machinery instead of giving answers.** Every record shows every field, zero counts included ("0 on the way · 0 held in decks"). Provenance notes show on every token. All 78 saved matchups carry a warning chip, and stats panels explain their formulas before giving the numbers. The answer to "can I build this deck?" is the last section of a 19,000 px page.
5. **Everything has the same weight.** Every record has Edit and Remove at equal size. The deck page has 7 equal buttons, and the main nav is 9 equal buttons. Forms need submit, then preview, then confirm, and their feedback appears where you aren't looking: on the Receipts page, errors go to the top of the page while the button is three screens down.

## 2. Design direction

Keep plain CSS and JS with no build step. Load stylesheets in this order: `tokens.css` → `base.css` → `components.css` → page files. Page files only lay out components; they never restyle a button or an input.

### 2.1 Tokens (`tokens.css`)

**Type**
```css
--font: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
--fs-xs: .75rem;   /* chips and badges only */
--fs-sm: .875rem;  /* meta, captions: the smallest size anyone reads */
--fs-md: 1rem;     /* body, inputs (16px stops iOS zooming on focus) */
--fs-lg: 1.25rem;  /* panel and section titles */
--fs-xl: 1.5rem;   /* page sections, deck title on phone */
--fs-2xl: 2rem;    /* page title */
--fw-regular: 400; --fw-semibold: 600; --fw-bold: 700;   /* drop 500/650/750/800 */
--lh-body: 1.5; --lh-tight: 1.25;
/* numbers: font-variant-numeric: tabular-nums */
```
Text people read uses `--ink` or `--ink-2`. `--ink-3` is only for decoration and disabled states.

**Spacing (4 px grid):** `--s-1 4px; --s-2 8px; --s-3 12px; --s-4 16px; --s-5 24px; --s-6 32px; --s-7 48px; --s-8 64px`. Page gutter is `--s-4` on phone and `--s-5` from 1000 px.

**Radii:** `--r-sm 6px` (chips, thumbnails), `--r-md 10px` (controls), `--r-lg 14px` (cards, panels, sheets), `--r-pill 999px`. Card images keep `border-radius: 4.75%`.

**Elevation:**
```css
--shadow-1: 0 1px 2px rgb(0 0 0/.06), 0 2px 8px rgb(0 0 0/.06);   /* cards */
--shadow-2: 0 2px 4px rgb(0 0 0/.08), 0 8px 24px rgb(0 0 0/.12);  /* sheets, menus, sticky bars */
```
In dark mode, rely on surface steps and borders, and use shadows only for overlays.

**Colour.** Separate the action colour from the link and info colour.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--page` | `#f1f0ec` | `#111113` | page background |
| `--surface` | `#ffffff` | `#1b1b1e` | cards, panels |
| `--surface-2` | `#f7f6f3` | `#242428` | sunken areas, table stripes, empty-state wells |
| `--ink` / `--ink-2` / `--ink-3` | `#161616` / `#46453f` / `#6f6e68` | `#f2f2ef` / `#c4c3bd` / `#8e8d87` | text |
| `--border` / `--border-strong` | `rgb(0 0 0/.12)` / `rgb(0 0 0/.24)` | `rgb(255 255 255/.12)` / `.24` | |
| `--accent` | `#0f6e6a` (deep teal, 5.9:1 on white) | `#4cc2b8` (dark text on it) | primary buttons, selected tab, active nav, ticks |
| `--link` / `--info` | keep `#1c5cab` | keep the existing dark value | links and info chips only |
| `--good` / `--warn` / `--crit` | keep the existing tokens | keep | status |
| `--win` / `--loss` / `--even` | `--good` / `--crit` / `--surface-2` | same | win-rate bars and the matrix (diverging around 50%) |

The accent is your choice; the point is that it's not link blue. Make the avatar colours (`style.css:451-453`) and the overlay literals (`style.css:676`, `732-736`; `devices.css:61-62`) tokens too.

**Write the dark block once.** Have `app.js` always set `data-theme` to `light` or `dark`. For `system`, resolve it with `matchMedia` and listen for changes, using a 3-line inline script in `<head>` so the page doesn't flash. Then CSS needs a single `:root[data-theme=dark]{…}` block instead of the two copies in `style.css:62-131`.

**Control sizes:** `--ctl-h: 44px`. Under `@media (pointer: fine)` use `--ctl-h: 36px` for buttons and 38 px for inputs and selects. The existing `(pointer: coarse)` rules (`devices.css:139`) stay.

**Breakpoints** (one ladder, used everywhere):

| Width | Layout |
|---|---|
| < 600 | Phone: lists in 1 column, image tiles in 2–3 columns, bottom tab bar |
| 600–999 | Tablet portrait: nav in the top bar |
| 1000–1599 | Desktop and iPad landscape: decklist picture grid, the editor's 2 columns from 1100, `.wrap` max 1400 px (now 1120) |
| ≥ 1600 | QHD: full width, hover peek column (hover and fine pointer only) |

### 2.2 Shell and navigation

- **Desktop (from 600 px):** a sticky 56 px top bar. Left: logo and "Deck Lab". Then **Decks · Collection · Shopping** (with a count badge for deliveries waiting) **· Matchups · More ▾**, where More holds Tokens, Sleeves & boxes, Packing plan, Game log, Wishlist and Activity. The active item gets `aria-current` and an accent underline. Right: an avatar button (the person's initial in their colour) that opens a menu with Theme (Auto/Light/Dark segmented control), Switch person (home network only), "This is my device" (skips the Who gate), and for admins Settings and About.
- **Phone (under 600 px):** a 48 px top bar with a back crumb or the logo, the page title and the avatar. Below it, a fixed bottom tab bar (56 px plus `env(safe-area-inset-bottom)`) with Decks, Collection, Shopping and More. More opens a sheet with the rest. Toasts sit above the tab bar.
- **One routes table in `core.js`:** `{path, label, h1, title, icon, visible(profile), parent}`. It drives the nav, crumbs, `document.title` and visibility. Each page gets one name:

| Route | Name |
|---|---|
| `#/library` | Decks |
| `#/collection` | Collection |
| `#/tokens` | Tokens |
| `#/accessories` | Sleeves & boxes |
| `#/shopping` | Shopping |
| `#/assembly` | Packing plan |
| `#/play` | Game log |
| `#/matchups` | Matchups |
| `#/activity` | Activity |
| `#/wishlist` | Wishlist |
| new | Settings (admin) |

  Hide items a profile can't use, or that are empty for members.
- **Page head pattern:**
  - a crumb, only on child pages, top left, named after the parent ("← Gruul Ramp", "← Shopping");
  - h1 and a one-line description;
  - one filled primary action and a "More ▾" overflow menu for the rest.
- **Footer:** one quiet line, for example "Prices 2026-10-12 · 1 USD = 1.43 AUD", or nothing. Version, update check, simulations mode and Forge workers move to Settings. The build-warning box still shows when the server is out of date.
- **Simulation permission:** shown inline next to any disabled Play or Start button, never as a page-wide banner.

### 2.3 Components to standardise (`components.css`, with small JS helpers in `core.js`)

| Component | Spec |
|---|---|
| `.btn` | Variants `--primary` (accent fill), `--secondary` (outline), `--quiet` (text), `--danger` (red text, and red fill only inside a confirm sheet). Size from `--ctl-h`. One primary per view. |
| `.actions` / `.toolbar` | `display:flex; flex-wrap:wrap; gap:var(--s-2); align-items:center`. Toolbar: live search on the left, filter chips or segmented control on the right, result count below. |
| Fields | A base rule for `input:not([type=checkbox],[type=radio],[type=file]), textarea, select`: `font:inherit; font-size:max(16px,1rem); min-height:var(--ctl-h); padding:10px 12px; border:1px solid var(--border-strong); border-radius:var(--r-md); background:var(--surface)`, plus `:disabled`, `::placeholder` and `[readonly]` states. Checkbox and radio: `accent-color:var(--accent); width:22px; height:22px`, inside a label row of at least 44 px. |
| `.segmented` | Already exists; becomes the only way to pick 2–6 options (finish, condition, theme, scope). |
| `.chip` | One pill (`--fs-xs`, `--r-pill`, icon plus word) replacing `.status`, `.shopping-badge`, `.activity-via`, `.tok-chip` and `.acc-owner`. Rule: show chips only for exceptions, never for "all fine" or zero. |
| `.note` | info/warn/crit/good boxes. Use them for a state of this item, never for a setting that's normal. |
| Disclosure | The `details.more` chevron (`style.css:826-834`) on every `summary`, including the ones that are `display:flex` today and show no marker. |
| `.tabs` | Real tabs with `?tab=` in the hash. A right-edge fade mask while they overflow. Sticky under the top bar. |
| Sheet | A `<dialog>`: bottom sheet under 600 px, centred 560 px dialog on desktop, right side panel (380 px) for row editing from 1280 px. Destructive actions sit at the bottom of the sheet. |
| Menu | An overflow popover for "More ▾" and per-row ⋯ menus. |
| `.card-tile` | Image at 488/680 via `cardThumb` srcset; ×N badge top-left (only when N > 1); a state badge or tick top-right; foil sheen; name in one line; one meta line; optional dashed "printing not recorded" frame. Click opens a sheet or `openCard`. Sizes: 3 columns on phone, about 150 px on tablet, 156–196 px on desktop. |
| `.card-row` | Thumbnail (40×56 full card, or Scryfall `art_crop` at small sizes), name, set and number in `--ink-2`, chips, quantity right-aligned with tabular numbers. Click opens a sheet. |
| Mana symbols | Scryfall's symbology SVGs cached once in `data/`, served from a new `/sym/` route, and used for costs, oracle text and guide prose. Keep the `aria-label` words. Replaces the lettered `.pip` circles and "φ". |
| `.action-bar` | A sticky bottom bar with progress, status and the primary action, generalised from the editor's `.edit-bar`. |
| Toast | With Undo (about 8 s) for instant removals and picks. |
| Empty state | One line plus the one action that fills it. |
| Data table | Sticky header, sortable columns, dense rows on fine pointers. |

## 3. Prioritised plan

Sizes: S is under a day, M is 2–4 days, L is about a week or more. After any code change, restart the background server if it's running (`python -m decklab.lib.homenet restart`). Test the phone layouts with CDP emulation.

**Decisions only you can make** (nothing below is blocked on them except where noted):

1. Allow editing on an iPad, and some quick edits on a phone (WP11). Commit `cd354e2` made the editor desktop-only on purpose.
2. One name for the second list (I suggest "Planned list" and "Play-now list"). The deck-text heading stays as it is.
3. The accent colour.
4. How a deck's library picture is chosen: by default the commander or the most-copied non-land, or a new optional header field, which would change the deck text format.

**WP1. Quick CSS fixes (S, no dependencies)**
- Add a global `.actions` rule. Fix `deck-tools.css:1`, which sets wrap without `display:flex`.
- Add the base field rule from 2.3, covering date, search and textarea. Delete the six copies (`editor.css:72`, `accessories.css:60`, `collection.css:43`, `tokens.css:10/80/99`) and fix `play.css:26`.
- Set `accent-color` and a 22 px size on checkboxes and radios, inside 44 px rows.
- Change the light `--page` and `--surface` to the values above, and add `--shadow-1`.
- Make `.deck-title` use `--ink`.
- Put the chevron on every `summary`.
- Pad `.receipt-checks` so its bullet doesn't hang outside the panel.
- Replace `overflow-wrap:anywhere` with `break-word` plus `hyphens:auto` in `tokens.css:42-43` and `accessories.css:18-20`.
- Add a fourth filter column at `devices.css:12`.
- Add a fade mask to `.section-nav`.
- Give the text search in `.collection-filters` two columns.
- Resolves: DS-1, DS-3, RS-7, INV-1, DS-5, DS-m2, DS-m3, IA-12, RS-6 (in part), RS-14 (bullet), RS-11 (word breaks).

**WP2. Copy and noise pass (S–M, no dependencies)**
- Show the simulations notice only beside Forge controls. Read `may_start` (already in `/api/simulations`) on every run control and swap the button for "Ask Matt to play this" when false. Change `permissions.py:120` to "Only Matt can start simulations right now".
- Hide the build line from members.
- Receipt headings: plain words instead of `cards · cards` (`receipts.js:20,44`).
- Default the arrival date to today, with today as the max (the server already has `_receipt_today`).
- Game log results: "<name> won" instead of "Player 1 won" (`play.js:140`).
- Accessories: "Not in use" instead of "Free".
- Wishlist: show a deck source as the deck's title, linked (`wishlist.js:78-84`).
- Library token chip: say "token" (`library.js:289-297`).
- Products caption for person spaces (`library.js:186`).
- Hide zero counts everywhere.
- Show "Earlier engine" as a neutral tag, and only when no newer result exists.
- Show the deck's current title in matchup rows.
- Use the same space order on every page (`collection.js:127` vs `core.js:229`).
- Name practice and test-hand parts the same in the nav and heading. "Deal a hand" status: "Opening seven. Keep or mulligan?"
- Resolves: IA-8, GEN-1, RS-m1, MU-03, R6/R7 (receipts), INV-17 (wording), INV-14, INV-11 (in part), LB-2 (in part), IA-13, MU-02, MU-15, INV-16, DK-11, DK-12 (in part).

**WP3. Tokens and component layer (M, after WP1)**
- Create `tokens.css`, `base.css` and `components.css` as in 2.1 and 2.3.
- Sweep the font-size, radius, spacing and colour literals onto the scale.
- Add the `pointer:fine` density step.
- Move the shared pieces out of page stylesheets: `dialog.sheet`, `.btn-danger` and `.page-head-actions` from `editor.css`; `.head-buttons` from `matchups.css`. Delete the dead `.card-dialog` block (`style.css:719-745`).
- Fix the load-order comment in `devices.css:3`, and use the single dark-theme block.
- Resolves: DS-6, DS-7, DS-8, DS-14, DS-15, INV-19, and the chip unification in DS-11.

**WP4. App shell (M, best after WP3)**
- Add the routes table in `core.js` and nav in `index.html:82-101`.
- Phone tab bar and sticky top bar (`style.css:257`), with the section nav's sticky top offset by the bar's height.
- Avatar menu with theme, switch person and "this is my device" (a localStorage flag that skips the Who gate and the away timeout).
- New `#/settings` page for admins: simulations mode, workers, version and update check, moved out of `index.html:113-128` and `version.js:97-200`.
- A `crumb(href, label)` helper that replaces the ten hand-made back links and "Decks" buttons (`shopping.js:102`, `collection.js:149`, `tokens.js:301`, `accessories.js:217`, `assembly.js:28`, `wishlist.js:62`, `play.js:54`, `activity.js:27`, `history.js:33`, `matchups-detail.js:48`, `matchups-overview.js:443`, `receipts.js:87`). Child pages keep their deck context.
- Remove the nine-button row from `library.js:79-90`.
- Titles come from the routes table.
- Resolves: DS-4, IA-1–7, IA-11, IA-14, IA-15, RS-3, RS-12, RS-13, DS-13, MU-16, IA-m4.

**WP5. Shared card tile, card row and mana symbols (M, after WP3)**
- Add `cards-ui.js` with `cardTile()` and `cardRow()`, built on `cardThumb` (`deck.js:307`) and `openCard` (`deck.js:373`).
- Make a `tokenTile()` from `tokenThumb` (`tokens.js:43-53`).
- Server: a `/sym/<code>.svg` cache from Scryfall's symbology, and a symbol renderer for costs, oracle text and prose.
- Resolves: DK-9, and it's the base for WP6–WP10.

**WP6. Receipts check-off board (L, after WP1; uses WP5's tile, or builds it first and WP5 extracts it)**

This is your PLAN.md request. It could go straight after WP1 if you want it first. The preview and apply API contract (`verified`, `rows`, the blockers) does not change.

1. **Page.** A header ("Receive delivery", seller and order date, order notes clamped to 2 lines with "More"). Then one section per pending component, then a sticky action bar. Remove the 1200 px cap (`receipts.css:1`) and allow up to about 1800 px.
2. **Component section.**
   - A plain heading: "15 cards from MTGMate", "13 token cards" or "Wretched Ranks (product)". Show the id only when it isn't the default (a split part such as `cards-2`).
   - When an order has a single pending component (all 8 pending orders today), select it automatically and hide its checkbox.
   - When there are several, a "What arrived?" switch per component, 44 px.
   - Then a **To check** card listing `component.checks`, each with its own tick.
   - Then the toolbar and the grid.
3. **Grid.**
   ```css
   .rcpt-grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(156px,1fr))}
   @media (max-width:599px){.rcpt-grid{gap:8px;grid-template-columns:repeat(3,1fr)}}
   ```
   That gives 3 tiles at 390, about 6 at 1440 and 9–10 at 2560.
   - A Pictures/List toggle, remembered in localStorage. List is the same tile with a 46 px thumbnail in one row: "3 × Swords to Plowshares · MSC 143 · Nonfoil · ? cond · ? lang".
   - Filter chips: All · Not checked · Needs attention (blank condition or language, a check note, a fallback picture, edited).
   - Images use `loading=lazy` and a skeleton in card proportions with the name on it, because `/img/` downloads serially with a 0.1 s gap (`cards.py:88`).
4. **Tile.**
   - The recorded printing's picture (`/img/<set>/<num>/small`, plus `normal` in the srcset).
   - ×N badge top-left, only when N > 1.
   - A 44 px round tick top-right (`aria-pressed`). Ticked tiles get an accent ring and the picture dims to 85%, so unchecked cards stand out.
   - Foil: a rainbow sheen overlay (`linear-gradient` with `mix-blend-mode:soft-light`) and a "Foil" chip. "Etched" gets a chip too.
   - Under the picture:
     - the name (2-line clamp; front face only for double-faced cards, full name in `title`);
     - "MSC 143 · Nonfoil" in monospace;
     - chips: "NM · EN" (good), "Condition ?" and "Language ?" (amber, because blank is allowed but should be visible), "Edited" (blue), "Split 1 of 2", and ⚑ when the row's notes or a check name the card.
   - No recorded printing, or one unknown to Scryfall: a dashed border with the ribbon "Default picture: printing not recorded" or "… msc 999 not in card data". With no card match at all, a text tile.
   - Small chips for the decks that use the card ("Giada Angels ×1"), so you know where it goes.
5. **Edit sheet** (tap a tile; bottom sheet on phone, right panel from 1280 px; Esc closes; swipe between tiles on phone).
   - A large picture, with Zoom opening `openCard` for the rules text.
   - Printing: "MSC 143 · Murders at Karlov Manor Commander" and a **Different printing…** button. It uses a shared `pickPrinting(name)` built from `collection.js:485-530` and `/api/cards/printings` (`editor-cards.js:453-532`), with thumbnails, and sets set and number together.
   - Finish: segmented, limited to the finishes that printing has.
   - Condition: segmented `? NM LP MP HP DMG`.
   - Language: a select with blank first (en ja de fr it es pt ko ru zhs zht).
   - Notes, with a one-tap "Remove 'check on arrival' note".
   - Quantity shown but fixed.
   - **Split copies** for quantity > 1: a stepper moves k copies to a new tile, and "Merge back" undoes it. The server only compares per-name totals (`receive.py:251-263`).
   - Footer buttons: **Tick and close** (primary) and **Next card →**.
6. **Tokens.**
   - The front picture (`tokens._face`), with the back as a small overlapping picture when it's recorded.
   - Text like "TM11 5 · 2/2 Ooze", so the two Ooze rows can be told apart.
   - In the sheet: front and back face pickers, **Swap front/back**, a **Back is blank** switch (writes `single-sided verified` and removes "reverse face unconfirmed…"), and "Back is really: [▾]".
7. **Products.** Read-only tiles from `product_item`, grouped by deck and section with the Commander first, and basics collapsed. Two large choice cards above the grid: "Keep it as its own deck(s)" and "Break it up into storage". The token checks stay listed, with a note that tokens are recorded later on the Tokens page.
8. **Toolbar.**
   - "Not set yet → Condition [NM] Language [EN] [Apply to 15]".
   - "Tick all", with a confirm.
   - "Clear 'check on arrival' notes on ticked tiles" (on by default when a tile is ticked; undo per tile in its sheet). It uses `/;?\s*(condition and language not recorded; )?check (physical pairing )?on arrival/`.
9. **Sticky action bar.** Progress "9/15 ✓" (and "1 check left"), **Arrived: [Today ▾]** (Today, Yesterday, another date), a status line, and **Preview**.
   - Preview opens a dialog: the outcome in plain words ("15 cards go into your collection (13 new, 2 you already had). These decks' tables update: [Giada Angels] [Free Peoples]" with deck chips as links), then blockers that link to their tiles, then **Record arrival**.
   - Editing after a preview shows "Changed since preview, preview again" in the bar. It no longer clears the preview without a word.
   - The component's "verified" becomes the button **Confirm: all 15 checked**, enabled when every tile and check is ticked. It still sends `verified:true`.
   - On success the page is replaced by a success view with "Where these go", grouped by deck and sleeve colour, with the rest marked "to storage", and links to Shopping and the refreshed decks.
10. **Draft.** Edits, splits and ticks are saved in localStorage under `receipt:${order}:${fingerprint}`, wrapped in try/catch. On load: "Resume your check (9 of 15 ticked)". The draft is dropped when the fingerprint changes or the receipt is applied.
11. **Server, read side only** (`api/receipts.py` `receipt_view`, `:79-91`):
    - Add a per-component `pictures` array aligned with `rows`. It must not go inside the rows, because `_edited` requires `set(row)==set(fields)` (`receive.py:247-249`).
    - Return `today`.
    - Return the product's `items`.
    - Return per-row `decks` (from `deck_line`, within the space).
    - If the card index isn't ready, return `pictures:null` and the page draws text tiles.
    ```python
    def _picture(row):
        card = cards.card(row['name'])
        if card is None: return None
        p = cards.printing(row['set'], row['collector_number']) if row['set'] and row['collector_number'] else None
        exact = bool(p and cards.printing_card(row['set'], row['collector_number'])['name'] == card['name'])
        shown = p if exact else _shown_printing(card)
        return {'card': _card_json(card, shown), 'exact': exact,
                'why': None if exact else ('not recorded' if not row['set'] else 'not in card data')}
    ```
12. **Read-only view** (members, opened from Shopping's "Receipt details"): the same tiles without ticks or the sheet.

- Resolves every Receipts finding: R1–R15, R-m1–m3, DS-2, IA-16, RS-2, RS-14, RS-m2, INV-m1.

**WP7. Deck page rebuild (L, after WP3 and WP5)**
- **Header:** title, colour pips, a status pill, and one meta line ("Casual 60 · Matt · 60 + 6 SB · Bracket 2"). Edit plus "More ▾" (Packing plan, Game log, History, Copy, Download, Print) on one row. An **availability banner** from `data.owned.totals`: "Ready to build", "1 on the way", or "32 missing, about A$41 · 3 held by other decks", with a [Show missing] button. Hide it from viewers who may not see the space's inventory. The version picker folds into the banner and its explanation goes behind an "i". Drop the "Sleeves are chosen…" and "build on your computer" sentences, and the Tokens chip unless something is wrong.
- **Tabs:** Overview (banner, game plan, stats verdict strip, key cards as large pictures), Cards (List/Pictures toggle at every width, an All/Missing/On the way/In other decks filter, tokens and sideboard), Stats, Practice, Matchups. Heavy parts load when their tab opens, and the practice run starts on its tab or a button, not on scroll. Phones get real tabs; desktop can keep anchor scrolling.
- **Cards:** join `data.owned.rows` onto the rows and tiles to add "2 missing", "on the way" and "in Gruul Ramp" badges, and grey out missing copies. The picture grid from 1000 px, with `--tile-w` about 110, 150 and 180 px; `art_crop` for List thumbnails. Owned vs needed becomes a folded "Price table", or one line when nothing is missing.
- Guide card names as dotted-underline text links. Symbols render in prose too.
- Stats: a verdict strip first; explanations go in closed disclosures.
- The card dialog opens on the picture on phones, renders `{T}`, and drops the duplicate h3.
- Matchups: one row per opponent with the latest result, older results folded. "Not played yet against: …" as one line. Never "No games yet" for an opponent that has older results.
- Resolves: DK-1–13, DK-15, DK-m2–m5, IA-9, IA-m5, RS-4, RS-5, RS-6, RS-8, RS-16, DS-16, MU-12.

**WP8. Library as a deck shelf (M, after WP5)**
- An `art_crop` banner on each tile (decision 4), colour pips, a status pill, one readiness chip in plain words ("Ready to play" / "1 card on the way" / "8 to buy · play-now list ready"), and token state on its own line.
- The whole tile is the link. When a deck is missing cards, it goes to `#tab=cards&filter=missing` (chips can't be nested links: the tile is one `<a>`, `library.js:258`).
- Drop the format line inside groups.
- Products start folded and remember the choice. Sort options: Ready first / Recently changed / Name.
- Filters on one row; on phone, a "Filter (n)" sheet.
- Resolves: LB-1–3, DS-9, DS-11 (library), DS-m4, IA-12, IA-13, RS-15, RS-m3.

**WP9. Collection, Tokens, Sleeves & boxes, Wishlist (M–L, after WP3 and WP5)**
- **Click to edit everywhere:** remove the permanent Edit/Remove pairs. Tapping a record opens its sheet, with Remove at the bottom.
- **Card list:** a sortable dense table with thumbnails, paged or virtual, and a "condition/language not recorded" filter.
- **Find cards:** compact tiles (image as the tile, ×N badge, one "3 owned · 2 free" line, chips only when not zero), 2 columns on phone (`minmax(150px,1fr)`, fluid image), filters that apply live, "Page 3 of 30" with First/Prev/Next/Last at top and bottom, and "Edit copies" in the dialog.
- **Add card:** a printing picture strip (reuse WP6's `pickPrinting`).
- **Tokens:** example art per face name for rows with no printing (`lib/api/tokens.py:96`), clearly labelled "example art, printing not recorded" (AGENTS.md forbids guessing printings). Notes go into the sheet. Uses become deck chips, with one "details to check" marker per tile. Panel title "Tokens your decks make that you don't have", split into Missing and On the way.
- **Sleeves & boxes:** a dashed "none chosen" slot instead of "?". Product sleeves and boxes are chosen through the deck page's Choose… sheet, not a select that saves on change. Add a "Built decks without sleeves (N)" panel.
- **Wishlist:** an Undo toast after Remove, and Edit note, printing and source.
- Resolves: INV-2, INV-3, INV-6–9, INV-11, INV-13–15, INV-18, INV-m3, DS-10, DS-17, RS-10, RS-11.

**WP10. Shopping, Packing plan, Game log (M, after WP5)**
- **Shopping:**
  - Each delivery card is titled seller · topic, has a strip of 6–8 thumbnails with "+N", nests its on-arrival checks inside it, and has Receive delivery as its primary action. "On the way" appears once.
  - Hide an empty To buy column.
  - A "Decks still missing cards" group linking to each deck's missing filter, kept separate from the purchase queue as AGENTS.md requires.
  - The long-term plan as a visible section grouped by deck.
  - Follow-ups for received orders in their own list, with a **Done** action. That needs a new write route (`order checks --resolve` behind `guard.py`, with an audit-trail change set).
- **Packing plan:**
  - Grouped steps (sleeves; pull from storage; move from other decks; basics; tokens; still waiting, folded), pull rows as image tiles, a sticky "Pulled 12 of 31", and ticks kept in localStorage per plan.
  - Choose decks from a checklist instead of repeated "Add a deck".
  - "Sleeves: Not recorded" becomes a Choose button.
- **Game log:** a quick record (two deck pickers defaulting to each player's last deck, then big "Matt won / User1 won / Draw" buttons). Details go under "More details".
- Resolves: DS-12, IA-10, IA-m2, IA-m3, INV-4, INV-5, INV-10, INV-17, INV-m2.

**WP11. Editor (L, after WP3; ED-1 needs decision 1)**
- Clicking or pressing Enter on a result adds 1, and the row flashes "Added ✓ (now 3)". Shift+click or Shift+Enter adds 4, and a leading count ("4 bolt") is parsed. Remove the Inspect/Add bar and its hint, and show at least 6 results.
- Results show a line of oracle text, the A$ price, an owned badge, and owned cards first. An "Owned only" toggle, colour/type/mana-value filters, and a "My collection" browse tab of free owned cards in the deck's colours.
- Dense 32 px rows with one status badge, shown only when something isn't simply owned and free. "−" at 1 removes the card with Undo, so Remove moves into a ⋯ menu.
- A Visual toggle showing image stacks.
- Two columns with a sticky side panel from 1100 px, the peek from 1400 px, and "/" to focus search.
- Side-panel tabs: Add · Stats (mini curve, lands, colour sources, type split) · Checks ("3 missing · ~A$4.20", warnings, bracket).
- Save in place with no blocks, a toast, and Ctrl/Cmd+S; the review sheet only appears for blocks or conflicts. A split button "Save & view deck".
- A Notes tab with a textarea for the prose, and a "Mark write-up as current" button that removes the "Decklist changed" line.
- Paste a list: Add or Replace, with a diff.
- Undo history for every change, Ctrl+Z.
- New deck: Title and Format only (plus Whose deck for an admin), with no size warning until the list has cards; "Start from a paste / a precon / another deck"; the two-column layout.
- The printings sheet as an image grid, with Move and Remove at the bottom.
- Most hint text removed.
- iPad (if you agree): allow any pointer from 1000 px (`editor.js:68-70`). Phone: a Quick edit (steppers, a search sheet, printing, status).
- Resolves: ED-1–15, ED-m1–m4, RS-9, DK-m1.

**WP12. Matchups (M–L, after WP3)**
- The Matchups home becomes a **matrix**: decks on both axes, each cell the row deck's latest win rate on the diverging scale with the number printed. Faded cells are older results, an empty cell has a "+" to play that pair, and a tap opens the pair page. On phone, "Show matchups for [deck]" and a sorted list.
- One row or cell per pair. Earlier results sit on the pair page, which never says "haven't played" when older results exist.
- The result page leads with a verdict: "Angels is a big favourite: wins about 9 in 10" with a bar, at most one caveat line, and Play more. "Why we're confident" and "Details" start closed.
- One run vocabulary everywhere: Quick look / Settle it / Precise, with the set-count option under More options and a single time estimate.
- Diverging bars; per-row whiskers dropped.
- The field part shows one empty state when it has no games, sorted rows, and plain wording.
- Variant tests: one scale shared by every bar on the page with axis labels, coloured by verdict.
- A global "Forge playing: X vs Y, 640/~1,100" pill in the top bar, with progress marked at the planned checks. Remove the "Last checked / Refresh" rows.
- Meta built as one string. The pilot box names the deck shown.
- Resolves: MU-01–15, MU-m1–m3, DK-13.

**WP13. Activity and History (M)**
- **Activity:** headlines in plain sentences ("Matt received the Ronin Games order: 16 cards"), the first 3–5 rows with "Show all", filter chips by kind and person, and links to decks, cards and orders.
- **History:** the server works out each revision's change against the revision before it, shown inline ("+2 Rabid Gnaw, −1 Shock") with card pictures. Today it diffs against the current list (`history.js:20-21`). Revisions that only changed the table or prose are folded.
- Resolves: INV-12, DK-14.

**Keep:** status chips with an icon and a word, 44 px touch targets, safe-area insets, the sticky deck section nav, the QHD picture grid and 488 px peek, editor drafts, rebase, conflict wording and removal Undo, "Did you mean", the result page's headline sentence, the Stop-run confirmation, and the ARIA on the SVG bars.

## 4. Findings by page

Severity is the verifier's. Each row has a primary ID; "also" lists duplicates merged into it.

### 4.1 Global: shell, navigation, design system

| ID | Sev | Finding | Evidence | Fix |
|---|---|---|---|---|
| IA-1 (also DS-4, IA-5, RS-3) | High | No global navigation. The only nav is 9 equal outline buttons in the Decks head, 3 rows on a phone; other pages offer only "Decks" or a back link, so Shopping → Collection goes through Decks. Nothing marks the current section. | `index.html:82-101`; `library.js:79-90`; `d-library.png`, `q-library.png`, `extra/resp/p390-library.png` | WP4 shell and routes table |
| DS-1 | High | Button groups touch: `.actions` has no global rule. | `play.js:59`, `deck-tools.js:55`, `collection.js:240/272`, `assembly.js:45`; only scoped rules (`style.css:349`, `editor.css:333`, `matchups.css:90/156`); `deck-tools.css:1` wraps without flex; `d-play.png`, `d-deck-gruul.png`, `d-collection.png`, `d-assembly.png` | One global `.actions` rule |
| DS-3 (also RS-7, INV-1) | Medium | No base style for date, search and textarea. The input rule is copied 6 times, and pages that miss it get native 21 px boxes under 16 px (iOS zooms on focus). | `editor.css:72`, `accessories.css:60`, `collection.css:43`, `tokens.css:10/80/99`, `play.css:26`; `d-collection.png`, `d-receipt-mtgmate.png`, `p390-receipt.json` | Base field rule, `font-size:max(16px,1rem)` |
| IA-8 (also GEN-1, RS-m1) | Medium | Amber "Only an admin can start simulations … while the PC is busy" on every page for non-admins. The mode is simply the default, so it's permanent. | `version.js:175-186`; `lib/permissions.py:120, 236-238`; `extra/ia-m-user1-library.png`, `extra/resp/c390-library.png` | Inline beside Forge controls only; reword |
| IA-7 (also DS-13, RS-12, MU-16) | Medium | The footer on every page has build hashes, Check for updates, Last checked, and (for Matt) Simulations and Forge-workers selects that save on change, about 290 px on a phone. | `index.html:113-128`; `version.js:97-108, 186-200`; `p390-receipt.png`, `d-matchup.png` | Settings page; one data line |
| DS-5 | Medium | Light theme looks flat: `--page #f9f9f7` vs `--surface #fcfcfb` (about 1.01:1), hairline borders, a 0.06-alpha shadow, and 29 ad-hoc box-shadows. | `style.css:19-20, 29, 50`; `d-library.png`, `d-shopping.png` | New page/surface values and `--shadow-1` |
| DS-6 | Medium | 37 font sizes, mostly 0.75–0.95 rem grey; 8 weights; no type tokens. | grep over `*.css`; `d-tokens.png`, `d-matchups.png` | Type scale (2.1) |
| INV-15 | Medium | Edit and Remove at equal weight on every record, about 1,400 buttons on Card list alone. | `tokens.js:425-430`, `accessories.js:285-292`, `collection.js:333`, `wishlist.js:117`; `extra/colrows.png` | Click to edit; Remove in the sheet |
| DS-8 | Medium | Every control is a 44 px outlined box even with a mouse. | `style.css:191-204`; no `pointer:fine` step; `q-library.png` | Fine-pointer density, quiet secondary buttons |
| IA-2 (also IA-3) | Medium | Back links come in 7+ forms, positions and labels. Child pages lose the deck: Packing plan and Game log opened from a deck go back to the library. | `deck.js:65`, `activity.js:27`, `history.js:33`, `play.js:54`, `assembly.js:28`, `receipts.js:87`, `matchups-detail.js:48`, `core.js:473`; good examples `variant.js:121`, `editor-screen.js:36` | `crumb()` helper, parent's name |
| IA-4 | Medium | One page, many names: Packing plan has 5 labels; Game log 3; the Library tab is titled "Library" but headed "Decks". | `library.js:34, 85-86`; `deck-tools.js:57-58`; `assembly.js:7, 23`; `play.js:5`; `collection.js:148` | One name per route from the routes table |
| IA-14 | Medium | Top bar isn't sticky, so long phone pages (Tokens 13k px, Collection 10k) strand the user. | `style.css:257-262` | Sticky top bar and phone tab bar |
| DS-m2 | Medium | Three disclosure looks. Flex `summary`s have no marker at all ("What's in it" on Tokens reads as plain text). | `tokens.css:75`, `collection.css:29`, `play.css:18`, `style.css:631`, `variant.css:27` vs `style.css:826-834` | One chevron on every summary |
| DS-7 | Low | 24 radii and 27 spacing values; only `--radius` and `--gutter` are tokens. | `style.css:57-58` | Radius and space scales |
| DS-14 | Low | Shared components live in page stylesheets; `devices.css` says "loaded last" but is 6th of 17; a dead `.card-dialog` block; dark tokens written twice. | `editor.css:1-16`, `devices.css:3`, `index.html:20-36`, `style.css:62-131, 719-745` | tokens, base and components files; one dark block |
| DS-15 | Low | One blue for links, primary buttons, info, focus and selection; colour literals. | `style.css:451-453, 676, 732-736`; `devices.css:61-62` | A separate `--accent`; tokenise literals |
| IA-6 (also RS-13) | Low | The theme select takes the most valuable top-bar spot; the profile button only switches person. (Default is already "Auto".) | `index.html:89-96`; `app.js:126` | Avatar menu |
| IA-11 | Low | "Who are you?" on every new tab and after 30 minutes away, which is deliberate for the shared iPad. | `app.js:44-49, 158-166` | Opt-in "This is my device" |
| IA-15 | Low | Tab titles are vague ("Receive delivery" for every order; "Deck history" without the deck). | `library.js:34`, `receipts.js:5`, `assembly.js:7`, `history.js:7`, `play.js:5` | Titles from the routes table, with the subject |
| RS-17 | Low | Small checkboxes and radios: assembly 20 px boxes in 32 px rows; matchup radios 18 px. | `collection.css:17-18`; `p390-assembly.json`, `p390-matchups.json` | 44 px label rows; 22 px accent-coloured box |
| RS-11 (wrap part) | Low | `overflow-wrap:anywhere` breaks words ("Phyrexia n Goblin"). | `tokens.css:42-43`, `accessories.css:18-20`; `p390-tokens.png` | `break-word` plus `hyphens:auto` |
| IA-m4 | Low | Members' nav offers pages that are empty for them (Game log, Activity) and 15 home products. | `extra/ia-d-user2-library.png` | Per-profile nav visibility |
| RS-1 | Low (method) | `m-*.png` shots were laid out at 500 px and cropped; the apparent overflow isn't real. | `extra/probe390.png`; `extra/resp/p390-*.json` (scrollW 390) | Use CDP emulation for phone shots |

### 4.2 Decks (library)

| ID | Sev | Finding | Evidence | Fix |
|---|---|---|---|---|
| LB-1 (also DS-9, RS-15) | High | Tiles are 4 lines of text with link-blue titles and no art or colour identity; the format line repeats the group heading. 29 tiles read like a database listing. | `library.js:250-271`; `style.css:504-516`; `q-library.png`, `d-library.png` | `art_crop` banner, pips, status pill, ink title |
| LB-2 (also DS-11, DS-m4) | Medium | Chips: "Target: 8 missing / Owned-only: all owned" is jargon; success chips on nearly every tile; the token chip "Coruscation Mage: on the way" doesn't say "token"; "all owned" and "on the way" side by side. | `library.js:226-239, 289-297`; `d-library.png` (Otter Limits) | One plain readiness chip; token on its own line |
| LB-3 (also IA-13) | Low | 15 products (10 Beginner Box halves) fill half the page; User2 is told they're "shared by both of you". Ready-to-play decks don't stand out. | `library.js:154, 180-207, 186`; `extra/ia-d-user2-library.png` | Fold products by default; fix the copy; add a sort |
| IA-12 (also RS-m3) | Low | The 4th filter wraps alone even at 2560 (`devices.css:12` has 3 columns); on phone the filters take about 330 px before the first deck. | `q-library.png`; `p390-library.png` | 4 columns or a flex row; phone filter sheet |

### 4.3 Deck page

| ID | Sev | Finding | Evidence | Fix |
|---|---|---|---|---|
| DK-1 | High | "Can I build this?" isn't answered at the top. Vader and Ani is 32 short but looks like a complete deck; the answer is the last section. | `deck.js:98-136, 85, 629-663`; `extra/ab-d-vader-top.png` vs `q-library.png` | Availability banner from `data.owned.totals` |
| DK-2 (also IA-9) | High | The card list doesn't mark missing, on-the-way or held cards. Owned vs needed repeats all 38 rows, zeros included, at the very bottom. | `deck.js:282-303, 670-717`; `extra/ab-d-gruul-lower2-0.png` | Badges and filter on the list; fold the table |
| DK-3 (also DS-16, RS-8) | High | The picture grid and peek need ≥1600 px and a mouse; laptops and iPads get 40×56 thumbnails of the whole card frame. | `devices.css:33-73, 107-131`; `style.css:670-691`; `d-deck-gruul.png`, `t1366-deck.png` | Grid from 1000 px with a remembered toggle; `art_crop` thumbnails |
| DK-4 (also RS-4, RS-6) | High | Nine "tabs" are jump links on one 11k px (desktop), 19k (Gruul phone) or 30k (Finneas) page. The phone nav cuts off at "Practice" with no sign it scrolls. | `deck.js:60-85`; `style.css:602-612`; `p390-gruulfull*.png`, `ab-p-vader-0.png` | 5 real tabs; fade mask; lazy loading |
| DK-m1 | High→see ED-1 | No editing on iPad or phone. | `editor.js:68-70` | WP11 (needs decision 1) |
| DK-5 (also RS-5, IA-m5) | Medium | Edit alone on its own row, then 6 equal buttons (3 of them exports): three bands of chrome; about 830 px before the first card on a phone. | `deck-tools.js:55-82`; `editor-deckpage.js:18`; `c390-deck.png`, `d-deck-gruul.png` | Edit and More ▾ on the title row |
| DK-7 | Medium | Tapping a card on a phone opens text with raw `{T}: Add {G}.` and the name twice. | `deck.js:378, 413-418`; `card-dialog.css:43-44`; `extra/ab-p-dialog.png` | Picture by default; symbols; swipe through cards |
| DK-8 (also RS-16, DK-m4) | Medium | Card names in the guide are bordered pills (44 px on touch) that break line height; the prose is 620 px wide in a 1,070 px box. | `deck-tools.js:84-93`; `style.css:749-761`; `devices.css:140`; `extra/ab-d-gruul-lower-0.png` | Dotted-underline text links; use the spare width |
| DK-9 | Medium | Mana costs are home-made lettered circles ("φ" for Phyrexian); raw `{R}` in the dialog and guide. | `deck.js:341-355, 416-418` | Scryfall symbol SVGs (WP5) |
| DK-10 | Medium | Every stats panel opens with an explanation box and a formula before the numbers; verdicts are tiny. | `stats.js:65, 218, 324, 598`; `ab-d-gruul-lower-0/1.png` | Verdict strip; closed "How is this worked out?" |
| DK-13 (also DK-m2, MU-12) | Medium | Deck matchups: 8 of 8 stale, duplicate opponents, up to 3 amber chips each. "Against each deck" says "No games yet" for opponents with results just above. | `extra/ab-d-gruul-lower-2.png`; `field.js` | One row per opponent; never "No games yet" when older results exist |
| DK-m3 (also ED-10) | Medium | The second list has three names: "Owned-only version", "Owned-only", "Substitute list". | `deck.js:126-134, 637`; `library.js:233`; `hands.js:51`; `editor-screen.js:91, 575` | One name everywhere (decision 2) |
| DK-6 | Low | Header facts are three bordered tiles for three words; "Sleeves are chosen…" on every unbuilt deck; a Tokens chip even when fine. | `deck.js:100-124, 156-158, 576-586` | One meta line; chips only for problems |
| DK-11 | Low | "Practice hands" vs "Deal a hand" vs heading "Try an opening hand"; the goldfish run starts on scroll. | `deck.js:60`; `practice.js:58-75`; `hands.js:43` | Rename; start on tab or button |
| DK-12 | Low | Test hand: "0 mulligans. Choose 0 cards to put on the bottom…", unsorted, no land/spell count, small images. | `hands.js:93-104`; `extra/ab-d-hand.png` | Plain status; sort; counts; larger images |
| DK-15 | Low | Two printings show as two rows ("Isolated Chapel LTC 318 / TDC 373"). Intentional, but reads like a mistake. | `deck.js:289`; `extra/ab-d-vader-top.png` | Group by name; printings in the subtitle |
| DK-m5 | Low | Two-version decks add a picker and a permanent explanation paragraph to the header. | `deck.js:126-134`; `editor-deckpage.js:20` | Fold into the availability banner |

### 4.4 Editor and new deck

| ID | Sev | Finding | Evidence | Fix |
|---|---|---|---|---|
| ED-2 | High | Adding a card takes 2 clicks (a click only selects); the Inspect/Add bar sits above the results; about 2.5 results visible at 1440×900. | `editor-cards.js:81, 113-120, 332`; `extra/w1440-search.png` | Click/Enter adds; remove the bar; 6+ rows |
| ED-4 (also ED-m1, ED-m4) | High | Every row repeats "N free now · 0 arriving · 0 in other decks · 0 missing" plus a red Remove (because "−" is disabled at 1); 40 px thumbnails; a 60-card deck is about 3,200 px. Basics are inconsistent. | `editor-save.js:163-179`; `editor-screen.js:641-664, 707, 737`; `d-edit-gruul.png` | One badge only when needed; "−" to 0 with Undo; dense rows; Visual toggle |
| ED-1 (also RS-9, DK-m1) | Medium | Phones and iPads (even 1366 px landscape) can't edit at all; this was a deliberate choice in `cd354e2`. | `editor.js:68-84`; `editor-deckpage.js:18`; `history.js:31`; `t1366-edit.png`, `extra/m390-handoff.png` | Decision 1: any pointer from 1000 px; phone Quick edit |
| ED-3 | Medium | Below 1600 px the search scrolls away, there's no peek, and the added row flashes off screen. | `devices.css:90-91, 110`; `d-edit-gruul.png` | Two columns from 1100; peek from 1400; "/" shortcut |
| ED-5 | Medium | No curve, colour or type summary while building. | `editor-screen.js:878-925` | Stats tab or strip |
| ED-6 | Medium | Search is by name only: no owned-first ranking, no filters, no way to browse the owned pool. Owned counts do show. | `lib/api/card_lookup.py:300-345`; `editor-cards.js:214-246` | Owned first, filters, "My collection" tab |
| ED-7 | Medium | Save → review sheet → Save → leaves the editor; no Ctrl+S. | `editor-save.js:329-351, 367-478, 516-528` | Save in place with a toast; Ctrl+S |
| ED-8 | Medium | Saving marks the write-up out of date, but no page can edit the write-up or clear the marker. | `editor-save.js:462`; `editor-deckpage.js:56-62` | Notes tab and "Mark write-up as current" |
| ED-9 | Medium | Enter always adds 1 ("4 bolt" adds 1); Paste only merges. | `editor-cards.js:164-178, 397-424, 636-654` | Parse the count; Shift = 4; Paste Replace with a diff |
| ED-11 (also ED-m3) | Medium | A blank new deck warns "0 cards" straight away; a long form sits above the search; most of a wide screen is empty. | `editor.js:760`; `editor-save.js:118-160`; `d-new.png` | Title and Format only; no warning until cards exist; two columns |
| ED-15 | Medium | Checks and missing cost are at the bottom of the list (about 3,000 px down). | `editor-screen.js:47-53`; `editor-save.js:304-327` | Summary in the side panel |
| ED-m2 | Medium | Results have no oracle snippet or price, and no peek below 1600 px. | `editor-cards.js:233-246` | Snippet, A$, hover popover |
| ED-12 | Low | Printing sheet: Move/Remove first, an explainer paragraph, 34×47 thumbnails. | `editor-cards.js:457-523`; `editor.css:344`; `extra/w1440p-printings.png` | Image grid; destructive actions last |
| ED-13 | Low | Instruction prose under every control. | `editor-screen.js:82, 96-98, 296, 497`; `editor-cards.js:52, 120` | Tooltips and a dismissible first-time tip |
| ED-14 | Low | Undo covers removals only. | `editor-screen.js:666-675, 781` | Snapshot history; Ctrl+Z |

### 4.5 Receive delivery

| ID | Sev | Finding | Evidence | Fix |
|---|---|---|---|---|
| R1 (also DS-2, IA-16, RS-2, INV-m1) | High | Each row is a collapsed "1 × Name": 15–51 clicks to check a parcel. No pictures; the two Ooze rows look identical; foil looks like nonfoil. 8 stacked fields per row (about 520 px each on a phone). Your PLAN.md request. | `receipts.js:57-72`; `PLAN.md:26, 37`; `d-receipt-mtgmate.png`, `d-receipt-tokens.png`, `extra/resp/x390-receipt-open.png` | WP6 board |
| R2 | High | Blockers, errors and success go to the page head while the button is at the bottom; no scroll or focus; the preview lands below the form. | `receipts.js:31, 88, 123-161`; `extra/rcpt-m-shop-b.png` | Sticky action bar; preview dialog |
| R3 | High | Condition and language are typed per row, inside collapsed rows; stale "check on arrival" notes deleted by hand. | `receipts.js:62-71`; `order show 2026-10-08-shop-a` | Bulk toolbar; note clean-up |
| R4 | High | Every field is free text; a printing or finish typo is caught only at preview, and that message is off screen. | `receipts.js:62-71`; `lib/inventory/receive.py:264-274` | Printing picker; segmented finish and condition; language select |
| R5 | Medium | Can't split a row (2 NM + 1 LP), though the server accepts it. | `receipts.js:64, 120`; `receive.py:251-263` | Split copies in the sheet |
| R6 (also RS-m2) | Medium | Single-component orders still need a heading checkbox; heading reads "cards · cards"; select and verified boxes are far apart. | `receipts.js:20, 39-44, 69-70` | Auto-select; plain headings |
| R7 | Medium | Date input unstyled, empty, no max (Game log already defaults to today). | `receipts.js:34`; `play.js:138`; `api/receipts.py:53-55` | Default today; Today/Yesterday control |
| R8 | Medium | Single-sided tokens need "single-sided verified" typed into Notes. | `receipts.js:54-56` | "Back is blank" switch; Swap front/back |
| R9 | Medium | Products show no card list. | `receive.py:222-228`; `receipts.js:47-52` | Product items as tiles; choice cards |
| R10 | Medium | Any edit silently clears the preview; inspection is one all-or-nothing tick. | `receipts.js:74-75, 82-83, 99-101` | "Changed since preview"; confirm earned by ticks |
| R13 | Medium | Work is lost on reload, phone sleep or the 30-minute expiry. | `receipts.js:57-79`; `api/receipts.py:44` | localStorage draft |
| R-m1 | Medium | Rows don't say which deck each card is for. | `receipts.js:58-59, 157-173` | Per-row deck chips; "Where these go" |
| R-m3 | Medium | Edited rows aren't marked; no progress count. | `receipts.js:58-72` | "Edited" chip; "9 of 15" |
| R11 (also RS-14) | Low | The checks bullet hangs outside the panel; jargon ("component", "payload"); the page says "leave blank" while the check says "record both". | `receipts.js:37, 45, 54-56, 75`; `style.css:152` | "To check" card; one plain line |
| R12 | Low | Preview reads like a database report ("13 new rows, 2 existing rows increased"). | `receipts.js:109-113, 136-143, 177-192` | Outcome first; deck chips |
| R14 | Low | 1200 px cap leaves 60% of QHD empty (matters once the grid exists). | `receipts.css:1`; `q-receipt.png` | Up to about 1800 px; side-panel sheet |
| R15 | Low | First view of a large order fetches images serially (design note for the grid). | `lib/cards.py:88, 760-780` | Lazy loading and skeletons; optional cache warm |
| R-m2 | Low | Members' read-only view is unstyled bullets with the same jargon. | `receipts.js:11-25`; `extra/rcpt-d-user1.png` | Same tiles, read only |

### 4.6 Shopping

| ID | Sev | Finding | Evidence | Fix |
|---|---|---|---|---|
| IA-10 (also DS-12) | Medium | "To buy: 0" takes a third of the page while decks are 8–62 cards short; the 65-card long-term plan is collapsed at the foot; no link to decks' missing cards. | `shopping.js:99-130`; `d-shopping.png` | "Decks still missing cards" group; long-term plan visible |
| IA-m2 (also INV-10) | Medium | "Needs checking" is a separate column titled by seller, with no link to its delivery. | `shopping.js:86-94`; `d-shopping.png` | Checks inside their delivery card |
| INV-m2 | Medium | Follow-up checks on received orders can't be cleared from the page, so they pile up (an older received order from 2026-09-29). | `shopping.js:86-94`; `server.py:102-106` | Done action (new guarded write route) |
| INV-10 (also IA-m3) | Medium | Five cards titled "eBay"; "On the way" shown twice; contents behind a native ▶ as text; no pictures. | `shopping.js:63-84`; `d-shopping.png`, `extra/q-shopping.png` | Seller · topic title; thumbnail strip |

### 4.7 Collection

| ID | Sev | Finding | Evidence | Fix |
|---|---|---|---|---|
| INV-3 | High | Card list: 705 bordered text cards, about 1,410 buttons, no images, sort or paging; "Condition NM · Language en" repeated. | `collection.js:301-340`; `collection.css:51-60`; `extra/colrows.png` | Sortable dense table; click to edit; "not recorded" filter |
| INV-6 (also RS-10) | Medium | Find tiles: three zero-heavy lines and a wrapped type line; 1 column on phone (205 px minimum), 146 px fixed image. | `collection.js:254, 257-263`; `collection.css:5-7`; `p390-collection.png` | Compact tile; `minmax(150px,1fr)`; fluid image |
| INV-7 | Medium | Filters need "Filter cards"; paging is Prev/Next at the bottom over 30 pages; found cards can't be edited. | `collection.js:216-274` | Live filters; full paging; "Edit copies" |
| INV-8 | Medium | Add card picks the printing from a text select of set codes. | `collection.js:436-465` | Printing picture strip |
| INV-16 | Medium | Space order differs: Find cards Home·User2·User3·User4; Card list and Tokens Home·User3·User2·User4. | `collection.js:127`; `core.js:229-235` | One client-side sort |
| DS-m3 | Low | Filter values truncate ("Owned and inco"); the Name field is narrow and its label on a different baseline. | `collection.css:2`; `d-collection.png` | Search spans 2 columns; shorter options |
| INV-18 | Low | Fixed explanatory notes as body text; 5 head buttons wrap. | `collection.js:139-154, 247`; `extra/coll-500.png` | (i) popover; primary action plus More |
| INV-19 | Low | Four different search and filter patterns across pages. | `d-tokens.png`, `d-collection.png`, `extra/colrows.png`, `d-wishlist.png` | One toolbar component |

### 4.8 Tokens

| ID | Sev | Finding | Evidence | Fix |
|---|---|---|---|---|
| INV-2 (also DS-10) | Medium | Grey letter squares ("A"/"C") on nearly every tile, while the panel above shows real token art. | `tokens.js:41-53, 395-397`; `lib/api/tokens.py:96`; `d-tokens.png` | Example art, labelled "printing not recorded" |
| INV-9 (also RS-11) | Medium | Tiles are walls of text: "Printing not recorded", provenance notes, repeated "Used for … (X side)" with a chip each; uneven heights; Edit/Remove on every tile. | `tokens.js:401-433`; `p390-tokens.png` | Notes into the sheet; deck chips; click to edit |
| DS-m4 | Low | "Your decks need, none owned" lists only on-the-way tokens; "received on the Receipts page" reads as already received. | `tokens.js:436-456` | Split Missing and On the way; "receive this order" |

### 4.9 Sleeves & boxes (Accessories)

| ID | Sev | Finding | Evidence | Fix |
|---|---|---|---|---|
| INV-13 (also DS-17) | Low | Product sleeves and box selects save on change (arrow keys on desktop save each step); grey "?" placeholders. | `accessories.js:61-66, 337-341`; `d-accessories.png` | Choose… sheet with confirm; dashed empty slot |
| INV-14 (also DS-17) | Low | Text-heavy cards (3-line names, "200 sleeves", "Free", "Picture" link); Edit/Remove on each. | `accessories.js:262-297` | Image, one meta line, "Not in use" badge, click to edit |
| INV-m3 | Low | Assignment is effectively unused: every item "Free", and the packing plan says "Sleeves: Not recorded". | `d-accessories.png`; `assembly.js:87-90` | "Built decks without sleeves" panel; Choose button |

### 4.10 Wishlist, Packing plan, Game log, Activity, History

| ID | Sev | Finding | Evidence | Fix |
|---|---|---|---|---|
| INV-4 | High | Packing plan: alphabetical text mixing "Wait for" and "Pull"; no pictures, no progress; ticks lost on reload. | `assembly.js:72, 120-140`; `extra/assembly-tfp.png` | Grouped steps, image tiles, sticky progress, saved ticks |
| INV-11 | Medium | Wishlist Remove is instant with no undo; notes, printing and source can't be edited; deck source shown as a slug. | `wishlist.js:71-84, 117-119`; `d-wishlist.png` | Undo toast; edit sheet; deck title link |
| INV-17 | Medium | Recording a home game is a long form with "Player 1/2 won" and a review step. | `play.js:131-180`; `d-play.png` | One-tap quick record |
| INV-12 | Medium | Activity headlines are raw CLI messages ("receive 2026-10-05-shop-c"); 20–40 rows expanded; no filters or links. | `activity.js:76-89`; `d-activity.png` | Plain headlines; collapse; filters; links |
| DK-14 | Medium | History shows git-era commit subjects, and clicking diffs against the current list, not the previous revision. | `history.js:11-37, 20-21`; `d-history.png` | Server-side diff against the previous revision, inline, with pictures |
| INV-5 | Low | Packing plan opens empty; "Add a deck" one dropdown at a time. | `assembly.js:36-41`; `d-assembly.png` | Deck checklist; presets |

### 4.11 Matchups, field, variant tests

| ID | Sev | Finding | Evidence | Fix |
|---|---|---|---|---|
| MU-01 | High | 78 results in an unsorted wall, only 40 distinct pairs (one pair 6 times); no filter, sort or grouping. | `matchups-overview.js:161-183, 479-497`; `d-matchups.png`, `extra/mu-q-matchups-a.png` | Matrix; one entry per pair |
| MU-03 | High | User1 sees "only an admin can start" above an enabled Play button; buttons only check `forge.ready`. | `matchups-overview.js:369, 401`; `matchups-detail.js:161`; `matchups-results.js:319`; `field.js:213`; `extra/mu-ph-matchup.png` | Use `may_start`; "Ask Matt" |
| MU-02 | Medium | Amber "Earlier engine" on 78 of 78 results, plus an engine-version box on the result page. | `matchups-overview.js:172-173`; `matchups.js:77-87` | Neutral tag, only when nothing newer exists |
| MU-04 | Medium | Result page: a good headline, then about 400 words of statistics before "More games". | `matchups-results.js:33-45, 156-260`; `d-matchup.png` | Verdict, then "Why confident", then Details |
| MU-05 | Medium | Three stop-rule modes with near-identical wording ("this deck" with two decks picked); a different vocabulary on each run form; "about 3–24 minutes". | `matchups.js:337-345, 388-428`; `field.js`; `variant.js` | Quick look / Settle it / Precise everywhere |
| MU-08 | Medium | Field part: 10 empty "No games yet" cards, contradicting the 34,800 earlier games shown just above. | `field.js:80-200`; `extra/mu-d-mwa-secfield.png` | One empty state with "Play the field" |
| MU-09 | Medium | Field jargon ("the tick is what the rating predicts", "±8 points of win rate"). | `field.js:16-17, ~123-164` | Rank and a sentence; sorted rows |
| MU-10 | Medium | Variant difference bars each have their own scale and no axis; one colour whatever the verdict. | `variant.js:64-77`; `variant.css:31-35` | One shared span, axis labels, verdict colour |
| MU-m1 | Medium | Pair page says "haven't played each other yet" when older results for that pair exist. | `matchups-detail.js:115-124, 165`; `extra/mu-ph-matchup.png` | List earlier results; "Not played with the current lists yet" |
| MU-06 | Low | All bars the same blue; the per-row whisker looks like a caret. | `matchups.js:240-276`; `matchups.css:16-22` | Diverging bars around 50% |
| MU-07 (also MU-m2) | Low | Meta shows "replay", "command line", "Claude (Milestone 8 check)"; wrapped lines start with "·". | `matchups-overview.js:174-175` vs `195-199`; `matchups.css:58-61` | Show only people; build the meta as one string |
| MU-11 | Low | Adaptive run bar measures the current stage while the text says "of up to 3,200"; it drops back at each check. | `matchups-detail.js:330-345`; `adaptive.py:361` | Segmented bar at the planned checks |
| MU-13 | Low | "Last checked … [Refresh]" on every simulation view, although pages poll. | `matchups-overview.js:15-40` | Remove; show only a lost-connection banner |
| MU-14 | Low | Panel holes at 1440; narrow column on QHD; 700 px-wide selects. | `d-matchup.png` | Two-column result page from 1600; dense grid |
| MU-15 | Low | Old titles ("Izzet Prowess") next to current ("Izzet Otters"). | `d-matchups.png` | Current title by deck id |
| MU-m3 | Low | The pilot box for Hare Raising cites Selesnya Rabbits' numbers. | `matchups-results.js:124-137` | Generic wording or the deck shown |

## Appendix: refuted claims

No finding was refuted outright. These parts of findings were:

- **DS-2:** "13 px checkbox on phone". It's 22 px (`receipts.css:5`); the shot was stale or from the 500 px capture.
- **Every m-\*.png overflow or clipping claim** (IA-5, IA-6, RS-1, INV-18, DS caveat): a 500 px layout cropped to 390, not real overflow.
- **IA-6:** "the theme select eats most of the phone header". That was the crop.
- **IA-12:** the cause isn't the 2-column grid in `style.css`. It's `devices.css:12`: 3 columns for 4 filters.
- **IA-9:** "make the library chips links". The tile is one `<a>`, so nested links are invalid; send the tile's link to the missing filter instead.
- **RS-2:** "receipt text inputs unstyled". `editor.css:72` styles them; only date, search and textarea aren't styled.
- **RS-11:** "Remove is one tap from destructive". It opens a confirm sheet with a reason (`tokens.js:537-554`).
- **RS-13:** "default to the system theme". It already does (`app.js:126`).
- **RS-17:** "20 px tap targets". The whole label row is about 32–48 px.
- **RS-16:** the 28 px measure came from `.sources-list`, not from prose.
- **DK-5:** "the computer-only line is about User1". It's a device test (`editor.js:68-70`) and hits every phone and iPad.
- **ED-1:** "an oversight". It was a deliberate decision (`cd354e2`).
- **ED-6:** "results don't show owned counts". They do (`editor-cards.js:214-246`).
- **ED-12:** "owned printing not marked". It's listed first and shows "5 owned".
- **INV-8:** "printings load only via the button". They load when the name changes (`collection.js:454`).
- **INV-13:** "fat-finger saves on a phone". Native pickers commit once; the real risk is arrow keys on desktop.
- **INV-14:** "Remove on in-use rows is unexplained". An "In use…" line is shown (`accessories.js:293-294`).
- **MU-11:** "the bar restarts from empty". It drops back at each stage rather than restarting.
- **DS-12:** "Needs checking duplicates the delivery cards". Its follow-ups belong to orders already received.
- **DS-5:** "about 13 shadows". It's 29, which strengthens the finding.
- **DS-8:** "ten outline buttons". It's 9 plus a primary.
- **DK-15:** two printings as two rows is intentional (`deck.js:289`). It's still worth grouping by name.
